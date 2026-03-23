"""MCP server for creating rich lexical graphs from PDFs.

Tools:
- create_lexical_graph: Parse PDF(s) and write graph (runs in background)
- check_processing_status: Monitor background job progress
- cancel_job: Cancel a running background job
- chunk_lexical_graph: Create Chunk nodes from Elements in the graph
- embed_chunks: Add embeddings to nodes (generic: any label, any text property)
- verify_lexical_graph: Structural checks + content reconstruction
- list_documents: Inventory of documents in the graph
- delete_document: Remove a document version with cascade
- set_active_version / clean_inactive: Version management
- assign_section_hierarchy: LLM-based section level assignment + heading chain propagation
- generate_chunk_descriptions: VLM-based image/table chunk descriptions
"""

from __future__ import annotations

import asyncio
import json
import logging
import multiprocessing
import os
import re
import sys
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Optional

import structlog
from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from neo4j import AsyncGraphDatabase, AsyncDriver
from pydantic import Field

load_dotenv()

from .chunkers.by_page import ByPageChunker
from .chunkers.by_section import BySectionChunker
from .chunkers.structured import StructuredChunker
from .chunkers.token_window import TokenWindowChunker
from .embedder import ChunkEmbedder
from .graph_reader import (
    delete_chunks_for_document,
    delete_document_cascade,
    deactivate_chunks_for_document,
    get_document,
    get_elements_for_document,
    get_existing_chunk_set_versions,
    get_pages_for_document,
    get_sections_for_document,
    list_all_documents,
)
from .graph_writer import (
    deactivate_versions,
    get_existing_versions,
    write_parsed_document,
)
from .job_manager import JobManager, JobStatus
from .models import ParsedDocument
from .postprocessing.section_hierarchy import assign_section_hierarchy as _assign_hierarchy
from .postprocessing.description_generator import generate_descriptions_batch as _generate_descriptions

# Configure structlog
structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


# Time-per-page estimates (seconds) for pre-flight warnings
_TIME_PER_PAGE: dict[str, float] = {
    "pymupdf": 1.5,
    "page_image": 2.5,
    "docling": 15.0,
    "vlm_blocks": 12.0,
}

# Threshold (seconds) above which a warning is included in the response
_WARNING_THRESHOLD_SECONDS = 120


DEFAULT_EXTRACTION_MODEL = "gpt-5-mini"


def _suggest_max_workers() -> int:
    """Auto-detect optimal ProcessPoolExecutor worker count based on available hardware.

    Docling loads neural network models (~1.5 GB RAM per worker) and is CPU-bound.
    We cap at 4 workers: diminishing returns beyond that for model inference.
    """
    try:
        import psutil
        available_ram_gb = psutil.virtual_memory().available / (1024 ** 3)
        ram_limited = max(1, int(available_ram_gb / 1.5))
    except ImportError:
        ram_limited = 2  # conservative fallback if psutil unavailable

    cpu_count = os.cpu_count() or 1
    cpu_limited = max(1, cpu_count - 2)  # leave 2 cores for event loop + Neo4j writes

    suggested = min(ram_limited, cpu_limited, 4)
    return max(1, suggested)


def create_mcp_server(
    neo4j_driver: AsyncDriver,
    database: str = "neo4j",
    embedding_model: str = "text-embedding-3-small",
    extraction_model: str = DEFAULT_EXTRACTION_MODEL,
    job_manager: JobManager | None = None,
    process_pool: ProcessPoolExecutor | None = None,
) -> FastMCP:
    """Create the lexical graph v2 MCP server."""

    mcp = FastMCP("mcp-neo4j-lexical-graph-v2")

    # Use provided or create defaults
    _job_manager = job_manager or JobManager()
    _auto_workers = _suggest_max_workers()
    _process_pool = process_pool or ProcessPoolExecutor(max_workers=_auto_workers)

    # ===========================================================
    # TOOL 1: create_lexical_graph (always async / background)
    # ===========================================================

    @mcp.tool(
        name="create_lexical_graph",
        annotations=ToolAnnotations(
            title="Create Lexical Graph",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    async def create_lexical_graph(
        path: str = Field(..., description="Path to a PDF file or a folder of PDFs"),
        output_dir: str = Field(..., description="Directory for logs and manifests"),
        document_id: Optional[str] = Field(
            None, description="Custom sourceId (defaults to filename). Ignored for folders."
        ),
        parse_mode: str = Field(
            "pymupdf", description="Parse mode: 'pymupdf', 'docling', 'page_image', or 'vlm_blocks' (experimental — prefer docling)"
        ),
        store_page_images: bool = Field(
            False, description="Render and store page images on Page nodes"
        ),
        dpi: int = Field(150, description="DPI for page image rendering"),
        metadata_json: Optional[str] = Field(
            None, description="JSON string of extra Document properties"
        ),
        skip_furniture: bool = Field(
            True, description="Skip headers/footers (docling and vlm_blocks modes)"
        ),
        extract_sections: bool = Field(
            True, description="Extract section hierarchy (docling and vlm_blocks modes)"
        ),
        extract_toc: bool = Field(
            True, description="Extract TOC entries (docling mode)"
        ),
        chunk_size: int = Field(500, description="Target tokens per chunk (pymupdf mode)"),
        chunk_overlap: int = Field(50, description="Token overlap between chunks (pymupdf mode)"),
        extract_images: bool = Field(
            True, description="Extract images as Element nodes with imageBase64 (pymupdf mode)"
        ),
        extract_tables: bool = Field(
            True, description="Extract tables as Element nodes with imageBase64 + text (pymupdf mode)"
        ),
        max_vlm_parallel: int = Field(
            10, description="Max concurrent VLM calls per document (vlm_blocks mode)"
        ),
        vlm_prompt: Optional[str] = Field(
            None, description="Custom VLM system prompt override (vlm_blocks mode)"
        ),
        text_preview_length: int = Field(
            200, description="Characters of text preview sent to VLM per block (vlm_blocks mode)"
        ),
        max_parallel: int = Field(
            0,
            description=(
                "Max documents to parse concurrently (docling/pymupdf modes). "
                "0 = auto-detect based on available RAM and CPU cores. "
                "vlm_blocks always runs sequentially."
            ),
        ),
    ) -> str:
        """Parse PDF(s) and create the lexical graph in Neo4j.

        Supports document versioning -- if a document with the same sourceId
        already exists, a new version is created and the old one is deactivated.

        **Parse modes:**
        - pymupdf: PyMuPDF extraction with image/table detection. Creates Document + Chunk + Element nodes.
          Set extract_images=False and extract_tables=False for text-only (Document + Chunk only).
        - docling: Full layout analysis with sections, tables, captions. (requires docling extra)
        - page_image: Page images + text. Creates Document + Page nodes for VLM use.
        - vlm_blocks: [EXPERIMENTAL — prefer docling] PyMuPDF blocks + VLM reading order/classification. Creates Document + Page + Element + Section nodes.

        **Returns immediately** with a job_id. Use check_processing_status(job_id) to monitor.
        """
        p = Path(path)
        if not p.exists():
            raise ToolError(f"Path not found: {path}")

        os.makedirs(output_dir, exist_ok=True)
        user_metadata = json.loads(metadata_json) if metadata_json else {}

        # -- Pre-flight: count files and pages --
        from .worker import count_pdf_pages

        is_folder = p.is_dir()
        if is_folder:
            pdf_files = sorted(p.glob("*.pdf")) + sorted(p.glob("*.PDF"))
            if not pdf_files:
                raise ToolError(f"No PDF files found in {path}")
        else:
            if not p.is_file():
                raise ToolError(f"Path is neither a file nor a directory: {path}")
            pdf_files = [p]

        files_total = len(pdf_files)
        total_pages = 0
        file_page_counts: list[tuple[str, int]] = []
        for pdf in pdf_files:
            try:
                pc = count_pdf_pages(str(pdf))
            except Exception:
                pc = 0
            file_page_counts.append((str(pdf), pc))
            total_pages += pc

        # Resolve effective parallelism for this job
        effective_parallel = max_parallel if max_parallel > 0 else _suggest_max_workers()
        if parse_mode == "vlm_blocks":
            effective_parallel = 1  # vlm_blocks is always sequential

        # Estimate processing time (adjusted for parallelism)
        rate = _TIME_PER_PAGE.get(parse_mode, 10.0)
        estimated_seconds = (total_pages * rate) / effective_parallel
        estimated_minutes = round(estimated_seconds / 60, 1)

        # Create the job
        job = _job_manager.create_job(
            path=str(p),
            parse_mode=parse_mode,
            is_folder=is_folder,
            files_total=files_total,
            total_pages_expected=total_pages,
        )

        # Prepare common kwargs for the worker
        parse_kwargs = {
            "dpi": dpi,
            "metadata": user_metadata,
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
            "extract_images": extract_images,
            "extract_tables": extract_tables,
            "skip_furniture": skip_furniture,
            "extract_sections": extract_sections,
            "extract_toc": extract_toc,
            "store_page_images": store_page_images,
            "max_vlm_parallel": max_vlm_parallel,
            "vlm_prompt": vlm_prompt,
            "text_preview_length": text_preview_length,
        }

        # Launch background task
        task = asyncio.create_task(
            _run_job(
                job_id=job.id,
                job_manager=_job_manager,
                process_pool=_process_pool,
                neo4j_driver=neo4j_driver,
                database=database,
                file_page_counts=file_page_counts,
                parse_mode=parse_mode,
                is_folder=is_folder,
                output_dir=output_dir,
                document_id=document_id,
                parse_kwargs=parse_kwargs,
                extraction_model=extraction_model,
                max_parallel=effective_parallel,
            )
        )
        _job_manager.register_task(job.id, task)

        # Build response
        response: dict[str, Any] = {
            "job_id": job.id,
            "status": "queued",
            "files_total": files_total,
            "total_pages": total_pages,
            "estimated_minutes": estimated_minutes,
            "max_parallel": effective_parallel,
            "message": (
                f"Job queued. Use check_processing_status('{job.id}') to monitor."
            ),
        }
        if estimated_seconds > _WARNING_THRESHOLD_SECONDS:
            response["warning"] = (
                f"Processing {files_total} PDF(s) ({total_pages} pages) "
                f"with {parse_mode} mode. Estimated time: ~{estimated_minutes} minutes."
            )

        return json.dumps(response, indent=2)

    # ===========================================================
    # TOOL 2: check_processing_status
    # ===========================================================

    @mcp.tool(
        name="check_processing_status",
        annotations=ToolAnnotations(
            title="Check Processing Status",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def check_processing_status(
        job_id: Optional[str] = Field(
            None,
            description="Job ID to check. If None, returns status of all jobs.",
        ),
    ) -> str:
        """Check the status of background lexical graph processing jobs.

        Returns progress info including elapsed time, estimated remaining time,
        files completed/remaining, pages processed, and elements extracted.
        """
        if job_id:
            job = _job_manager.get_job(job_id)
            if not job:
                raise ToolError(f"Job not found: {job_id}")
            return json.dumps(job.to_status_dict(), indent=2)
        else:
            jobs = _job_manager.list_jobs()
            if not jobs:
                return json.dumps({
                    "status": "success",
                    "message": "No jobs found.",
                    "jobs": [],
                })
            return json.dumps({
                "status": "success",
                "jobs": [j.to_status_dict() for j in jobs],
            }, indent=2)

    # ===========================================================
    # TOOL 3: cancel_job
    # ===========================================================

    @mcp.tool(
        name="cancel_job",
        annotations=ToolAnnotations(
            title="Cancel Job",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def cancel_job_tool(
        job_id: str = Field(..., description="Job ID to cancel"),
        cleanup: bool = Field(
            True,
            description="Delete partial graph data created by the cancelled job",
        ),
    ) -> str:
        """Cancel a running background processing job.

        If cleanup=True, deletes any documents that were already written to Neo4j
        by this job.
        """
        job = _job_manager.get_job(job_id)
        if not job:
            raise ToolError(f"Job not found: {job_id}")

        if job.status in (JobStatus.COMPLETE, JobStatus.FAILED, JobStatus.CANCELLED):
            return json.dumps({
                "status": "already_finished",
                "job_status": job.status.value,
                "message": f"Job {job_id} is already {job.status.value}.",
            })

        cancelled = _job_manager.cancel_job(job_id)

        result: dict[str, Any] = {
            "status": "cancelled" if cancelled else "cancel_failed",
            "job_id": job_id,
        }

        if cancelled and cleanup and job.documents_created:
            cleaned = 0
            for doc_info in job.documents_created:
                doc_id = doc_info.get("document_id")
                if doc_id:
                    try:
                        await delete_document_cascade(neo4j_driver, database, doc_id)
                        cleaned += 1
                    except Exception as e:
                        logger.warning(f"Cleanup failed for {doc_id}: {e}")
            result["documents_cleaned"] = cleaned

        result["message"] = f"Job {job_id} cancelled."
        return json.dumps(result, indent=2)

    # ===========================================================
    # TOOL 4: chunk_lexical_graph
    # ===========================================================

    @mcp.tool(
        name="chunk_lexical_graph",
        annotations=ToolAnnotations(
            title="Chunk Lexical Graph",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    async def chunk_lexical_graph(
        document_id: Optional[str] = Field(
            None,
            description="Document version id to chunk. If None, chunks all active documents without chunks.",
        ),
        strategy: str = Field(
            "token_window",
            description="Chunking strategy: 'token_window', 'structured', 'by_section', 'by_page'",
        ),
        chunk_size: int = Field(500, description="Target tokens per chunk"),
        chunk_overlap: int = Field(50, description="Token overlap (token_window only)"),
        include_tables_as_chunks: bool = Field(
            True, description="Create separate chunks for table elements"
        ),
        include_images_as_chunks: bool = Field(
            True, description="Create separate chunks for image/chart elements"
        ),
        clear_existing_chunks: bool = Field(
            False,
            description="If True, delete ALL existing chunk sets. If False, keep as inactive.",
        ),
        prepend_section_heading: bool = Field(
            True, description="Add section title to chunk text"
        ),
    ) -> str:
        """Create Chunk nodes from Elements in the Neo4j graph.

        Reads Elements and Sections from Neo4j (not from any external file).
        Supports chunk versioning: multiple chunk sets can coexist.

        **Strategies:**
        - token_window: Simple sliding window. No structure awareness.
        - structured: Section + token aware, element boundaries.
        - by_section: One chunk per section (falls back to by_page if no sections).
        - by_page: One chunk per page.
        """
        try:
            # Determine which documents to chunk
            doc_ids: list[str] = []
            if document_id:
                doc = await get_document(neo4j_driver, database, document_id)
                if not doc:
                    raise ToolError(f"Document not found: {document_id}")
                if doc.get("parseMode") in ("pymupdf", "text_only"):
                    return json.dumps({
                        "status": "success",
                        "message": (
                            f"Document '{document_id}' was created in pymupdf mode. "
                            "Chunks are created automatically during graph creation. "
                            "Use embed_chunks to add vector embeddings."
                        ),
                    })
                if doc.get("parseMode") == "page_image":
                    return json.dumps({
                        "status": "success",
                        "message": (
                            f"Document '{document_id}' was created in page_image mode. "
                            "Page-image documents have no Elements to chunk. "
                            "Use the entity MCP server with VLM for extraction."
                        ),
                    })
                doc_ids = [document_id]
            else:
                all_docs = await list_all_documents(neo4j_driver, database)
                doc_ids = [
                    d["id"]
                    for d in all_docs
                    if d.get("active")
                    and d.get("totalChunkCount", 0) == 0
                    and d.get("parseMode") not in ("pymupdf", "text_only", "page_image")
                ]
                if not doc_ids:
                    return json.dumps(
                        {"status": "success", "message": "No documents need chunking."}
                    )

            all_results = []
            for did in doc_ids:
                result = await _chunk_single_document(
                    neo4j_driver,
                    database,
                    document_id=did,
                    strategy=strategy,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                    include_tables_as_chunks=include_tables_as_chunks,
                    include_images_as_chunks=include_images_as_chunks,
                    clear_existing_chunks=clear_existing_chunks,
                    prepend_section_heading=prepend_section_heading,
                )
                all_results.append(result)

            return json.dumps(
                {"status": "success", "results": all_results}, indent=2
            )

        except ToolError:
            raise
        except Exception as e:
            logger.error("Chunking failed", error=str(e))
            raise ToolError(f"Chunking failed: {e}")

    # ===========================================================
    # TOOL 5: list_documents
    # ===========================================================

    @mcp.tool(
        name="list_documents",
        annotations=ToolAnnotations(
            title="List Documents",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def list_documents_tool() -> str:
        """List all documents in the graph, grouped by sourceId with version info."""
        try:
            docs = await list_all_documents(neo4j_driver, database)
            if not docs:
                return json.dumps({"status": "success", "documents": [], "message": "No documents in graph."})

            # Group by sourceId
            grouped: dict[str, list[dict[str, Any]]] = {}
            for d in docs:
                sid = d.get("sourceId", d["id"])
                grouped.setdefault(sid, []).append(d)

            output = []
            for sid, versions in grouped.items():
                output.append(
                    {
                        "sourceId": sid,
                        "name": versions[0].get("name"),
                        "source": versions[0].get("source"),
                        "versions": [
                            {
                                "id": v["id"],
                                "version": v.get("version"),
                                "active": v.get("active"),
                                "parseMode": v.get("parseMode"),
                                "pages": v.get("pageCount"),
                                "elements": v.get("elementCount"),
                                "sections": v.get("sectionCount"),
                                "chunks": v.get("totalChunkCount"),
                                "hasEmbeddings": v.get("hasEmbeddings"),
                                "createdAt": v.get("createdAt"),
                            }
                            for v in versions
                        ],
                    }
                )

            return json.dumps({"status": "success", "documents": output}, indent=2)

        except Exception as e:
            logger.error("list_documents failed", error=str(e))
            raise ToolError(f"Failed: {e}")

    # ===========================================================
    # TOOL 6: verify_lexical_graph
    # ===========================================================

    @mcp.tool(
        name="verify_lexical_graph",
        annotations=ToolAnnotations(
            title="Verify Lexical Graph",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def verify_lexical_graph(
        document_id: str = Field(..., description="Document version id to verify"),
        output_dir: str = Field(..., description="Directory to write reports"),
    ) -> str:
        """Run structural checks and content reconstruction on a document's graph.

        Checks: orphan nodes, broken NEXT chains, statistics, and
        reconstructs the document as Markdown for visual comparison.

        Default reconstruction uses elements (reading order).
        For pymupdf mode, chunks are always used (no separate elements).
        """
        try:
            os.makedirs(output_dir, exist_ok=True)
            doc = await get_document(neo4j_driver, database, document_id)
            if not doc:
                raise ToolError(f"Document not found: {document_id}")

            issues: list[str] = []
            stats: dict[str, Any] = {}
            parse_mode = doc.get("parseMode", "unknown")

            # --- Statistics ---
            pages = await get_pages_for_document(neo4j_driver, database, document_id)
            sections = await get_sections_for_document(neo4j_driver, database, document_id)

            # Elements: use page-based query for docling, direct query for pymupdf
            if parse_mode in ("pymupdf", "text_only"):
                async with neo4j_driver.session(database=database) as session:
                    result = await session.run(
                        """
                        MATCH (d:Document {id: $docId})-[:HAS_ELEMENT]->(e)
                        WITH e, toInteger(split(e.id, '_fig_')[-1]) AS figIdx,
                             toInteger(split(e.id, '_tbl_')[-1]) AS tblIdx
                        RETURN e.id AS id, e.type AS type, e.text AS text,
                               e.pageNumber AS pageNumber, e.level AS level
                        ORDER BY e.pageNumber, coalesce(figIdx, 0) + coalesce(tblIdx, 0)
                        """,
                        docId=document_id,
                    )
                    elements = await result.data()
            else:
                elements = await get_elements_for_document(neo4j_driver, database, document_id)

            type_counts: dict[str, int] = {}
            for e in elements:
                t = e.get("type", "unknown")
                type_counts[t] = type_counts.get(t, 0) + 1

            stats = {
                "parseMode": parse_mode,
                "pages": len(pages),
                "elements": len(elements),
                "elements_by_type": type_counts,
                "sections": len(sections),
            }

            # Check chunk stats
            async with neo4j_driver.session(database=database) as session:
                result = await session.run(
                    """
                    MATCH (c:Chunk)-[:PART_OF]->(d:Document {id: $docId})
                    RETURN count(c) AS cnt,
                           avg(c.tokenCount) AS avgTokens,
                           min(c.tokenCount) AS minTokens,
                           max(c.tokenCount) AS maxTokens,
                           sum(CASE WHEN c.active THEN 1 ELSE 0 END) AS activeChunks
                    """,
                    docId=document_id,
                )
                chunk_rec = await result.single()
                if chunk_rec:
                    stats["chunks"] = chunk_rec["cnt"]
                    stats["activeChunks"] = chunk_rec["activeChunks"]
                    stats["avgTokensPerChunk"] = round(chunk_rec["avgTokens"] or 0, 1)
                    stats["minTokens"] = chunk_rec["minTokens"]
                    stats["maxTokens"] = chunk_rec["maxTokens"]

            # Check HAS_ELEMENT rels from chunks (pymupdf mode)
            if parse_mode in ("pymupdf", "text_only") and elements:
                async with neo4j_driver.session(database=database) as session:
                    result = await session.run(
                        """
                        MATCH (d:Document {id: $docId})-[:HAS_ELEMENT]->(e)
                        WHERE NOT (:Chunk)-[:HAS_ELEMENT]->(e)
                        RETURN count(e) AS cnt
                        """,
                        docId=document_id,
                    )
                    rec = await result.single()
                    if rec and rec["cnt"] > 0:
                        issues.append(
                            f"Elements not referenced by any chunk: {rec['cnt']}"
                        )

            # --- Structural checks (docling / page_image modes) ---

            if parse_mode not in ("pymupdf", "text_only"):
                # Orphan elements (not connected to any page)
                async with neo4j_driver.session(database=database) as session:
                    result = await session.run(
                        """
                        MATCH (e:Element)
                        WHERE e.id STARTS WITH $prefix
                          AND NOT (:Page)-[:HAS_ELEMENT]->(e)
                        RETURN count(e) AS cnt
                        """,
                        prefix=document_id,
                    )
                    rec = await result.single()
                    if rec and rec["cnt"] > 0:
                        issues.append(f"Orphan elements (no page): {rec['cnt']}")

                # Broken NEXT_PAGE chain
                if len(pages) > 1:
                    async with neo4j_driver.session(database=database) as session:
                        result = await session.run(
                            """
                            MATCH (d:Document {id: $docId})-[:HAS_PAGE]->(p:Page)
                            WHERE NOT (p)-[:NEXT_PAGE]->() AND p.pageNumber < $maxPage
                            RETURN count(p) AS cnt
                            """,
                            docId=document_id,
                            maxPage=len(pages) - 1,
                        )
                        rec = await result.single()
                        if rec and rec["cnt"] > 0:
                            issues.append(f"Broken NEXT_PAGE chain: {rec['cnt']} gaps")

            # Broken NEXT_CHUNK chain
            if stats.get("chunks", 0) > 1:
                async with neo4j_driver.session(database=database) as session:
                    result = await session.run(
                        """
                        MATCH (c:Chunk)-[:PART_OF]->(d:Document {id: $docId})
                        WHERE c.active = true AND NOT (c)-[:NEXT_CHUNK]->()
                        WITH count(c) AS tailCount
                        RETURN CASE WHEN tailCount > 1
                               THEN tailCount - 1 ELSE 0 END AS gaps
                        """,
                        docId=document_id,
                    )
                    rec = await result.single()
                    if rec and rec["gaps"] > 0:
                        issues.append(f"Broken NEXT_CHUNK chain: {rec['gaps']} gaps")

            # --- Content reconstruction ---
            md_lines: list[str] = []
            md_lines.append(f"# {doc.get('name', document_id)}\n")
            md_lines.append(f"*Source: {doc.get('source', 'unknown')}*\n")
            md_lines.append(f"*Parse mode: {parse_mode}*\n\n")

            if parse_mode in ("pymupdf", "text_only"):
                # Build a lookup of element images for placeholder replacement
                import re as _re

                elem_images: dict[str, tuple[str, str]] = {}  # id -> (b64, mime)
                if elements:
                    async with neo4j_driver.session(database=database) as session:
                        result = await session.run(
                            """
                            MATCH (d:Document {id: $docId})-[:HAS_ELEMENT]->(e)
                            WHERE e.imageBase64 IS NOT NULL
                            RETURN e.id AS id, e.imageBase64 AS b64,
                                   e.imageMimeType AS mime, e.type AS type
                            """,
                            docId=document_id,
                        )
                        for rec in await result.data():
                            mime = rec.get("mime") or "image/png"
                            elem_images[rec["id"]] = (rec["b64"], mime)

                # Reconstruct from chunks (pymupdf has no pages)
                async with neo4j_driver.session(database=database) as session:
                    result = await session.run(
                        """
                        MATCH (c:Chunk)-[:PART_OF]->(d:Document {id: $docId})
                        WHERE c.active = true
                        RETURN c.text AS text, c.index AS idx, c.type AS type
                        ORDER BY c.index
                        """,
                        docId=document_id,
                    )
                    chunk_records = await result.data()

                placeholder_re = _re.compile(
                    r"\[(IMAGE|TABLE):\s*([^\]]+)\]"
                )

                for cr in chunk_records:
                    md_lines.append(f"---\n### Chunk {cr['idx']} (type: {cr['type']})\n")
                    chunk_text = cr["text"]
                    # Replace placeholders with embedded images
                    def _replace_placeholder(m: _re.Match) -> str:
                        elem_type = m.group(1)
                        elem_id = m.group(2).strip()
                        if elem_id in elem_images:
                            b64, mime = elem_images[elem_id]
                            img_md = f"![{elem_type}: {elem_id}](data:{mime};base64,{b64})"
                            return img_md
                        return m.group(0)

                    chunk_text = placeholder_re.sub(_replace_placeholder, chunk_text)
                    md_lines.append(f"{chunk_text}\n")
            elif parse_mode == "page_image":
                # Reconstruct from pages: show page image + extracted text
                # Fetch page images from graph
                page_images: dict[int, tuple[str, str]] = {}
                async with neo4j_driver.session(database=database) as session:
                    result = await session.run(
                        """
                        MATCH (d:Document {id: $docId})-[:HAS_PAGE]->(p:Page)
                        WHERE p.imageBase64 IS NOT NULL
                        RETURN p.pageNumber AS pn, p.imageBase64 AS b64,
                               p.imageMimeType AS mime
                        """,
                        docId=document_id,
                    )
                    for rec in await result.data():
                        mime = rec.get("mime") or "image/png"
                        page_images[rec["pn"]] = (rec["b64"], mime)

                for page in pages:
                    pn = page["pageNumber"]
                    md_lines.append(f"---\n## Page {pn + 1}\n")
                    # Embed the page image
                    if pn in page_images:
                        b64, mime = page_images[pn]
                        md_lines.append(
                            f"![Page {pn + 1}](data:{mime};base64,{b64})\n"
                        )
                    # Show extracted text
                    text = page.get("text", "")
                    if text:
                        md_lines.append(f"**Extracted text:**\n\n{text}\n")
                    md_lines.append("")

            else:
                # Reconstruct from pages/elements (docling mode)
                # Build element image lookup
                elem_images_other: dict[str, tuple[str, str]] = {}
                if elements:
                    async with neo4j_driver.session(database=database) as session:
                        result = await session.run(
                            """
                            MATCH (e:Element)
                            WHERE e.id STARTS WITH $prefix
                              AND e.imageBase64 IS NOT NULL
                            RETURN e.id AS id, e.imageBase64 AS b64,
                                   e.imageMimeType AS mime
                            """,
                            prefix=document_id,
                        )
                        for rec in await result.data():
                            mime = rec.get("mime") or "image/png"
                            elem_images_other[rec["id"]] = (rec["b64"], mime)

                for page in pages:
                    md_lines.append(f"---\n## Page {page['pageNumber'] + 1}\n")
                    page_elements = [
                        e for e in elements
                        if e.get("pageNumber") == page["pageNumber"]
                    ]
                    for e in page_elements:
                        etype = e.get("type", "paragraph")
                        text = e.get("text", "")
                        eid = e.get("id", "")
                        if etype == "heading":
                            level = e.get("level", 2)
                            md_lines.append(f"{'#' * (level + 1)} {text}\n")
                        elif etype == "table":
                            md_lines.append(f"\n**[TABLE]**\n{text}\n")
                            if eid in elem_images_other:
                                b64, mime = elem_images_other[eid]
                                md_lines.append(
                                    f"![Table: {eid}](data:{mime};base64,{b64})\n"
                                )
                        elif etype == "image":
                            md_lines.append(f"\n**[IMAGE]** {text}\n")
                            if eid in elem_images_other:
                                b64, mime = elem_images_other[eid]
                                md_lines.append(
                                    f"![Figure: {eid}](data:{mime};base64,{b64})\n"
                                )
                        elif etype == "caption":
                            md_lines.append(f"*Caption: {text}*\n")
                        else:
                            md_lines.append(f"{text}\n")
                    md_lines.append("")

            reconstruction_path = os.path.join(
                output_dir, f"{document_id}_reconstruction.md"
            )
            with open(reconstruction_path, "w", encoding="utf-8") as f:
                f.write("\n".join(md_lines))

            # --- Chunk-based reconstruction (if chunks exist) ---
            chunk_reconstruction_path: Optional[str] = None
            if stats.get("activeChunks", 0) > 0 and parse_mode not in ("pymupdf", "text_only"):
                # For pymupdf, the main reconstruction already uses chunks.
                # For docling/page_image, generate a separate chunk reconstruction.
                chunk_md = await _reconstruct_from_chunks(
                    neo4j_driver, database, document_id, doc
                )
                if chunk_md:
                    chunk_reconstruction_path = os.path.join(
                        output_dir, f"{document_id}_chunks_reconstruction.md"
                    )
                    with open(chunk_reconstruction_path, "w", encoding="utf-8") as f:
                        f.write(chunk_md)

            report = {
                "document_id": document_id,
                "statistics": stats,
                "issues": issues,
                "reconstruction_file": reconstruction_path,
                "status": "pass" if not issues else "issues_found",
            }
            if chunk_reconstruction_path:
                report["chunk_reconstruction_file"] = chunk_reconstruction_path

            # Write JSON report
            report_path = os.path.join(output_dir, f"{document_id}_report.json")
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2)

            return json.dumps(report, indent=2)

        except ToolError:
            raise
        except Exception as e:
            logger.error("Verification failed", error=str(e))
            raise ToolError(f"Verification failed: {e}")

    # ===========================================================
    # TOOL 7: assign_section_hierarchy
    # ===========================================================

    @mcp.tool(
        name="assign_section_hierarchy",
        annotations=ToolAnnotations(
            title="Assign Section Hierarchy",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        ),
    )
    async def assign_section_hierarchy_tool(
        document_id: Optional[str] = Field(
            None,
            description=(
                "Document version id to process. "
                "If omitted, runs on all active documents in parallel (LLM mode only)."
            ),
        ),
        model: Optional[str] = Field(
            None,
            description="LLM model to use (defaults to EXTRACTION_MODEL env var)",
        ),
        hierarchy: Optional[str] = Field(
            None,
            description=(
                'Optional: agent-provided hierarchy as JSON string, e.g. '
                '\'[{"id": "doc_v1_sec_0", "level": 1}, {"id": "doc_v1_sec_1", "level": 2}]\'. '
                "When provided, skips the LLM call and applies these levels directly. "
                "Requires document_id (agent mode cannot run on all docs at once)."
            ),
        ),
    ) -> str:
        """Use LLM to assign proper heading levels to sections, rebuild HAS_SUBSECTION, and propagate heading chains to chunks.

        Fixes Docling's flat level=1 sections. After running:
        - Section.level values reflect the real document hierarchy
        - HAS_SUBSECTION relationships link parent to child sections
        - Active Chunk.sectionContext contains the full heading chain (e.g., "Chapter 1 > Section 1.1 > Sub 1.1.1")

        Two modes:
        - LLM mode (default): automatically infers hierarchy using the configured LLM.
          When document_id is None, runs on ALL active documents concurrently.
        - Agent mode: pass a hierarchy JSON to apply levels directly (no LLM call).
          Requires document_id. If the LLM call fails, returns sections for the agent to decide.
        """
        try:
            use_model = model or extraction_model

            # Agent mode requires a specific document
            if hierarchy and not document_id:
                raise ToolError(
                    "document_id is required when providing a hierarchy JSON (agent mode). "
                    "Agent mode cannot run on all documents at once."
                )

            parsed_hierarchy = None
            if hierarchy:
                try:
                    parsed_hierarchy = json.loads(hierarchy)
                except json.JSONDecodeError as e:
                    raise ToolError(f"Invalid hierarchy JSON: {e}")

            # Single-document path
            if document_id:
                doc = await get_document(neo4j_driver, database, document_id)
                if not doc:
                    raise ToolError(f"Document not found: {document_id}")
                doc_name = doc.get("name", document_id)
                result = await _assign_hierarchy(
                    neo4j_driver, database, document_id, doc_name,
                    model=use_model, hierarchy=parsed_hierarchy,
                )
                if "error" in result:
                    raise ToolError(result["error"])
                return json.dumps(result, indent=2, default=str)

            # All-documents path: parallel LLM calls
            all_docs = await list_all_documents(neo4j_driver, database)
            active_docs = [d for d in all_docs if d.get("active")]
            if not active_docs:
                return json.dumps({"message": "No active documents found."})

            async def _process_one(doc: dict) -> dict:
                doc_id = doc["id"]
                doc_name = doc.get("name", doc_id)
                try:
                    result = await _assign_hierarchy(
                        neo4j_driver, database, doc_id, doc_name,
                        model=use_model, hierarchy=None,
                    )
                    return {"document_id": doc_id, "document_name": doc_name, **result}
                except Exception as exc:
                    return {"document_id": doc_id, "document_name": doc_name, "error": str(exc)}

            results = await asyncio.gather(*[_process_one(d) for d in active_docs])
            successes = [r for r in results if "error" not in r]
            failures = [r for r in results if "error" in r]
            return json.dumps(
                {
                    "documents_processed": len(active_docs),
                    "succeeded": len(successes),
                    "failed": len(failures),
                    "results": list(results),
                },
                indent=2,
                default=str,
            )

        except ToolError:
            raise
        except Exception as e:
            logger.error("assign_section_hierarchy failed", error=str(e))
            raise ToolError(f"Failed: {e}")

    # ===========================================================
    # TOOL 8: generate_chunk_descriptions
    # ===========================================================

    @mcp.tool(
        name="generate_chunk_descriptions",
        annotations=ToolAnnotations(
            title="Generate Chunk Descriptions",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        ),
    )
    async def generate_chunk_descriptions_tool(
        document_id: Optional[str] = Field(
            None,
            description=(
                "Document version id to process. "
                "None (default) = run for all active documents in the graph."
            ),
        ),
        model: Optional[str] = Field(
            None,
            description="VLM model for description generation (defaults to EXTRACTION_MODEL env var, must support vision)",
        ),
        parallel: int = Field(
            5, description="Max concurrent VLM calls"
        ),
    ) -> str:
        """Generate text descriptions for image/table chunks using a Vision Language Model.

        Works with both docling and pymupdf parse modes:
        - Docling: image/table chunks have imageBase64 directly
        - PyMuPDF: chunks link to Image/Table nodes via HAS_ELEMENT

        After running:
        - Chunk.textDescription stores the VLM description
        - Chunk.text is NOT modified (stays as original extracted content)
        - (PyMuPDF mode) Image/Table nodes receive the :Chunk label, documentName, active
        - (Page-image mode) Page nodes receive the :Chunk label

        When document_id is None, runs for all active documents sequentially.
        """
        try:
            use_model = model or extraction_model

            if document_id is not None:
                # Single document
                doc = await get_document(neo4j_driver, database, document_id)
                if not doc:
                    raise ToolError(f"Document not found: {document_id}")
                result = await _generate_descriptions(
                    neo4j_driver, database, document_id, model=use_model, parallel=parallel
                )
                if "error" in result:
                    raise ToolError(result["error"])
                return json.dumps(result, indent=2, default=str)

            else:
                # All active documents
                all_docs = await list_all_documents(neo4j_driver, database)
                active_docs = [d for d in all_docs if d.get("active", False)]
                if not active_docs:
                    return json.dumps({"status": "success", "message": "No active documents found.", "documents_processed": 0})

                results = []
                total_chunks = 0
                total_failed = 0
                for doc in active_docs:
                    doc_id = doc["id"]
                    r = await _generate_descriptions(
                        neo4j_driver, database, doc_id, model=use_model, parallel=parallel
                    )
                    results.append({"document_id": doc_id, **r})
                    total_chunks += r.get("chunks_processed", 0)
                    total_failed += r.get("chunks_failed", 0)

                return json.dumps({
                    "status": "success",
                    "documents_processed": len(active_docs),
                    "total_chunks_processed": total_chunks,
                    "total_chunks_failed": total_failed,
                    "model": use_model,
                    "results": results,
                }, indent=2, default=str)

        except ToolError:
            raise
        except Exception as e:
            logger.error("generate_chunk_descriptions failed", error=str(e))
            raise ToolError(f"Failed: {e}")

    # ===========================================================
    # TOOL 9: embed_chunks
    # ===========================================================

    @mcp.tool(
        name="embed_chunks",
        annotations=ToolAnnotations(
            title="Embed Chunks",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def embed_chunks(
        node_label: str = Field(
            "Chunk",
            description=(
                "Node label to embed. Default: 'Chunk'. "
                "Can be any label (e.g. 'Image', 'Table', 'Page', or custom labels). "
                "After generate_chunk_descriptions, Image/Table/Page nodes also have the :Chunk label "
                "and can be embedded together with text chunks using text_property_fallback."
            ),
        ),
        text_property: str = Field(
            "text",
            description=(
                "Primary property to embed. Default: 'text'. "
                "For Image/Table/Page nodes use 'textDescription' (set by generate_chunk_descriptions). "
                "When text_property_fallback is set, COALESCE(text_property, text_property_fallback) is used — "
                "nodes where both are null are skipped."
            ),
        ),
        text_property_fallback: Optional[str] = Field(
            None,
            description=(
                "Fallback text property when text_property is null on a node. "
                "When set, embeds COALESCE(text_property, text_property_fallback). "
                "Use text_property='textDescription', text_property_fallback='text' to prefer VLM descriptions "
                "for Image/Table nodes while still embedding raw text for regular Chunk nodes — "
                "all in one unified index."
            ),
        ),
        context_properties: list[str] = Field(
            default=["documentName", "sectionContext"],
            description=(
                "Properties prepended to the text before embedding, in order. "
                "Default: ['documentName', 'sectionContext']. "
                "Missing properties are skipped. Set to [] to embed text_property alone."
            ),
        ),
        index_prefilter_properties: Optional[list[str]] = Field(
            default=["documentName", "type"],
            description=(
                "Properties used as prefilters on the vector index for efficient filtered search. "
                "Default: ['documentName', 'type']. Supports multiple properties (Neo4j 5.18+ WITH [...] syntax). "
                "Set to null or [] to create a plain vector index with no prefilter."
            ),
        ),
        document_id: Optional[str] = Field(
            None,
            description=(
                "Filter to a specific document: only embeds nodes where documentName = document_id. "
                "None = all active nodes without embeddings."
            ),
        ),
        overwrite: bool = Field(
            False,
            description="Re-embed nodes that already have embeddings. Default: false (skip already-embedded nodes).",
        ),
        parallel: int = Field(10, description="Max concurrent embedding batches"),
        model: str = Field(
            default=embedding_model, description="Embedding model (via LiteLLM)"
        ),
        create_fulltext_index: bool = Field(
            True, description=(
                "Create fulltext index on text_property (and text_property_fallback if set) "
                "of the node_label"
            )
        ),
    ) -> str:
        """Embed a text property on any node label and store as a vector index.

        Composes the embedding input as: context_properties (joined) + text_property.
        When text_property_fallback is set, uses COALESCE(text_property, text_property_fallback)
        per node — nodes where both are null are skipped.

        **Recommended usage after generate_chunk_descriptions (pymupdf with images/tables):**
          text_property='textDescription', text_property_fallback='text'
          → Table/Image nodes: embedded from VLM description (textDescription)
          → Regular Chunk nodes: embedded from raw extracted text (text)
          → All stored in one unified chunk_text_embedding index

        **Minimal usage (text-only docs, no images/tables):**
          Use defaults — text_property='text', no fallback needed.
          Auto-detection: if defaults are used and any Chunk node has textDescription set
          (i.e. generate_chunk_descriptions was run), automatically switches to
          text_property='textDescription' + text_property_fallback='text'. The output
          reports auto_detected_fallback=true when this happens.

        **Prefilter (index_prefilter_properties):**
          Adds metadata properties to the vector index for efficient filtered search.
          Default ['documentName', 'type'] lets you search within a document or by node type
          (e.g. only table descriptions, only text chunks).
          Uses Neo4j 5.18+ WITH [...] syntax — requires Neo4j 5.18 or later.

        **Fulltext index:**
          Created on text_property (and text_property_fallback if set), covering both raw text
          and VLM descriptions in one index.

        **Index names:**
          Vector: {node_label.lower()}_text_embedding
          Fulltext: {node_label.lower()}_text_fulltext

        Synchronous — no status poll needed.
        """
        # Warn early if likely misconfiguration: visual node labels with 'text' but no fallback
        visual_labels = {"Image", "Table", "Page"}
        if node_label in visual_labels and text_property == "text" and not text_property_fallback:
            return json.dumps({
                "status": "warning",
                "message": (
                    f"node_label='{node_label}' has no 'text' property. "
                    f"These nodes use 'textDescription' (set by generate_chunk_descriptions). "
                    f"Re-run with text_property='textDescription' to embed {node_label} nodes."
                ),
                "embedded": 0,
            })

        # Auto-detect: if defaults are unchanged (text_property='text', no fallback),
        # check whether any Chunk has textDescription — if so, auto-enable the fallback
        # so Table/Image VLM descriptions are included without requiring explicit parameters.
        auto_detected_fallback = False
        if text_property == "text" and text_property_fallback is None and node_label == "Chunk":
            try:
                async with neo4j_driver.session(database=database) as session:
                    result = await session.run(
                        "MATCH (c:Chunk) WHERE c.textDescription IS NOT NULL RETURN c LIMIT 1"
                    )
                    record = await result.single()
                    if record is not None:
                        text_property = "textDescription"
                        text_property_fallback = "text"
                        auto_detected_fallback = True
            except Exception:
                pass  # detection failure is non-fatal, proceed with original values

        try:
            # Build text expression: COALESCE when fallback is provided
            if text_property_fallback:
                text_expr = f"coalesce(c.`{text_property}`, c.`{text_property_fallback}`)"
                text_not_null = f"(c.`{text_property}` IS NOT NULL OR c.`{text_property_fallback}` IS NOT NULL)"
            else:
                text_expr = f"c.`{text_property}`"
                text_not_null = f"c.`{text_property}` IS NOT NULL"

            # Build context concatenation dynamically
            context_parts = " + ' ' + ".join(
                f"coalesce(c.`{p}`, '')" for p in context_properties
            )
            if context_parts:
                composed_text = f"trim({context_parts} + ' ' + {text_expr})"
            else:
                composed_text = text_expr

            # Build WHERE clause
            embedding_prop = "text_embedding"
            where_clauses = [text_not_null]
            if not overwrite:
                where_clauses.append(f"c.`{embedding_prop}` IS NULL")
            if document_id:
                where_clauses.append("c.documentName = $document_id")
            elif node_label == "Chunk":
                # active filter is only meaningful for Chunk nodes (versioned)
                where_clauses.append("coalesce(c.active, true) = true")

            where_str = " AND ".join(where_clauses)

            # Use elementId(c) as the stable identifier — works for any node label
            # including entity nodes that have no 'id' property.
            query = f"""
                MATCH (c:`{node_label}`)
                WHERE {where_str}
                RETURN elementId(c) AS eid,
                  {composed_text} AS text
            """
            params: dict[str, Any] = {}
            if document_id:
                params["document_id"] = document_id

            async with neo4j_driver.session(database=database) as session:
                result = await session.run(query, **params)
                records = await result.data()

            if not records:
                return json.dumps({
                    "status": "success",
                    "message": f"No {node_label} nodes need embedding.",
                    "embedded": 0,
                })

            logger.info(f"Embedding {len(records)} {node_label} nodes")

            embedder = ChunkEmbedder(model=model)
            pairs = [(r["eid"], r["text"]) for r in records]
            embedded = await embedder.embed_many(pairs, parallel=parallel)

            # Write embeddings using native VECTOR type, matched by elementId
            total_updated = 0
            dims = len(embedded[0][1]) if embedded else 0
            batch_size = 100
            for i in range(0, len(embedded), batch_size):
                batch = [{"eid": eid, "embedding": emb} for eid, emb in embedded[i : i + batch_size]]
                async with neo4j_driver.session(database=database) as session:
                    result = await session.run(
                        f"""
                        CYPHER 25
                        UNWIND $embeddings AS item
                        MATCH (c:`{node_label}`)
                        WHERE elementId(c) = item.eid
                        SET c.`{embedding_prop}` = vector(item.embedding, $dims, FLOAT32)
                        RETURN count(c) AS updated
                        """,
                        embeddings=batch,
                        dims=dims,
                    )
                    record = await result.single()
                    total_updated += record["updated"] if record else 0

            # Create vector index
            index_name = f"{node_label.lower()}_{embedding_prop}"
            if dims > 0:
                try:
                    async with neo4j_driver.session(database=database) as session:
                        prefilter_props = index_prefilter_properties or []
                        if prefilter_props:
                            prefilter_list = ", ".join(f"c.`{p}`" for p in prefilter_props)
                            await session.run(
                                f"""
                                CYPHER 25
                                CREATE VECTOR INDEX `{index_name}` IF NOT EXISTS
                                FOR (c:`{node_label}`) ON c.`{embedding_prop}`
                                WITH [{prefilter_list}]
                                OPTIONS {{indexConfig: {{
                                    `vector.dimensions`: $dims,
                                    `vector.similarity_function`: 'cosine'
                                }}}}
                                """,
                                dims=dims,
                            )
                        else:
                            await session.run(
                                f"""
                                CYPHER 25
                                CREATE VECTOR INDEX `{index_name}` IF NOT EXISTS
                                FOR (c:`{node_label}`) ON c.`{embedding_prop}`
                                OPTIONS {{indexConfig: {{
                                    `vector.dimensions`: $dims,
                                    `vector.similarity_function`: 'cosine'
                                }}}}
                                """,
                                dims=dims,
                            )
                except Exception as e:
                    logger.warning(f"Vector index note: {e}")

            if create_fulltext_index:
                # Index the resolved text property(ies) for fulltext search
                ft_props = [text_property]
                if text_property_fallback and text_property_fallback not in ft_props:
                    ft_props.append(text_property_fallback)
                fulltext_index_name = f"{node_label.lower()}_text_fulltext"
                ft_prop_list = ", ".join(f"c.`{p}`" for p in ft_props)
                try:
                    async with neo4j_driver.session(database=database) as session:
                        await session.run(
                            f"CREATE FULLTEXT INDEX `{fulltext_index_name}` IF NOT EXISTS "
                            f"FOR (c:`{node_label}`) ON EACH [{ft_prop_list}]"
                        )
                except Exception as e:
                    logger.warning(f"Fulltext index note: {e}")

            prefilter_props = index_prefilter_properties or []
            prefilter_msg = f" with {prefilter_props} prefilter" if prefilter_props else ""
            auto_msg = (
                " (auto-detected textDescription on Chunk nodes — "
                "using textDescription with text fallback)"
                if auto_detected_fallback else ""
            )
            return json.dumps(
                {
                    "status": "success",
                    "node_label": node_label,
                    "text_property": text_property,
                    "text_property_fallback": text_property_fallback,
                    "context_properties": context_properties,
                    "index_prefilter_properties": prefilter_props,
                    "auto_detected_fallback": auto_detected_fallback,
                    "model": model,
                    "embedded": total_updated,
                    "dimensions": dims,
                    "vector_index": index_name,
                    "message": (
                        f"Embedded {total_updated} {node_label} nodes (VECTOR FLOAT32, {dims}d). "
                        f"Vector index '{index_name}'{prefilter_msg} created.{auto_msg}"
                    ),
                },
                indent=2,
            )

        except Exception as e:
            logger.error("Embedding failed", error=str(e))
            raise ToolError(f"Embedding failed: {e}")

    # ===========================================================
    # TOOL 10: set_active_version
    # ===========================================================

    @mcp.tool(
        name="set_active_version",
        annotations=ToolAnnotations(
            title="Set Active Version",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def set_active_version(
        document_id: str = Field(..., description="Document version to activate"),
        chunk_set_version: Optional[int] = Field(
            None,
            description="If provided, activate this chunk set version for the document.",
        ),
    ) -> str:
        """Activate a specific document version (deactivates others with same sourceId).

        Optionally also activate a specific chunk set version.
        """
        try:
            doc = await get_document(neo4j_driver, database, document_id)
            if not doc:
                raise ToolError(f"Document not found: {document_id}")

            source_id = doc.get("sourceId", document_id)

            # Deactivate all versions, then activate the target
            await deactivate_versions(neo4j_driver, database, source_id)
            async with neo4j_driver.session(database=database) as session:
                await session.run(
                    "MATCH (d:Document {id: $id}) SET d.active = true",
                    id=document_id,
                )

            msg = f"Activated document version {document_id}."

            # Optionally set chunk version
            if chunk_set_version is not None:
                await deactivate_chunks_for_document(
                    neo4j_driver, database, document_id
                )
                async with neo4j_driver.session(database=database) as session:
                    result = await session.run(
                        """
                        MATCH (c:Chunk)-[:PART_OF]->(d:Document {id: $docId})
                        WHERE c.chunkSetVersion = $ver
                        SET c.active = true
                        RETURN count(c) AS cnt
                        """,
                        docId=document_id,
                        ver=chunk_set_version,
                    )
                    rec = await result.single()
                    cnt = rec["cnt"] if rec else 0
                msg += f" Activated chunk set v{chunk_set_version} ({cnt} chunks)."

            return json.dumps({"status": "success", "message": msg})

        except ToolError:
            raise
        except Exception as e:
            logger.error("set_active_version failed", error=str(e))
            raise ToolError(f"Failed: {e}")

    # ===========================================================
    # TOOL 11: clean_inactive
    # ===========================================================

    @mcp.tool(
        name="clean_inactive",
        annotations=ToolAnnotations(
            title="Clean Inactive Versions",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def clean_inactive(
        source_id: Optional[str] = Field(
            None, description="Clean inactive document versions for this sourceId. None = all."
        ),
        document_id: Optional[str] = Field(
            None, description="Clean inactive chunk sets for this document. None = all active docs."
        ),
    ) -> str:
        """Delete inactive document versions and/or inactive chunk sets."""
        try:
            results: dict[str, Any] = {}

            if document_id:
                # Clean inactive chunks for a specific document
                cnt = await delete_chunks_for_document(
                    neo4j_driver, database, document_id, only_inactive=True
                )
                results["inactive_chunks_deleted"] = cnt
            elif source_id:
                # Delete inactive document versions for a sourceId
                query = """
                    MATCH (d:Document {sourceId: $sourceId})
                    WHERE d.active = false
                    RETURN d.id AS id
                """
                async with neo4j_driver.session(database=database) as session:
                    result = await session.run(query, sourceId=source_id)
                    inactive_ids = [r["id"] for r in await result.data()]

                total_deleted: dict[str, int] = {}
                for did in inactive_ids:
                    counts = await delete_document_cascade(
                        neo4j_driver, database, did
                    )
                    for k, v in counts.items():
                        total_deleted[k] = total_deleted.get(k, 0) + v
                results["inactive_documents_deleted"] = len(inactive_ids)
                results["nodes_deleted"] = total_deleted
            else:
                # Clean all inactive across all sourceIds
                query = """
                    MATCH (d:Document)
                    WHERE d.active = false
                    RETURN d.id AS id
                """
                async with neo4j_driver.session(database=database) as session:
                    result = await session.run(query)
                    inactive_ids = [r["id"] for r in await result.data()]

                total_deleted = {}
                for did in inactive_ids:
                    counts = await delete_document_cascade(
                        neo4j_driver, database, did
                    )
                    for k, v in counts.items():
                        total_deleted[k] = total_deleted.get(k, 0) + v
                results["inactive_documents_deleted"] = len(inactive_ids)
                results["nodes_deleted"] = total_deleted

            return json.dumps({"status": "success", **results}, indent=2)

        except Exception as e:
            logger.error("clean_inactive failed", error=str(e))
            raise ToolError(f"Failed: {e}")

    # ===========================================================
    # TOOL 12: delete_document
    # ===========================================================

    @mcp.tool(
        name="delete_document",
        annotations=ToolAnnotations(
            title="Delete Document",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def delete_document(
        document_id: str = Field(..., description="Document version id to delete"),
    ) -> str:
        """Delete a document version and ALL its children (pages, elements, sections, chunks, TOC entries)."""
        try:
            doc = await get_document(neo4j_driver, database, document_id)
            if not doc:
                raise ToolError(f"Document not found: {document_id}")

            counts = await delete_document_cascade(
                neo4j_driver, database, document_id
            )

            return json.dumps(
                {
                    "status": "success",
                    "document_id": document_id,
                    "deleted": counts,
                    "message": f"Deleted document {document_id} and all children.",
                },
                indent=2,
            )
        except ToolError:
            raise
        except Exception as e:
            logger.error("delete_document failed", error=str(e))
            raise ToolError(f"Failed: {e}")

    return mcp


# ===========================================================
# Background job runner + Neo4j writing helpers
# ===========================================================


def _remap_version_in_result(
    worker_result: dict[str, Any],
    source_id: str,
    old_version: int,
    new_version: int,
) -> dict[str, Any]:
    """Remap all IDs in a worker result from one version to another.

    IDs follow the pattern: {source_id}_v{version} or contain it as a prefix.
    This rewrites them so parsed results can be written with the correct version
    even if the version changed between parse time and write time.
    """
    import json as _json
    import copy

    old_suffix = f"_v{old_version}"
    new_suffix = f"_v{new_version}"

    parse_mode = worker_result.get("parse_mode", "")

    if parse_mode == "pymupdf":
        result = copy.deepcopy(worker_result)
        old_doc_id = f"{source_id}_v{old_version}"
        new_doc_id = f"{source_id}_v{new_version}"

        # Remap doc_id
        if result.get("doc_id") == old_doc_id:
            result["doc_id"] = new_doc_id

        # Remap doc_props
        if "doc_props" in result:
            props = result["doc_props"]
            if props.get("id") == old_doc_id:
                props["id"] = new_doc_id
            if "version" in props:
                props["version"] = new_version

        # Remap element records
        for rec in result.get("element_records", []):
            if "id" in rec and old_suffix in rec["id"]:
                rec["id"] = rec["id"].replace(old_suffix, new_suffix, 1)

        # Remap chunk records
        for chunk in result.get("chunks", []):
            if "id" in chunk and old_suffix in chunk["id"]:
                chunk["id"] = chunk["id"].replace(old_suffix, new_suffix, 1)
            # Chunk text may contain element references -- leave text as-is
            # (element placeholders reference element IDs, remap those too)
            for key in ("hasElementIds",):
                if key in chunk and isinstance(chunk[key], list):
                    chunk[key] = [
                        eid.replace(old_suffix, new_suffix, 1) if old_suffix in eid else eid
                        for eid in chunk[key]
                    ]

        return result

    else:
        # docling / page_image: the entire parsed_doc is a dict
        # Serialize to JSON, do a global string replace on the version suffix, deserialize
        raw = _json.dumps(worker_result)
        old_id_prefix = f"{source_id}_v{old_version}"
        new_id_prefix = f"{source_id}_v{new_version}"
        raw = raw.replace(old_id_prefix, new_id_prefix)
        # Also fix the version integer in the document properties
        raw = raw.replace(
            f'"version": {old_version}',
            f'"version": {new_version}',
        )
        return _json.loads(raw)


async def _run_job(
    job_id: str,
    job_manager: JobManager,
    process_pool: ProcessPoolExecutor,
    neo4j_driver: AsyncDriver,
    database: str,
    file_page_counts: list[tuple[str, int]],
    parse_mode: str,
    is_folder: bool,
    output_dir: str,
    document_id: Optional[str],
    parse_kwargs: dict[str, Any],
    extraction_model: str = "gpt-5-mini",
    max_parallel: int = 1,
) -> None:
    """Background task that orchestrates parallel-parse, sequential-write processing.

    Files are parsed in batches of max_parallel concurrently (using the process pool),
    then each result is written to Neo4j sequentially (keeps version handling atomic).
    vlm_blocks always runs sequentially (async parser, cannot run in subprocess).

    For each file:
      1. Submit parsing to subprocess (tentative version=1)
      2. After all batch parses complete, write each result sequentially
      3. Determine real version atomically (right before write)
      4. Remap IDs if version changed, write to Neo4j with retry
      5. Update job progress
    """
    from .worker import parse_single_pdf  # noqa: F401 — ensures pickle works in pool

    loop = asyncio.get_running_loop()
    progress_queue: multiprocessing.Queue = multiprocessing.Queue()
    worker_kwargs = {
        k: v for k, v in parse_kwargs.items()
        if k not in ("max_vlm_parallel", "vlm_prompt", "text_preview_length")
    }

    try:
        # Process files in batches of max_parallel
        for batch_start in range(0, len(file_page_counts), max_parallel):
            batch = file_page_counts[batch_start:batch_start + max_parallel]

            # Check cancellation before each batch
            job = job_manager.get_job(job_id)
            if not job or job.status == JobStatus.CANCELLED:
                logger.info("Job cancelled, stopping", job_id=job_id)
                return

            job_manager.update_status(job_id, JobStatus.PARSING)
            batch_size = len(batch)

            # --- PARSE PHASE: submit all files in batch concurrently ---
            batch_infos: list[tuple[str, int, str]] = []  # (pdf_path, page_count, source_id)
            parse_futures: list[Any] = []

            for pdf_path, page_count in batch:
                pdf_name = Path(pdf_path).name
                source_id = document_id if (not is_folder and document_id) else Path(pdf_path).stem
                batch_infos.append((pdf_path, page_count, source_id))

                current_file_label = (
                    pdf_name if batch_size == 1
                    else f"{batch_size} files in parallel"
                )
                job_manager.update_progress(
                    job_id,
                    current_file=current_file_label,
                    current_file_pages=page_count,
                    current_stage="parsing",
                )

                logger.info(
                    "Submitting for parsing",
                    job_id=job_id,
                    file=pdf_name,
                    mode=parse_mode,
                    batch_size=batch_size,
                )

                if parse_mode == "vlm_blocks":
                    # VLM blocks: async parser, runs in the event loop (not subprocess)
                    from .parsers.vlm_blocks import VLMBlocksParser

                    vlm_parser = VLMBlocksParser(
                        vlm_model=extraction_model,
                        max_parallel=parse_kwargs.get("max_vlm_parallel", 10),
                    )
                    parsed_doc = await vlm_parser.parse_async(
                        pdf_path=pdf_path,
                        source_id=source_id,
                        version=1,
                        metadata=parse_kwargs.get("metadata"),
                        dpi=parse_kwargs.get("dpi", 150),
                        store_page_images=parse_kwargs.get("store_page_images", False),
                        vlm_prompt=parse_kwargs.get("vlm_prompt"),
                        skip_furniture=parse_kwargs.get("skip_furniture", True),
                        extract_sections=parse_kwargs.get("extract_sections", True),
                        text_preview_length=parse_kwargs.get("text_preview_length", 200),
                    )
                    # Wrap as a resolved future so the gather below works uniformly
                    fut: asyncio.Future[Any] = loop.create_future()
                    fut.set_result({"parse_mode": "vlm_blocks", "parsed_doc": parsed_doc.model_dump()})
                    parse_futures.append(fut)
                else:
                    parse_futures.append(
                        loop.run_in_executor(
                            process_pool,
                            _make_worker_call(
                                pdf_path=pdf_path,
                                source_id=source_id,
                                version=1,  # tentative; remapped at write time
                                parse_mode=parse_mode,
                                progress_queue=progress_queue,
                                **worker_kwargs,
                            ),
                        )
                    )

            # Wait for all parse tasks in this batch (exceptions are returned, not raised)
            batch_results = await asyncio.gather(*parse_futures, return_exceptions=True)

            # --- WRITE PHASE: write each result sequentially ---
            job_manager.update_status(job_id, JobStatus.WRITING)

            for (pdf_path, page_count, source_id), worker_result in zip(batch_infos, batch_results):
                pdf_name = Path(pdf_path).name

                # Handle parse-phase errors
                if isinstance(worker_result, BaseException):
                    if isinstance(worker_result, BrokenProcessPool):
                        raise RuntimeError(
                            f"Subprocess crashed while parsing {pdf_name}. "
                            "This may be due to memory or a docling bug."
                        )
                    logger.error(
                        f"Failed to parse {pdf_name}",
                        job_id=job_id,
                        error=str(worker_result),
                    )
                    job_manager.update_progress(
                        job_id,
                        files_failed=job_manager.get_job(job_id).files_failed + 1,
                    )
                    job_manager.get_job(job_id).errors.append({
                        "filename": pdf_name,
                        "error": str(worker_result),
                    })
                    if not is_folder:
                        raise worker_result  # type: ignore[misc]
                    continue

                job_manager.update_progress(job_id, current_stage="writing")

                try:
                    # Atomically determine real version (right before write)
                    existing = await get_existing_versions(neo4j_driver, database, source_id)
                    real_version = 1
                    if existing:
                        real_version = max(v["version"] for v in existing) + 1
                        await deactivate_versions(neo4j_driver, database, source_id)

                    if real_version != 1:
                        logger.info(
                            "Version remapped",
                            job_id=job_id,
                            file=pdf_name,
                            tentative=1,
                            real=real_version,
                        )
                        worker_result = _remap_version_in_result(
                            worker_result, source_id, 1, real_version
                        )

                    version = real_version

                    # Write to Neo4j with retry on constraint violation
                    max_retries = 2
                    for attempt in range(max_retries + 1):
                        try:
                            doc_summary = await _write_worker_result_to_neo4j(
                                neo4j_driver, database, worker_result, source_id, version
                            )
                            break
                        except Exception as write_err:
                            err_str = str(write_err)
                            if "ConstraintValidationFailed" in err_str and attempt < max_retries:
                                version += 1
                                logger.warning(
                                    "Constraint conflict, retrying with higher version",
                                    job_id=job_id,
                                    file=pdf_name,
                                    new_version=version,
                                    attempt=attempt + 1,
                                )
                                worker_result = _remap_version_in_result(
                                    worker_result, source_id, version - 1, version
                                )
                            else:
                                raise

                    # Record successful document
                    job_manager.update_progress(
                        job_id,
                        files_completed=job_manager.get_job(job_id).files_completed + 1,
                        total_pages_processed=(
                            job_manager.get_job(job_id).total_pages_processed + page_count
                        ),
                        total_elements_extracted=(
                            job_manager.get_job(job_id).total_elements_extracted
                            + doc_summary.get("elements", 0)
                        ),
                    )
                    job_manager.get_job(job_id).documents_created.append(doc_summary)

                    logger.info(
                        "Document written to Neo4j",
                        job_id=job_id,
                        document_id=doc_summary.get("document_id"),
                    )

                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error(
                        f"Failed to process {pdf_name}",
                        job_id=job_id,
                        error=str(e),
                    )
                    job_manager.update_progress(
                        job_id,
                        files_failed=job_manager.get_job(job_id).files_failed + 1,
                    )
                    job_manager.get_job(job_id).errors.append({
                        "filename": pdf_name,
                        "error": str(e),
                    })
                    if not is_folder:
                        raise

        # All files done -- write manifest for folders
        job = job_manager.get_job(job_id)
        if is_folder and job:
            os.makedirs(output_dir, exist_ok=True)
            manifest = {
                "timestamp": datetime.now().isoformat(),
                "folder_path": job.path,
                "parse_mode": parse_mode,
                "total_pdfs": job.files_total,
                "successful": job.files_completed,
                "errors": job.files_failed,
                "documents_created": job.documents_created,
                "error_details": job.errors,
            }
            manifest_path = os.path.join(output_dir, "manifest.json")
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2)
            job_manager.update_progress(job_id, result={"manifest_file": manifest_path})

        # Mark complete
        job_manager.update_status(job_id, JobStatus.COMPLETE)
        logger.info("Job complete", job_id=job_id)

    except asyncio.CancelledError:
        logger.info("Job task cancelled", job_id=job_id)
        job_manager.update_status(job_id, JobStatus.CANCELLED)
    except Exception as e:
        logger.error("Job failed", job_id=job_id, error=str(e))
        job_manager.update_status(job_id, JobStatus.FAILED, error=str(e))
    finally:
        # Drain the progress queue
        try:
            while not progress_queue.empty():
                progress_queue.get_nowait()
        except Exception:
            pass


def _make_worker_call(
    pdf_path: str,
    source_id: str,
    version: int,
    parse_mode: str,
    progress_queue: Optional[multiprocessing.Queue] = None,
    **kwargs: Any,
) -> Any:
    """Create a callable for run_in_executor.

    ProcessPoolExecutor requires a callable (no args), so we wrap
    parse_single_pdf with functools.partial.
    """
    import functools
    from .worker import parse_single_pdf

    return functools.partial(
        parse_single_pdf,
        pdf_path=pdf_path,
        source_id=source_id,
        version=version,
        parse_mode=parse_mode,
        progress_queue=None,  # Queue can't be pickled across processes easily
        **kwargs,
    )


async def _write_worker_result_to_neo4j(
    driver: AsyncDriver,
    database: str,
    worker_result: dict[str, Any],
    source_id: str,
    version: int,
) -> dict[str, Any]:
    """Write the result from a subprocess worker to Neo4j.

    Returns a summary dict with document info.
    """
    parse_mode = worker_result["parse_mode"]

    if parse_mode == "pymupdf":
        return await _write_pymupdf_result(driver, database, worker_result)
    else:
        # docling, page_image, or vlm_blocks -- reconstruct ParsedDocument from dict
        parsed = ParsedDocument.model_validate(worker_result["parsed_doc"])
        summary = await write_parsed_document(driver, database, parsed)
        return summary


async def _write_pymupdf_result(
    driver: AsyncDriver,
    database: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    """Write pymupdf worker output to Neo4j (Document + Elements + Chunks)."""

    doc_id = result["doc_id"]
    doc_props = result["doc_props"]
    element_records = result["element_records"]
    chunks = result["chunks"]

    # Create Document node
    async with driver.session(database=database) as session:
        await session.run("CREATE (d:Document) SET d = $props", props=doc_props)
    logger.info("Document node created", doc_id=doc_id, mode="pymupdf")

    # Create Image/Table nodes (pymupdf visual assets get dedicated labels)
    if element_records:
        batch_size = 50
        for i in range(0, len(element_records), batch_size):
            batch = element_records[i : i + batch_size]
            async with driver.session(database=database) as session:
                await session.run(
                    """
                    UNWIND $records AS rec
                    CREATE (e)
                    SET e.id = rec.id,
                        e.type = rec.type,
                        e.pageNumber = rec.pageNumber,
                        e.coordinates = rec.coordinates
                    WITH e, rec
                    FOREACH (_ IN CASE WHEN rec.type = 'image' THEN [1] ELSE [] END |
                        SET e:Image
                    )
                    FOREACH (_ IN CASE WHEN rec.type = 'table' THEN [1] ELSE [] END |
                        SET e:Table
                    )
                    FOREACH (_ IN CASE WHEN rec.text IS NOT NULL THEN [1] ELSE [] END |
                        SET e.text = rec.text
                    )
                    FOREACH (_ IN CASE WHEN rec.imageBase64 IS NOT NULL THEN [1] ELSE [] END |
                        SET e.imageBase64 = rec.imageBase64,
                            e.imageMimeType = rec.imageMimeType
                    )
                    WITH e
                    MATCH (d:Document {id: $docId})
                    CREATE (d)-[:HAS_ELEMENT]->(e)
                    """,
                    records=batch,
                    docId=doc_id,
                )

    # Create Chunk nodes
    if chunks:
        batch_size = 200
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            async with driver.session(database=database) as session:
                await session.run(
                    """
                    UNWIND $records AS rec
                    CREATE (c:Chunk)
                    SET c.id = rec.id, c.text = rec.text, c.index = rec.index,
                        c.tokenCount = rec.tokenCount, c.type = rec.type,
                        c.chunkSetVersion = rec.chunkSetVersion, c.active = rec.active,
                        c.strategy = rec.strategy, c.strategyParams = rec.strategyParams,
                        c.documentName = rec.documentName
                    WITH c
                    MATCH (d:Document {id: $docId})
                    CREATE (c)-[:PART_OF]->(d)
                    """,
                    records=batch,
                    docId=doc_id,
                )

        # NEXT_CHUNK chain
        if len(chunks) > 1:
            pairs = [
                {"fromId": chunks[i]["id"], "toId": chunks[i + 1]["id"]}
                for i in range(len(chunks) - 1)
            ]
            async with driver.session(database=database) as session:
                await session.run(
                    """
                    UNWIND $pairs AS pair
                    MATCH (a:Chunk {id: pair.fromId})
                    MATCH (b:Chunk {id: pair.toId})
                    CREATE (a)-[:NEXT_CHUNK]->(b)
                    """,
                    pairs=pairs,
                )

    # HAS_ELEMENT relationships from chunks
    if element_records and chunks:
        placeholder_re = re.compile(r"\[(IMAGE|TABLE): ([^\]]+)\]")
        chunk_elem_rels: list[dict[str, str]] = []
        for chunk in chunks:
            for _kind, elem_id in placeholder_re.findall(chunk["text"]):
                chunk_elem_rels.append({
                    "chunkId": chunk["id"],
                    "elementId": elem_id,
                })
        if chunk_elem_rels:
            for i in range(0, len(chunk_elem_rels), 200):
                batch = chunk_elem_rels[i : i + 200]
                async with driver.session(database=database) as session:
                    await session.run(
                        """
                        UNWIND $rels AS rel
                        MATCH (c:Chunk {id: rel.chunkId})
                        OPTIONAL MATCH (i:Image {id: rel.elementId})
                        OPTIONAL MATCH (t:Table {id: rel.elementId})
                        WITH c, coalesce(i, t) AS target
                        WHERE target IS NOT NULL
                        CREATE (c)-[:HAS_ELEMENT]->(target)
                        """,
                        rels=batch,
                    )

    return {
        "document_id": doc_id,
        "source_id": result["source_id"],
        "version": result["version"],
        "pages": result["total_pages"],
        "elements": len(element_records),
        "images": result["fig_counter"],
        "tables": result["tbl_counter"],
        "chunks": len(chunks),
    }


async def _reconstruct_from_chunks(
    driver: AsyncDriver,
    database: str,
    document_id: str,
    doc: dict[str, Any],
) -> Optional[str]:
    """Walk the NEXT_CHUNK chain and reconstruct markdown from chunk content.

    For image/table chunks, embeds the image from the linked Element node.
    Returns the full markdown string, or None if no chunks exist.
    """
    # Fetch active chunks walking the NEXT_CHUNK chain
    async with driver.session(database=database) as session:
        result = await session.run(
            """
            MATCH (c:Chunk)-[:PART_OF]->(d:Document {id: $docId})
            WHERE c.active = true
            OPTIONAL MATCH (c)-[:NEXT_CHUNK]->(nxt:Chunk)
            RETURN c.id AS id, c.text AS text, c.index AS idx,
                   c.type AS type, c.tokenCount AS tokenCount,
                   c.strategy AS strategy, c.chunkSetVersion AS csVersion,
                   c.documentName AS docName,
                   c.sectionHeading AS sectionHeading,
                   c.sectionContext AS sectionContext,
                   nxt.id AS nextId
            """,
            docId=document_id,
        )
        rows = await result.data()

    if not rows:
        return None

    # Walk the chain to get correct order
    by_id: dict[str, dict[str, Any]] = {}
    has_prev: set[str] = set()
    for row in rows:
        by_id[row["id"]] = row
        if row.get("nextId"):
            has_prev.add(row["nextId"])

    heads = [rid for rid in by_id if rid not in has_prev]
    ordered: list[dict[str, Any]] = []
    visited: set[str] = set()
    for head in sorted(heads):
        current = head
        while current and current not in visited:
            visited.add(current)
            row = by_id.get(current)
            if row:
                ordered.append(row)
                current = row.get("nextId")
            else:
                break
    # Append any orphans
    for rid, row in by_id.items():
        if rid not in visited:
            ordered.append(row)

    # Build element image lookup for image/table chunks
    chunk_element_images: dict[str, tuple[str, str]] = {}
    async with driver.session(database=database) as session:
        result = await session.run(
            """
            MATCH (c:Chunk)-[:HAS_ELEMENT]->(e)
            WHERE c.id STARTS WITH $prefix AND e.imageBase64 IS NOT NULL
            RETURN c.id AS chunkId, e.imageBase64 AS b64,
                   e.imageMimeType AS mime, e.type AS eType
            """,
            prefix=document_id,
        )
        for rec in await result.data():
            mime = rec.get("mime") or "image/png"
            chunk_element_images[rec["chunkId"]] = (rec["b64"], mime)

    # Build image lookup for pymupdf-style placeholder replacement
    # Searches across all label types (Element, Image, Table)
    import re as _re
    placeholder_re = _re.compile(r"\[(IMAGE|TABLE):\s*([^\]]+)\]")
    all_elem_images: dict[str, tuple[str, str]] = {}
    async with driver.session(database=database) as session:
        result = await session.run(
            """
            MATCH (d:Document {id: $docId})-[:HAS_ELEMENT]->(e)
            WHERE e.imageBase64 IS NOT NULL
            RETURN e.id AS id, e.imageBase64 AS b64, e.imageMimeType AS mime
            """,
            docId=document_id,
        )
        for rec in await result.data():
            mime = rec.get("mime") or "image/png"
            all_elem_images[rec["id"]] = (rec["b64"], mime)

    # Generate markdown
    lines: list[str] = []
    lines.append(f"# {doc.get('name', document_id)} (Chunk Reconstruction)\n")
    lines.append(f"*Source: {doc.get('source', 'unknown')}*\n")
    parse_mode = doc.get("parseMode", "unknown")
    strategy = ordered[0].get("strategy", "unknown") if ordered else "unknown"
    cs_ver = ordered[0].get("csVersion", "?") if ordered else "?"
    lines.append(f"*Parse mode: {parse_mode} | Chunking: {strategy} (set {cs_ver})*\n")
    lines.append(f"*Total chunks: {len(ordered)}*\n\n")

    for chunk in ordered:
        ctype = chunk.get("type", "text")
        idx = chunk.get("idx", "?")
        tokens = chunk.get("tokenCount", "?")
        sec_heading = chunk.get("sectionHeading", "")
        sec_context = chunk.get("sectionContext", "")
        heading_info = f" | section: {sec_heading}" if sec_heading else ""
        context_info = f" | context: {sec_context}" if sec_context and sec_context != sec_heading else ""
        lines.append(f"---\n### Chunk {idx} (type: {ctype}, tokens: {tokens}{heading_info}{context_info})\n")

        if ctype == "image":
            # Show caption text if any
            text = chunk.get("text", "")
            if text:
                lines.append(f"{text}\n")
            # Embed the image from the linked Element
            cid = chunk["id"]
            if cid in chunk_element_images:
                b64, mime = chunk_element_images[cid]
                lines.append(f"![{ctype}: {cid}](data:{mime};base64,{b64})\n")
        elif ctype == "table":
            text = chunk.get("text", "")
            if text:
                lines.append(f"{text}\n")
            cid = chunk["id"]
            if cid in chunk_element_images:
                b64, mime = chunk_element_images[cid]
                lines.append(f"![table: {cid}](data:{mime};base64,{b64})\n")
        else:
            text = chunk.get("text", "")
            # Replace any element placeholders with embedded images
            def _replace_placeholder(m: _re.Match) -> str:
                elem_id = m.group(2).strip()
                if elem_id in all_elem_images:
                    b64, mime = all_elem_images[elem_id]
                    return f"![{m.group(1)}: {elem_id}](data:{mime};base64,{b64})"
                return m.group(0)

            text = placeholder_re.sub(_replace_placeholder, text)
            lines.append(f"{text}\n")
        lines.append("")

    return "\n".join(lines)


async def _chunk_single_document(
    driver: AsyncDriver,
    database: str,
    document_id: str,
    strategy: str,
    chunk_size: int,
    chunk_overlap: int,
    include_tables_as_chunks: bool,
    include_images_as_chunks: bool,
    clear_existing_chunks: bool,
    prepend_section_heading: bool,
) -> dict[str, Any]:
    """Chunk a single document and write chunks to Neo4j."""

    # Handle existing chunks
    existing_versions = await get_existing_chunk_set_versions(driver, database, document_id)
    chunk_set_version = 1
    if existing_versions:
        if clear_existing_chunks:
            deleted = await delete_chunks_for_document(driver, database, document_id)
            logger.info(f"Cleared {deleted} existing chunks")
        else:
            max_ver = max(v["ver"] for v in existing_versions if v["ver"] is not None) if existing_versions else 0
            chunk_set_version = (max_ver or 0) + 1
            await deactivate_chunks_for_document(driver, database, document_id)

    # Select chunker
    if strategy == "token_window":
        chunker = TokenWindowChunker(
            chunk_size=chunk_size, chunk_overlap=chunk_overlap
        )
    elif strategy == "structured":
        chunker = StructuredChunker(chunk_size=chunk_size)
    elif strategy == "by_section":
        chunker = BySectionChunker()
    elif strategy == "by_page":
        chunker = ByPageChunker()
    else:
        raise ToolError(f"Unknown strategy: {strategy}")

    # Create chunks
    chunks = await chunker.create_chunks(
        driver,
        database,
        document_id,
        include_tables_as_chunks=include_tables_as_chunks,
        include_images_as_chunks=include_images_as_chunks,
        prepend_section_heading=prepend_section_heading,
    )

    if not chunks:
        return {
            "document_id": document_id,
            "chunks_created": 0,
            "message": "No elements with text found.",
        }

    # Re-assign chunk IDs to include chunk_set_version for uniqueness
    for idx, c in enumerate(chunks):
        c.index = idx
        c.id = f"{document_id}_cs{chunk_set_version}_chunk_{idx:04d}"

    strategy_params = json.dumps({
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap,
        "include_tables_as_chunks": include_tables_as_chunks,
        "include_images_as_chunks": include_images_as_chunks,
        "prepend_section_heading": prepend_section_heading,
    })

    # Write chunks to Neo4j in batches
    batch_size = 200
    total_created = 0
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        records = [
            {
                "id": c.id,
                "text": c.text,
                "index": c.index,
                "tokenCount": c.token_count,
                "type": c.type,
                "chunkSetVersion": chunk_set_version,
                "active": True,
                "strategy": strategy,
                "strategyParams": strategy_params,
                "documentId": document_id,
                "documentName": c.document_name,
                "sectionHeading": c.section_heading,
                "sectionContext": c.section_context,
                "imageBase64": c.image_base64 or None,
                "imageMimeType": c.image_mime_type or None,
                "textAsHtml": c.text_as_html or None,
            }
            for c in batch
        ]

        async with driver.session(database=database) as session:
            result = await session.run(
                """
                UNWIND $records AS rec
                CREATE (c:Chunk)
                SET c.id = rec.id,
                    c.text = rec.text,
                    c.index = rec.index,
                    c.tokenCount = rec.tokenCount,
                    c.type = rec.type,
                    c.chunkSetVersion = rec.chunkSetVersion,
                    c.active = rec.active,
                    c.strategy = rec.strategy,
                    c.strategyParams = rec.strategyParams,
                    c.documentName = rec.documentName,
                    c.sectionHeading = rec.sectionHeading,
                    c.sectionContext = rec.sectionContext,
                    c.imageBase64 = rec.imageBase64,
                    c.imageMimeType = rec.imageMimeType,
                    c.textAsHtml = rec.textAsHtml
                WITH c, rec
                FOREACH (_ IN CASE WHEN rec.type = 'image' THEN [1] ELSE [] END |
                    SET c:Image
                )
                FOREACH (_ IN CASE WHEN rec.type = 'table' THEN [1] ELSE [] END |
                    SET c:Table
                )
                WITH c, rec
                MATCH (d:Document {id: rec.documentId})
                CREATE (c)-[:PART_OF]->(d)
                RETURN count(c) AS cnt
                """,
                records=records,
            )
            rec = await result.single()
            total_created += rec["cnt"] if rec else 0

    # Write HAS_ELEMENT relationships from chunks
    # Uses coalesce across Element/Image/Table labels for cross-mode compatibility
    elem_rels = []
    for c in chunks:
        for eid in c.element_ids:
            elem_rels.append({"chunkId": c.id, "elementId": eid})
    if elem_rels:
        for i in range(0, len(elem_rels), batch_size):
            batch = elem_rels[i : i + batch_size]
            async with driver.session(database=database) as session:
                await session.run(
                    """
                    UNWIND $rels AS rel
                    MATCH (c:Chunk {id: rel.chunkId})
                    OPTIONAL MATCH (e1:Element {id: rel.elementId})
                    OPTIONAL MATCH (e2:Image {id: rel.elementId})
                    OPTIONAL MATCH (e3:Table {id: rel.elementId})
                    WITH c, coalesce(e1, e2, e3) AS target
                    WHERE target IS NOT NULL
                    CREATE (c)-[:HAS_ELEMENT]->(target)
                    """,
                    rels=batch,
                )

    # NEXT_CHUNK chain
    if len(chunks) > 1:
        ordered_ids = [c.id for c in sorted(chunks, key=lambda x: x.index)]
        pairs = [
            {"fromId": ordered_ids[i], "toId": ordered_ids[i + 1]}
            for i in range(len(ordered_ids) - 1)
        ]
        for i in range(0, len(pairs), batch_size):
            batch = pairs[i : i + batch_size]
            async with driver.session(database=database) as session:
                await session.run(
                    """
                    UNWIND $pairs AS pair
                    MATCH (a:Chunk {id: pair.fromId})
                    MATCH (b:Chunk {id: pair.toId})
                    CREATE (a)-[:NEXT_CHUNK]->(b)
                    """,
                    pairs=batch,
                )

    return {
        "document_id": document_id,
        "strategy": strategy,
        "chunk_set_version": chunk_set_version,
        "chunks_created": total_created,
        "message": f"Created {total_created} chunks (set v{chunk_set_version}).",
    }


# ===========================================================
# Entry point
# ===========================================================


async def main(
    db_url: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    database: Optional[str] = None,
    embedding_model: str = "text-embedding-3-small",
    extraction_model: str = DEFAULT_EXTRACTION_MODEL,
    transport: Literal["stdio", "sse"] = "stdio",
    host: str = "127.0.0.1",
    port: int = 8002,
) -> None:
    """Main entry point for the MCP server."""

    db_url = db_url or os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    username = username or os.environ.get("NEO4J_USERNAME", "neo4j")
    password = password or os.environ.get("NEO4J_PASSWORD", "password")
    database = database or os.environ.get("NEO4J_DATABASE", "neo4j")
    embedding_model = os.environ.get("EMBEDDING_MODEL", embedding_model)
    extraction_model = os.environ.get("EXTRACTION_MODEL", extraction_model)

    logger.info(
        "Starting MCP Neo4j Lexical Graph v2 Server",
        db_url=db_url,
        database=database,
        embedding_model=embedding_model,
        extraction_model=extraction_model,
    )

    neo4j_driver = AsyncGraphDatabase.driver(db_url, auth=(username, password))

    try:
        async with neo4j_driver.session(database=database) as session:
            await session.run("RETURN 1")
        logger.info("Neo4j connection verified")
    except Exception as e:
        logger.error(f"Failed to connect to Neo4j: {e}")
        raise

    # Create shared components for background processing
    job_mgr = JobManager()
    auto_workers = _suggest_max_workers()
    process_pool = ProcessPoolExecutor(max_workers=auto_workers)

    logger.info("Process pool and job manager initialized", max_workers=auto_workers)

    mcp_server = create_mcp_server(
        neo4j_driver=neo4j_driver,
        database=database,
        embedding_model=embedding_model,
        extraction_model=extraction_model,
        job_manager=job_mgr,
        process_pool=process_pool,
    )

    if transport == "stdio":
        logger.info("Running with stdio transport")
        await mcp_server.run_stdio_async()
    else:
        logger.info(f"Running with SSE transport on {host}:{port}")
        await mcp_server.run_sse_async(host=host, port=port)


def run():
    """Synchronous entry point for CLI."""
    asyncio.run(main())


if __name__ == "__main__":
    run()
