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
import uuid
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
from .embedding_identity import (
    embedding_space, input_hash, cache_matches, validate_vectors, check_preserved_space,
    index_info as _embedding_index_info, check_index, ensure_publication_constraint,
    overlapping_indexes, check_overlaps,
)
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
    activate_document_version,
    ensure_constraints,
    write_document_atomically,
    get_existing_versions,
    write_parsed_document,
)
from .job_manager import JobManager, JobStatus
from .metadata import normalize_document_metadata
from .models import ParsedDocument
from .input_formats import DOCUMENT_FORMATS, SUPPORTED_SUFFIXES, mode_for_path, default_source_id
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
}

# Threshold (seconds) above which a warning is included in the response
_WARNING_THRESHOLD_SECONDS = 120


DEFAULT_EXTRACTION_MODEL = "gpt-6-luna"


async def _ensure_vector_index(
    driver: AsyncDriver,
    database: str,
    index_name: str,
    node_label: str,
    embedding_prop: str,
    dimensions: int,
    prefilter_properties: list[str],
) -> dict[str, str]:
    """Create a vector index and verify the actual index before reporting success."""
    index_options = (
        "OPTIONS {indexConfig: {`vector.dimensions`: $dims, "
        "`vector.similarity_function`: 'cosine'}}"
    )
    plain_query = (
        f"CYPHER 25 CREATE VECTOR INDEX `{index_name}` IF NOT EXISTS "
        f"FOR (c:`{node_label}`) ON c.`{embedding_prop}` {index_options}"
    )
    prefilter_query = plain_query.replace(
        index_options,
        "WITH [" + ", ".join(f"c.`{prop}`" for prop in prefilter_properties) + "] " + index_options,
    )

    async def create(query: str) -> None:
        async with driver.session(database=database) as session:
            result = await session.run(query, dims=dimensions)
            await result.consume()

    prefilter_error = None
    if prefilter_properties:
        try:
            await create(prefilter_query)
        except Exception as exc:
            prefilter_error = exc
            logger.warning("Prefiltered vector index unavailable; trying plain index", error=str(exc))
            try:
                await create(plain_query)
            except Exception as plain_exc:
                # Concurrent IF NOT EXISTS can still race on schema creation.
                # Only an equivalent-rule race may proceed to named-index
                # verification; missing/wrong definitions still fail below.
                if getattr(plain_exc, "code", None) != "Neo.ClientError.Schema.EquivalentSchemaRuleAlreadyExists":
                    raise RuntimeError(
                        f"Vector index '{index_name}' failed with prefilters ({prefilter_error}) "
                        f"and without them ({plain_exc})"
                    ) from plain_exc
    else:
        await create(plain_query)

    async with driver.session(database=database) as session:
        result = await session.run(
            "SHOW VECTOR INDEXES YIELD name, state, createStatement "
            "WHERE name = $name RETURN name, state, createStatement",
            name=index_name,
        )
        record = await result.single()
    if record is None:
        raise RuntimeError(f"Vector index '{index_name}' was not created")
    state = record["state"]
    if state not in {"ONLINE", "POPULATING"}:
        raise RuntimeError(f"Vector index '{index_name}' is {state}")
    statement = record["createStatement"] or ""
    mode = "prefiltered" if " WITH [" in statement.upper() else "plain"
    return {"name": index_name, "state": state, "mode": mode}



async def _ensure_fulltext_index(driver, database, index_name, node_label, properties):
    """Consume DDL and verify its named definition; IF NOT EXISTS is not validation."""
    for identifier in [index_name, node_label, *properties]:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", identifier):
            raise ValueError(f"Unsafe fulltext identifier: {identifier!r}")
    props = ", ".join(f"n.`{p}`" for p in properties)
    async with driver.session(database=database) as session:
        result = await session.run(
            f"CREATE FULLTEXT INDEX `{index_name}` IF NOT EXISTS "
            f"FOR (n:`{node_label}`) ON EACH [{props}]"
        )
        await result.consume()
        result = await session.run(
            "SHOW FULLTEXT INDEXES YIELD name, state, labelsOrTypes, properties, entityType, failureMessage "
            "WHERE name = $name RETURN *", name=index_name,
        )
        record = await result.single()
    if record is None:
        raise RuntimeError(f"Fulltext index '{index_name}' was not created")
    if (record["entityType"] != "NODE" or record["labelsOrTypes"] != [node_label]
            or set(record["properties"]) != set(properties)):
        raise RuntimeError(f"Fulltext index '{index_name}' has an incompatible definition; use a distinct name or explicitly rebuild it")
    if record["state"] not in {"ONLINE", "POPULATING"}:
        raise RuntimeError(f"Fulltext index '{index_name}' is {record['state']}: {record.get('failureMessage', '')}")
    return {"name": index_name, "state": record["state"]}


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
    # Use the "spawn" start method explicitly. On Linux the multiprocessing
    # default is "fork", which forks the live, multithreaded async server and
    # can deadlock (fork-after-threads). "spawn" is the default on macOS and is
    # safe here: only picklable primitives cross the process boundary (the
    # progress Queue is passed as None) and the worker entrypoint is top-level.
    _process_pool = process_pool or ProcessPoolExecutor(
        max_workers=_auto_workers,
        mp_context=multiprocessing.get_context("spawn"),
    )

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
        path: str = Field(..., description="Path to a PDF, Markdown, TXT, local HTML/XHTML or DOCX file, or a mixed folder"),
        output_dir: str = Field(..., description="Directory for logs and manifests"),
        document_id: Optional[str] = Field(
            None, description="Custom sourceId (defaults to filename). Ignored for folders."
        ),
        parse_mode: str = Field(
            "pymupdf", description="PDF parse mode: pymupdf, docling, page_image. Markdown/TXT/HTML/DOCX automatically use 'document'; explicit 'document' supports non-PDF files only."
        ),
        store_page_images: bool = Field(
            False, description="Render and store page images on Page nodes"
        ),
        dpi: int = Field(150, description="DPI for page image rendering"),
        metadata_json: Optional[str] = Field(
            None, description="JSON string of extra Document properties"
        ),
        skip_furniture: bool = Field(
            True, description="Skip headers/footers (docling/document modes)"
        ),
        extract_sections: bool = Field(
            True, description="Extract section hierarchy (docling/document modes)"
        ),
        chunk_size: int = Field(500, description="Target tokens per chunk (pymupdf mode)"),
        chunk_overlap: int = Field(50, description="Token overlap between chunks (pymupdf mode)"),
        extract_images: bool = Field(
            True, description="Extract images as Element nodes with imageBase64 (pymupdf mode)"
        ),
        extract_tables: bool = Field(
            True, description="Extract tables as Element nodes with imageBase64 + text (pymupdf mode)"
        ),
        max_parallel: int = Field(
            0,
            description=(
                "Max documents to parse concurrently (all retained modes). "
                "0 = auto-detect based on available RAM and CPU cores. "
            ),
        ),
    ) -> str:
        """Parse PDF, Markdown, TXT, local HTML/XHTML or DOCX into a lexical graph.

        Non-PDF formats automatically use native document parsing, without PDF
        rendering or invented pages. Call chunk_lexical_graph afterward; structured
        chunking preserves heading paths. TXT is literal text, without inferred headings.
        Local HTML is static content; scripts are not executed and remote assets
        are not fetched. Source anchors replace page citations for pageless inputs.

        Supports document versioning -- if a document with the same sourceId
        already exists, a new version is created and the old one is deactivated.

        **Parse modes:**
        - pymupdf: PyMuPDF extraction with image/table detection. Creates Document + Chunk + Element nodes.
          Set extract_images=False and extract_tables=False for text-only (Document + Chunk only).
        - docling: Full layout analysis with sections, tables, captions. (requires docling extra)
        - page_image: Page images + text. Creates Document + Page nodes for VLM use.

        **Returns immediately** with a job_id. Use check_processing_status(job_id) to monitor.
        """
        p = Path(path)
        if not p.exists():
            raise ToolError(f"Path not found: {path}")

        os.makedirs(output_dir, exist_ok=True)
        try:
            user_metadata = normalize_document_metadata(json.loads(metadata_json) if metadata_json else {})
        except (ValueError, TypeError) as exc:
            raise ToolError(str(exc)) from exc

        # -- Pre-flight: count files and pages --
        from .worker import count_pdf_pages

        is_folder = p.is_dir()
        if is_folder:
            input_files = sorted(
                (file for file in p.iterdir() if file.is_file() and file.suffix.lower() in SUPPORTED_SUFFIXES),
                key=lambda file: file.name,
            )
            if not input_files:
                raise ToolError(f"No supported documents found in {path}; supported: {', '.join(sorted(SUPPORTED_SUFFIXES))}")
        else:
            if not p.is_file():
                raise ToolError(f"Path is neither a file nor a directory: {path}")
            input_files = [p]

        file_page_counts: list[tuple[str, int]] = []
        file_modes = set()
        source_formats = set()
        resolved_sources: dict[str, Path] = {}
        for source in input_files:
            try:
                file_mode = mode_for_path(source, parse_mode)
            except ValueError as exc:
                raise ToolError(str(exc)) from exc
            source_key = document_id if not is_folder and document_id else default_source_id(source)
            if source_key in resolved_sources:
                raise ToolError(
                    f"Source ID collision between {resolved_sources[source_key].name!r} and {source.name!r}. "
                    "Rename one file or import them separately with distinct document_id values."
                )
            resolved_sources[source_key] = source
            file_modes.add(file_mode)
            source_formats.add("pdf" if source.suffix.lower() == ".pdf" else DOCUMENT_FORMATS[source.suffix.lower()])
            page_count = 0
            if source.suffix.lower() == ".pdf":
                try:
                    page_count = count_pdf_pages(str(source))
                except Exception:
                    pass  # The parser records a useful failure for invalid PDFs.
            file_page_counts.append((str(source), page_count))
        files_total = len(input_files)
        total_pages = sum(count for _, count in file_page_counts)
        pageless_files = sum(source.suffix.lower() != ".pdf" for source in input_files)
        job_mode = next(iter(file_modes)) if len(file_modes) == 1 else "mixed"

        # Resolve effective parallelism for this job
        effective_parallel = max_parallel if max_parallel > 0 else _suggest_max_workers()

        # Estimate processing time (adjusted for parallelism)
        rate = _TIME_PER_PAGE.get(parse_mode, 10.0)
        estimated_seconds = (total_pages * rate) / effective_parallel
        estimated_minutes = None if pageless_files else round(estimated_seconds / 60, 1)

        # Create the job
        job = _job_manager.create_job(
            path=str(p),
            parse_mode=job_mode,
            is_folder=is_folder,
            files_total=files_total,
            source_pages_expected=total_pages,
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
            "store_page_images": store_page_images,
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
            "sourcePageCount": total_pages,
            "pageless_files": pageless_files,
            "source_formats": sorted(source_formats),
            "parse_mode": job_mode,
            "estimated_minutes": estimated_minutes,
            "max_parallel": effective_parallel,
            "message": (
                f"Job queued. Use check_processing_status('{job.id}') to monitor."
            ),
        }
        if not pageless_files and estimated_seconds > _WARNING_THRESHOLD_SECONDS:
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
        files completed/remaining, source pages processed, and elements extracted.
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
            description=(
                "Document version id to chunk. If None, chunks all active eligible "
                "documents without chunks, or rebuilds all of them when "
                "clear_existing_chunks is True."
            ),
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
                    and (
                        clear_existing_chunks
                        or d.get("totalChunkCount", 0) == 0
                    )
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
                                "sourceFormat": v.get("sourceFormat"),
                                "sourcePageCount": v.get("sourcePageCount"),
                                "pageNodeCount": v.get("pageNodeCount"),
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
                "sourceFormat": doc.get("sourceFormat"),
                "sourcePageCount": doc.get("totalPages", len(pages)),
                "pageNodeCount": len(pages),
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

            if parse_mode not in ("pymupdf", "text_only", "document"):
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

            elif parse_mode == "document":
                # Preserve logical source order without fabricating a physical page.
                if doc.get("sourceFormat") == "text":
                    body = "".join(e.get("text") or "" for e in elements)
                    fence = "`" * max(3, 1 + max((len(run) for run in re.findall(r"`+", body)), default=0))
                    md_lines.append(f"{fence}text\n{body}\n{fence}\n")
                else:
                    for element in elements:
                        text = element.get("text") or ""
                        kind = element.get("type")
                        if kind == "heading":
                            md_lines.append(f"{'#' * (element.get('level') or 1)} {text}\n")
                        elif kind == "list_item":
                            md_lines.append(f"- {text}\n")
                        else:
                            md_lines.append(text + "\n")
                        if element.get("imageBase64"):
                            mime = element.get("imageMimeType") or "image/png"
                            md_lines.append(f"![{element['id']}](data:{mime};base64,{element['imageBase64']})\n")
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
                "Default: ['documentName', 'type']. Additional prefilter properties require Neo4j 2026.01+. "
                "Older servers fall back to a plain vector index. Set to null or [] to request a plain index."
            ),
        ),
        document_id: Optional[str] = Field(
            None,
            description=(
                "Filter to a specific document: only embeds nodes where documentName = document_id. "
                "None = all active inputs, regenerating stale or unverifiable embeddings."
            ),
        ),
        overwrite: bool = Field(
            False,
            description="Force re-embedding. Otherwise reuse only embeddings with matching input, model, provider and dimension identity.",
        ),
        parallel: int = Field(10, description="Max concurrent embedding batches"),
        model: str = Field(
            default=embedding_model, description="Embedding model (via LiteLLM)"
        ),
        dimensions: Optional[int] = Field(
            None, description="Optional dimensions sent to the embedding provider. Must match an existing named index.",
        ),
        include_inactive: bool = Field(
            False, description="Include inactive Chunk nodes in a label-wide refresh, needed when migrating all vectors in an index.",
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
          Additional prefilter properties require Neo4j 2026.01+. Older servers
          fall back to a plain vector index, and the result reports the actual mode.

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
            if parallel < 1:
                raise ValueError("parallel must be positive")
            for name in [node_label, text_property, *(context_properties or []), *(index_prefilter_properties or []), *([text_property_fallback] if text_property_fallback else [])]:
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                    raise ValueError(f"Unsafe embedding identifier: {name!r}")
            fulltext_index = None
            if create_fulltext_index:
                ft_props = list(dict.fromkeys([text_property, *([text_property_fallback] if text_property_fallback else [])]))
                fulltext_index = await _ensure_fulltext_index(
                    neo4j_driver, database, f"{node_label.lower()}_text_fulltext", node_label, ft_props,
                )
            space = embedding_space(model, dimensions)
            embedding_prop = "text_embedding"
            index_name = f"{node_label.lower()}_{embedding_prop}"
            text_expr = (f"coalesce(c.`{text_property}`, c.`{text_property_fallback}`)"
                         if text_property_fallback else f"c.`{text_property}`")
            text_not_null = (f"(c.`{text_property}` IS NOT NULL OR c.`{text_property_fallback}` IS NOT NULL)"
                             if text_property_fallback else f"c.`{text_property}` IS NOT NULL")
            context_parts = " + ' ' + ".join(f"coalesce(c.`{p}`, '')" for p in context_properties)
            composed_text = f"trim({context_parts} + ' ' + {text_expr})" if context_parts else text_expr
            where_clauses = [text_not_null]
            params = {}
            if document_id:
                where_clauses.append("c.documentName = $document_id")
                params["document_id"] = document_id
            elif node_label == "Chunk" and not include_inactive:
                where_clauses.append("coalesce(c.active, true) = true")
            where_str = " AND ".join(where_clauses)
            scope_where = " AND ".join(where_clauses[1:]) or "true"
            vector_fields = (
                "elementId(c) AS eid, size(c.text_embedding) AS vector_dims, "
                "c.embeddingSpace AS space, c.embeddingModel AS cached_model, "
                "c.embeddingProvider AS provider, c.embeddingDimensions AS dims, "
                "c.embeddingInputHash AS input_hash, labels(c) AS labels"
            )
            query = (f"CYPHER 25 MATCH (c:`{node_label}`) WHERE {where_str} RETURN "
                     + vector_fields + f", {composed_text} AS text")
            global_query = (f"CYPHER 25 MATCH (c:`{node_label}`) WHERE c.text_embedding IS NOT NULL RETURN "
                            + vector_fields)
            async with neo4j_driver.session(database=database) as session:
                records = await (await session.run(query, **params)).data()
                indexed = await (await session.run(global_query)).data()
                existing_index = await _embedding_index_info(session, index_name)
                missing_inputs = await (await session.run(
                    f"MATCH (c:`{node_label}`) WHERE {scope_where} AND c.text_embedding IS NOT NULL "
                    f"AND NOT ({text_not_null}) RETURN count(c) AS missing_inputs", **params,
                )).single()
            if missing_inputs is None or missing_inputs["missing_inputs"]:
                raise RuntimeError(
                    "Indexed nodes in the requested scope have no usable embedding input. "
                    "Restore input or explicitly remove obsolete embeddings; no provider request was made."
                )
            check_index(existing_index, node_label, dimensions)
            if not records:
                return json.dumps({
                    "status": "no_work", "embedded": 0, "vector_index": None,
                    "fulltext_index": fulltext_index,
                    "message": "No eligible source inputs in this scope; no cache identity was assumed.",
                })
            if any(not isinstance(r["text"], str) for r in records):
                raise RuntimeError("Every embedding input must compose to a string")
            pending = [r for r in records if overwrite or not cache_matches(r, space)]
            pending_ids = {r["eid"] for r in pending}
            preserved_dims = check_preserved_space(indexed, pending_ids, space, dimensions)
            if not pending:
                if len(preserved_dims) != 1:
                    raise RuntimeError("Cached vectors have no single verified dimension")
                dims = next(iter(preserved_dims))
                check_index(existing_index, node_label, dims)
                vector_index = await _ensure_vector_index(
                    neo4j_driver, database, index_name, node_label, embedding_prop,
                    dims, index_prefilter_properties or [],
                )
                async with neo4j_driver.session(database=database) as session:
                    check_index(await _embedding_index_info(session, index_name), node_label, dims)
                return json.dumps({
                    "status": "success", "embedded": 0, "skipped": len(records),
                    "model": model, "provider": space.provider, "dimensions": dims,
                    "vector_index": index_name, "vector_index_mode": vector_index["mode"],
                    "vector_index_state": vector_index["state"],
                    "fulltext_index": fulltext_index,
                    "message": "All selected embeddings match exact input/model/provider/dimension identity; vector index verified.",
                })
            # Privilege/constraint failures happen before a billable provider call.
            async with neo4j_driver.session(database=database) as session:
                overlaps = await overlapping_indexes(session, index_name, pending)
                check_overlaps(overlaps, pending, space, dimensions)
                await ensure_publication_constraint(session)
            embedder = ChunkEmbedder(model=model, dimensions=dimensions)
            embedded = await embedder.embed_many([(r["eid"], r["text"]) for r in pending], parallel=parallel)
            dims = validate_vectors(pending, embedded, dimensions)
            check_preserved_space(indexed, pending_ids, space, dims)
            check_index(existing_index, node_label, dims)
            check_overlaps(overlaps, pending, space, dims)
            # Establish/verify the immutable index dimensions before data writes.
            # No index is dropped. An empty index may remain after a later failure.
            vector_index = await _ensure_vector_index(
                neo4j_driver, database, index_name, node_label, embedding_prop,
                dims, index_prefilter_properties or [],
            )
            async with neo4j_driver.session(database=database) as session:
                check_index(await _embedding_index_info(session, index_name), node_label, dims)
            by_id = {r["eid"]: r for r in pending}
            batch = [{"eid": eid, "text": by_id[eid]["text"], "hash": input_hash(by_id[eid]["text"]),
                      "embedding": vector} for eid, vector in embedded]

            publication_token = uuid.uuid4().hex
            async def publish(tx):
                lock = await (await tx.run(
                    "MERGE (lock:EmbeddingPublicationLock {indexName:$name}) "
                    "ON CREATE SET lock.token=$token "
                    "SET lock.generation=coalesce(lock.generation, 0)+1 RETURN lock.token AS token",
                    name=index_name, token=publication_token,
                )).single()
                if lock is None or lock["token"] != publication_token:
                    raise RuntimeError("Reserved embedding publication lock already contains committed data; inspect it before retrying")
                current = await (await tx.run(
                    f"CYPHER 25 MATCH (c:`{node_label}`) WHERE elementId(c) IN $ids AND {where_str} "
                    "WITH c ORDER BY elementId(c) "
                    "SET c.text_embedding=c.text_embedding "
                    f"RETURN {vector_fields}, {composed_text} AS text",
                    ids=list(pending_ids), **params,
                )).data()
                if sorted((r["eid"], r["text"]) for r in current) != sorted((r["eid"], r["text"]) for r in pending):
                    raise RuntimeError("Embedding source input changed during provider work; no vectors were written")
                check_overlaps(await overlapping_indexes(tx, index_name, current), current, space, dims)
                current_vectors = await (await tx.run(global_query)).data()
                check_preserved_space(current_vectors, pending_ids, space, dims)
                result = await tx.run(f"""
                    CYPHER 25 UNWIND $embeddings AS item
                    MATCH (c:`{node_label}`) WHERE elementId(c)=item.eid
                    SET c.text_embedding=vector(item.embedding, $dims, FLOAT32),
                        c.embeddingModel=$model, c.embeddingProvider=$provider,
                        c.embeddingDimensions=$dims, c.embeddingInputHash=item.hash,
                        c.embeddingSpace=$space
                    RETURN count(c) AS updated
                """, embeddings=batch, dims=dims, model=model, provider=space.provider, space=space.fingerprint)
                record = await result.single()
                if record is None or record["updated"] != len(batch):
                    raise RuntimeError("Embedding publication did not update every selected node")
                await (await tx.run(
                    "MATCH (lock:EmbeddingPublicationLock {indexName:$name}) DELETE lock", name=index_name,
                )).consume()
                return record["updated"]

            async with neo4j_driver.session(database=database) as session:
                total_updated = await session.execute_write(publish)

            prefilter_props = index_prefilter_properties or []
            prefilter_msg = f" ({vector_index['mode']}, {vector_index['state']})" if vector_index else " (no embeddings)"
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
                    "provider": space.provider,
                    "skipped": len(records) - len(pending),
                    "include_inactive": include_inactive,
                    "embedded": total_updated,
                    "dimensions": dims,
                    "vector_index": index_name,
                    "vector_index_mode": vector_index["mode"] if vector_index else None,
                    "vector_index_state": vector_index["state"] if vector_index else None,
                    "fulltext_index": fulltext_index,
                    "message": (
                        f"Embedded {total_updated} {node_label} nodes (VECTOR FLOAT32, {dims}d). "
                        f"Vector index '{index_name}'{prefilter_msg} "
                        f"{'verified' if vector_index else 'not created because no embeddings were written'}.{auto_msg}"
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

            cnt = await activate_document_version(
                neo4j_driver, database, document_id, chunk_set_version
            )
            msg = f"Activated document version {document_id}."
            if chunk_set_version is not None:
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
    import copy

    result = copy.deepcopy(worker_result)
    old_prefix = f"{source_id}_v{old_version}"
    new_prefix = f"{source_id}_v{new_version}"

    def identifier(value):
        if isinstance(value, str) and (value == old_prefix or value.startswith(old_prefix + "_")):
            return new_prefix + value[len(old_prefix):]
        return value

    if result.get("parse_mode") == "pymupdf":
        result["doc_id"] = identifier(result.get("doc_id"))
        result["version"] = new_version
        props = result.get("doc_props", {})
        props["id"] = identifier(props.get("id"))
        props["version"] = new_version
        asset_ids = {}
        for record in result.get("element_records", []):
            original = record.get("id")
            record["id"] = identifier(original)
            asset_ids[original] = record["id"]
        for chunk in result.get("chunks", []):
            chunk["id"] = identifier(chunk.get("id"))
            if "hasElementIds" in chunk:
                chunk["hasElementIds"] = [identifier(eid) for eid in chunk["hasElementIds"]]
            # Rewrite only generated visual references, not arbitrary source text.
            chunk["text"] = re.sub(
                r"\[(IMAGE|TABLE):\s*([^\]]+)\]",
                lambda match: f"[{match[1]}: {asset_ids[match[2]]}]" if match[2] in asset_ids else match[0],
                chunk.get("text") or "",
            )
        return result

    document = result["parsed_doc"]
    document["id"] = identifier(document["id"])
    document["version"] = new_version
    for page in document.get("pages", []):
        page["element_ids"] = [identifier(eid) for eid in page.get("element_ids", [])]
    for element in document.get("elements", []):
        element["id"] = identifier(element["id"])
        if element.get("caption_target_id"):
            element["caption_target_id"] = identifier(element["caption_target_id"])
    for section in document.get("sections", []):
        section["id"] = identifier(section["id"])
        for key in ("element_ids", "subsection_ids"):
            section[key] = [identifier(value) for value in section.get(key, [])]
    return result


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
    extraction_model: str = "gpt-6-luna",
    max_parallel: int = 1,
) -> None:
    """Background task that orchestrates parallel-parse, sequential-write processing.

    Files are parsed in batches of max_parallel concurrently (using the process pool),
    then each result is published in its own atomic Neo4j data transaction.

    For each file:
      1. Submit parsing to subprocess (tentative version=1)
      2. After all batch parses complete, write each result sequentially
      3. Select a version immediately before writing; uniqueness guards collisions
      4. Remap IDs if version changed, write to Neo4j with retry
      5. Update job progress
    """
    from .worker import parse_single_pdf  # noqa: F401 — ensures pickle works in pool

    loop = asyncio.get_running_loop()
    progress_queue: multiprocessing.Queue = multiprocessing.Queue()
    worker_kwargs = dict(parse_kwargs)

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
                file_mode = mode_for_path(pdf_path, parse_mode)
                source_id = document_id if (not is_folder and document_id) else default_source_id(pdf_path)
                batch_infos.append((pdf_path, page_count, source_id))

                current_file_label = (
                    pdf_name if batch_size == 1
                    else f"{batch_size} files in parallel"
                )
                job_manager.update_progress(
                    job_id,
                    current_file=current_file_label,
                    current_file_source_page_count=page_count,
                    current_stage="parsing",
                )

                logger.info(
                    "Submitting for parsing",
                    job_id=job_id,
                    file=pdf_name,
                    mode=file_mode,
                    batch_size=batch_size,
                )

                parse_futures.append(
                    loop.run_in_executor(
                        process_pool,
                        _make_worker_call(
                            pdf_path=pdf_path,
                            source_id=source_id,
                            version=1,  # tentative; remapped at write time
                            parse_mode=file_mode,
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
                    # Select the next version; the unique Document id guards concurrent writers.
                    existing = await get_existing_versions(neo4j_driver, database, source_id)
                    real_version = 1
                    if existing:
                        # An automatically generated ID must not silently treat a different
                        # file-format family as a replacement. Explicit IDs opt into that.
                        if not (not is_folder and document_id):
                            incoming_document = worker_result.get("parse_mode") == "document"
                            if any((item.get("parseMode") == "document") != incoming_document for item in existing):
                                raise ValueError(
                                    f"Default source ID {source_id!r} already belongs to another input format. "
                                    "Use an explicit document_id or rename the input; prior versions were preserved."
                                )
                        real_version = max(v["version"] for v in existing) + 1

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
                        source_pages_processed=(
                            job_manager.get_job(job_id).source_pages_processed + page_count
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
                "total_files": job.files_total,
                "total_pdfs": sum(Path(file).suffix.lower() == ".pdf" for file, _ in file_page_counts),
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
        await ensure_constraints(
            driver, database, parse_mode="pymupdf",
            extract_images=bool(worker_result["fig_counter"]),
            extract_tables=bool(worker_result["tbl_counter"]),
        )
        return await write_document_atomically(
            driver, database, source_id, worker_result["doc_id"],
            lambda transaction_driver: _write_pymupdf_result(
                transaction_driver, database, worker_result
            ),
        )
    else:
        # docling, page_image, or document -- reconstruct ParsedDocument from dict
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
        "sourcePageCount": result["total_pages"],
        "pageNodeCount": 0,
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
                "sourceFormat": c.source_format,
                "sourceAnchors": c.source_anchors,
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
                    c.sourceFormat = rec.sourceFormat,
                    c.sourceAnchors = rec.sourceAnchors,
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
                SET c.documentName = coalesce(d.name, rec.documentName, d.id),
                    c.sourceFormat = coalesce(d.sourceFormat, rec.sourceFormat)
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
    # "spawn" avoids the fork-after-threads deadlock on Linux (default "fork");
    # it is the macOS default. See create_mcp_server for the full rationale.
    process_pool = ProcessPoolExecutor(
        max_workers=auto_workers,
        mp_context=multiprocessing.get_context("spawn"),
    )

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
