"""MCP server for entity extraction from graph nodes.

Tools:
- convert_schema: Convert data modeling output to extraction schema + Pydantic models
- extract_entities: Async entity extraction with auto text/VLM routing
- check_extraction_status: Monitor background extraction jobs
- cancel_extraction: Cancel a running extraction job
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import pathlib
import sys
import time
from typing import Any, Literal, Optional, Type

import structlog
from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from neo4j import AsyncGraphDatabase, AsyncDriver
from pydantic import BaseModel, Field

load_dotenv()

from .base_extractor import (
    DEFAULT_EXTRACTION_MODEL,
    load_extraction_output_model,
    schema_from_pydantic_module,
)
from .job_manager import ExtractionJobInfo, JobManager, JobStatus
from .models import (
    ChunkExtractionResult,
    ChunkType,
    ClassifiedChunk,
    ExtractionMetadata,
    ExtractionSchema,
    PassType,
)
from .schema_generator import generate_extraction_models_code
from .text_extractor import TextExtractor
from .vlm_extractor import VlmExtractor

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


def create_mcp_server(
    neo4j_driver: AsyncDriver,
    database: str = "neo4j",
    extraction_model: str = DEFAULT_EXTRACTION_MODEL,
) -> FastMCP:
    """Create the entity graph MCP server with all tools."""

    mcp = FastMCP("mcp-neo4j-entity-graph")
    job_manager = JobManager()

    # ========================================
    # Neo4j read: classify chunks
    # ========================================

    async def query_and_classify_chunks(
        source_label: str,
        force: bool,
    ) -> list[ClassifiedChunk]:
        """Query Neo4j for source nodes and classify them as text or VLM."""

        # Query fetches all relevant properties for classification
        force_filter = ""
        if not force:
            force_filter = "AND NOT (n)<-[:EXTRACTED_FROM]-()"

        query = f"""
            MATCH (n:{source_label})
            WHERE n.text IS NOT NULL OR n.imageBase64 IS NOT NULL
            {force_filter}
            RETURN
                n.id AS id,
                n.text AS text,
                coalesce(n.type, 'text') AS type,
                n:Page AS isPage,
                n.documentName AS documentName,
                n.sectionContext AS sectionContext,
                n.imageBase64 AS imageBase64,
                n.imageMimeType AS imageMimeType,
                n.textAsHtml AS textAsHtml
        """

        async with neo4j_driver.session(database=database) as session:
            result = await session.run(query)
            records = await result.data()

        chunks: list[ClassifiedChunk] = []
        for r in records:
            chunk_type_str = r.get("type", "text")
            has_image = r.get("imageBase64") is not None
            is_page = r.get("isPage", False)

            if is_page and has_image:
                ct = ChunkType.PAGE
            elif chunk_type_str == "image" and has_image:
                ct = ChunkType.IMAGE
            elif chunk_type_str == "table" and has_image:
                ct = ChunkType.TABLE
            elif has_image and chunk_type_str not in ("text",):
                ct = ChunkType.IMAGE
            else:
                ct = ChunkType.TEXT

            chunks.append(
                ClassifiedChunk(
                    id=r["id"],
                    chunk_type=ct,
                    text=r.get("text"),
                    document_name=r.get("documentName"),
                    section_context=r.get("sectionContext"),
                    image_base64=r.get("imageBase64"),
                    image_mime_type=r.get("imageMimeType"),
                    text_as_html=r.get("textAsHtml"),
                )
            )

        return chunks

    # ========================================
    # Neo4j write: batch results
    # ========================================

    async def write_batch_to_neo4j(
        results: list[ChunkExtractionResult],
        schema: ExtractionSchema,
        source_label: str,
        metadata: ExtractionMetadata,
    ) -> dict[str, int]:
        """Write extraction results to Neo4j with EXTRACTED_FROM provenance."""
        stats = {
            "entities_created": 0,
            "relationships_created": 0,
            "extracted_from_created": 0,
        }

        entities_by_label: dict[str, list[dict[str, Any]]] = {}
        for chunk_result in results:
            for entity in chunk_result.entities:
                if entity.label not in entities_by_label:
                    entities_by_label[entity.label] = []

                entity_schema = schema.get_entity_schema(entity.label)
                if entity_schema:
                    key_value = entity.properties.get(entity_schema.key_property)
                    if key_value:
                        entities_by_label[entity.label].append(
                            {
                                "key_value": key_value,
                                "properties": entity.properties,
                                "chunk_id": chunk_result.chunk_id,
                            }
                        )

        rels_by_type: dict[str, list[dict[str, Any]]] = {}
        for chunk_result in results:
            for rel in chunk_result.relationships:
                key = f"{rel.type}_{rel.source_label}_{rel.target_label}"
                if key not in rels_by_type:
                    rels_by_type[key] = []

                source_schema = schema.get_entity_schema(rel.source_label)
                target_schema = schema.get_entity_schema(rel.target_label)

                if source_schema and target_schema:
                    rels_by_type[key].append(
                        {
                            "type": rel.type,
                            "source_label": rel.source_label,
                            "target_label": rel.target_label,
                            "source_key_property": source_schema.key_property,
                            "target_key_property": target_schema.key_property,
                            "source_key_value": rel.source_key,
                            "target_key_value": rel.target_key,
                            "properties": rel.properties,
                        }
                    )

        meta_props = {
            "model": metadata.model,
            "extractedAt": metadata.timestamp,
            "passNumber": metadata.pass_number,
            "passType": metadata.pass_type.value,
        }

        async with neo4j_driver.session(database=database) as session:
            for label, entities in entities_by_label.items():
                if not entities:
                    continue
                entity_schema = schema.get_entity_schema(label)
                if not entity_schema:
                    continue

                query = f"""
                    UNWIND $entities AS entity
                    MERGE (e:{label} {{{entity_schema.key_property}: entity.key_value}})
                    SET e += entity.properties
                    WITH e, entity
                    MATCH (c:{source_label} {{id: entity.chunk_id}})
                    MERGE (e)-[r:EXTRACTED_FROM]->(c)
                    SET r += $meta
                    RETURN count(DISTINCT e) as entities_created, count(*) as rels_created
                """

                result = await session.run(query, entities=entities, meta=meta_props)
                record = await result.single()
                if record:
                    stats["entities_created"] += record["entities_created"]
                    stats["extracted_from_created"] += record["rels_created"]

            for key, rels in rels_by_type.items():
                if not rels:
                    continue
                first = rels[0]
                query = f"""
                    UNWIND $relationships AS rel
                    MATCH (source:{first['source_label']} {{{first['source_key_property']}: rel.source_key_value}})
                    MATCH (target:{first['target_label']} {{{first['target_key_property']}: rel.target_key_value}})
                    MERGE (source)-[r:{first['type']}]->(target)
                    SET r += rel.properties
                    RETURN count(r) as created
                """
                result = await session.run(query, relationships=rels)
                record = await result.single()
                stats["relationships_created"] += record["created"] if record else 0

        return stats

    # ========================================
    # Background extraction job
    # ========================================

    async def _run_extraction_job(
        job: ExtractionJobInfo,
        chunks: list[ClassifiedChunk],
        schema: ExtractionSchema,
        source_label: str,
        output_model: Type[BaseModel],
        text_parallel: int,
        vlm_parallel: int,
        batch_size: int,
    ) -> None:
        """Background task that performs the actual extraction."""
        try:
            job_manager.update_status(job.id, JobStatus.EXTRACTING)

            text_chunks = [c for c in chunks if not c.needs_vlm]
            vlm_chunks = [c for c in chunks if c.needs_vlm]

            text_extractor = TextExtractor(model=job.model)
            vlm_extractor = VlmExtractor(model=job.model)

            metadata = ExtractionMetadata(
                model=job.model,
                pass_number=job.pass_number,
                pass_type=job.pass_type,
            )

            all_results: list[ChunkExtractionResult] = []
            buffer: list[ChunkExtractionResult] = []

            async def flush():
                nonlocal buffer
                if not buffer:
                    return
                to_write = buffer.copy()
                buffer = []
                job_manager.update_status(job.id, JobStatus.WRITING)
                write_stats = await write_batch_to_neo4j(
                    to_write, schema, source_label, metadata
                )
                job_manager.update_progress(
                    job.id,
                    batches_written=job.batches_written + 1,
                    entities_created=job.entities_created
                    + write_stats["entities_created"],
                    relationships_created=job.relationships_created
                    + write_stats["relationships_created"],
                    extracted_from_created=job.extracted_from_created
                    + write_stats["extracted_from_created"],
                )
                job_manager.update_status(job.id, JobStatus.EXTRACTING)

            # Run text and VLM extraction concurrently
            text_semaphore = asyncio.Semaphore(text_parallel)
            vlm_semaphore = asyncio.Semaphore(vlm_parallel)

            async def extract_text_chunk(chunk: ClassifiedChunk) -> ChunkExtractionResult:
                async with text_semaphore:
                    return await text_extractor.extract_chunk(chunk, schema, output_model)

            async def extract_vlm_chunk(chunk: ClassifiedChunk) -> ChunkExtractionResult:
                async with vlm_semaphore:
                    return await vlm_extractor.extract_chunk(chunk, schema, output_model)

            # Create all tasks
            tasks: list[asyncio.Task] = []
            for c in text_chunks:
                tasks.append(asyncio.create_task(extract_text_chunk(c)))
            for c in vlm_chunks:
                tasks.append(asyncio.create_task(extract_vlm_chunk(c)))

            for coro in asyncio.as_completed(tasks):
                result = await coro
                all_results.append(result)
                buffer.append(result)

                job_manager.update_progress(
                    job.id,
                    chunks_completed=job.chunks_completed + 1,
                    entities_extracted=job.entities_extracted + len(result.entities),
                    relationships_extracted=job.relationships_extracted
                    + len(result.relationships),
                )

                logger.info(
                    f"[{job.chunks_completed}/{job.total_chunks}] Chunk extracted",
                    chunk_id=result.chunk_id,
                    entities=len(result.entities),
                    rels=len(result.relationships),
                )

                if len(buffer) >= batch_size:
                    await flush()

            # Final flush
            await flush()

            job_manager.update_status(job.id, JobStatus.COMPLETE)
            logger.info(
                "Extraction job complete",
                job_id=job.id,
                entities_created=job.entities_created,
                relationships_created=job.relationships_created,
                elapsed=job.elapsed_seconds,
            )

        except asyncio.CancelledError:
            job_manager.update_status(job.id, JobStatus.CANCELLED)
            logger.info("Extraction job cancelled", job_id=job.id)
        except Exception as e:
            job_manager.update_status(
                job.id, JobStatus.FAILED, error=str(e)
            )
            logger.error(
                "Extraction job failed",
                job_id=job.id,
                error=str(e),
                error_type=type(e).__name__,
            )

    # ========================================
    # TOOL 1: Convert Schema
    # ========================================

    @mcp.tool(
        name="convert_schema",
        annotations=ToolAnnotations(
            title="Convert Data Model to Extraction Schema",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def convert_schema(
        modeling_output: str = Field(
            ...,
            description="JSON output from the Data Modeling MCP server (nodes + relationships)",
        ),
        output_path: str = Field(
            ...,
            description="Path to save the Pydantic .py file (e.g. /path/to/schema.py).",
        ),
    ) -> str:
        """
        Convert a data model from the Data Modeling MCP to extraction-ready Pydantic models.

        Generates one file: `{output_path}` — strongly-typed Pydantic models for LLM structured extraction.
        The .py file can be customized with Literal constraints and field_validators before extraction.
        """
        try:
            modeling_data = json.loads(modeling_output)

            # Convert nodes to entity types
            entity_types = []
            for node in modeling_data.get("nodes", []):
                key_prop_data = node.get("key_property", {})
                entity_type = {
                    "label": node.get("label"),
                    "description": node.get("description", f"A {node.get('label')} entity"),
                    "key_property": key_prop_data.get("name"),
                    "properties": [
                        {
                            "name": key_prop_data.get("name"),
                            "type": key_prop_data.get("type", "STRING"),
                            "description": key_prop_data.get("description"),
                        }
                    ]
                    + [
                        {
                            "name": prop.get("name"),
                            "type": prop.get("type", "STRING"),
                            "description": prop.get("description"),
                        }
                        for prop in node.get("properties", [])
                    ],
                }
                entity_types.append(entity_type)

            relationship_types = []
            for rel in modeling_data.get("relationships", []):
                rel_type = {
                    "type": rel.get("type"),
                    "description": rel.get(
                        "description",
                        f"{rel.get('start_node_label')} to {rel.get('end_node_label')}",
                    ),
                    "source_entity": rel.get("start_node_label"),
                    "target_entity": rel.get("end_node_label"),
                    "properties": [
                        {
                            "name": prop.get("name"),
                            "type": prop.get("type", "STRING"),
                            "description": prop.get("description"),
                        }
                        for prop in rel.get("properties", [])
                    ],
                }
                relationship_types.append(rel_type)

            extraction_schema_data = {
                "entity_types": entity_types,
                "relationship_types": relationship_types,
            }

            # Validate
            schema = ExtractionSchema.model_validate(extraction_schema_data)

            # Write Pydantic models to output_path
            pydantic_path = pathlib.Path(output_path)
            pydantic_path.parent.mkdir(parents=True, exist_ok=True)
            pydantic_code = generate_extraction_models_code(schema)
            pydantic_path.write_text(pydantic_code)

            logger.info("Pydantic models saved", pydantic_path=str(pydantic_path))

            return json.dumps(
                {
                    "status": "success",
                    "pydantic_path": str(pydantic_path),
                    "entity_types": len(entity_types),
                    "relationship_types": len(relationship_types),
                    "message": (
                        f"Pydantic models saved to {pydantic_path}\n"
                        f"You can customize the .py file with Literal constraints and field_validators before running extraction."
                    ),
                },
                indent=2,
            )

        except json.JSONDecodeError as e:
            raise ToolError(f"Invalid modeling output JSON: {e}")
        except Exception as e:
            logger.error("Failed to convert schema", error=str(e))
            raise ToolError(f"Failed to convert schema: {e}")

    # ========================================
    # TOOL 2: Extract Entities (async)
    # ========================================

    @mcp.tool(
        name="extract_entities",
        annotations=ToolAnnotations(
            title="Extract Entities from Graph",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )
    async def extract_entities(
        schema: str = Field(
            ...,
            description="Path to the Pydantic .py schema file generated by convert_schema.",
        ),
        source_label: str = Field(
            default="Chunk",
            description="Label of source nodes to extract from (Chunk or Page)",
        ),
        force: bool = Field(
            default=False,
            description="If true, re-extract all nodes. If false, skip nodes with existing EXTRACTED_FROM.",
        ),
        text_parallel: int = Field(
            default=20,
            description="Max concurrent text extractions (default: 20)",
        ),
        vlm_parallel: int = Field(
            default=5,
            description="Max concurrent VLM extractions (default: 5)",
        ),
        batch_size: int = Field(
            default=10,
            description="Chunks to batch before writing to Neo4j",
        ),
        model: Optional[str] = Field(
            default=None,
            description="LLM model (must support vision). Defaults to EXTRACTION_MODEL env var.",
        ),
        pass_type: str = Field(
            default="full",
            description="Extraction pass type: full, entities_only, relationships_only, corrective",
        ),
        pass_number: int = Field(
            default=1,
            description="Pass number for multi-pass extraction (1, 2, 3...)",
        ),
    ) -> str:
        """
        Extract entities and relationships from graph nodes using LLM structured output.

        **Returns immediately** with a job_id. Use check_extraction_status to monitor progress.

        The tool auto-detects text vs visual chunks:
        - Text chunks (type="text"): sent to LLM with text only (parallel: text_parallel)
        - Visual chunks (images, tables, pages): sent to VLM with text + image (parallel: vlm_parallel)
        """
        actual_model = model or extraction_model

        # Validate pass_type
        try:
            pt = PassType(pass_type)
        except ValueError:
            raise ToolError(
                f"Invalid pass_type: {pass_type}. "
                f"Must be one of: full, entities_only, relationships_only, corrective"
            )

        if pt != PassType.FULL:
            raise ToolError(
                f"pass_type='{pass_type}' is not yet implemented. Only 'full' is supported in v1."
            )

        # Load Pydantic schema
        schema_path = pathlib.Path(schema)
        if not schema_path.exists():
            raise ToolError(f"Schema file not found: {schema}")
        if schema_path.suffix != ".py":
            raise ToolError(f"Schema must be a .py file generated by convert_schema, got: {schema_path.suffix}")

        try:
            output_model = load_extraction_output_model(schema)
            module = sys.modules.get("extraction_models")
            if module is None:
                raise ToolError("Failed to load extraction_models module")
            extraction_schema = schema_from_pydantic_module(module)
            logger.info(
                "Schema loaded from .py module",
                path=schema,
                entities=len(extraction_schema.entity_types),
                relationships=len(extraction_schema.relationship_types),
            )
        except ToolError:
            raise
        except Exception as e:
            raise ToolError(f"Failed to load schema from {schema}: {e}")

        # Query and classify chunks
        try:
            chunks = await query_and_classify_chunks(source_label, force)
        except Exception as e:
            raise ToolError(f"Failed to query chunks from Neo4j: {e}")

        if not chunks:
            return json.dumps(
                {
                    "status": "success",
                    "message": "No chunks to process (all may have been extracted already, or no matching nodes found)",
                    "job_id": None,
                },
                indent=2,
            )

        text_chunks = [c for c in chunks if not c.needs_vlm]
        vlm_chunks = [c for c in chunks if c.needs_vlm]

        logger.info(
            "Chunks classified",
            total=len(chunks),
            text=len(text_chunks),
            vlm=len(vlm_chunks),
        )

        # Create job
        job = job_manager.create_job(
            model=actual_model,
            total_chunks=len(chunks),
            text_chunks=len(text_chunks),
            vlm_chunks=len(vlm_chunks),
            pass_type=pt,
            pass_number=pass_number,
        )

        # Launch background task
        task = asyncio.create_task(
            _run_extraction_job(
                job=job,
                chunks=chunks,
                schema=extraction_schema,
                source_label=source_label,
                output_model=output_model,
                text_parallel=text_parallel,
                vlm_parallel=vlm_parallel,
                batch_size=batch_size,
            )
        )
        job_manager.register_task(job.id, task)

        return json.dumps(
            {
                "status": "started",
                "job_id": job.id,
                "model": actual_model,
                "total_chunks": len(chunks),
                "text_chunks": len(text_chunks),
                "vlm_chunks": len(vlm_chunks),
                "message": (
                    f"Extraction started (job {job.id}). "
                    f"{len(text_chunks)} text chunks (parallel: {text_parallel}), "
                    f"{len(vlm_chunks)} visual chunks (parallel: {vlm_parallel}). "
                    f"Use check_extraction_status to monitor progress."
                ),
            },
            indent=2,
        )

    # ========================================
    # TOOL 3: Check Extraction Status
    # ========================================

    @mcp.tool(
        name="check_extraction_status",
        annotations=ToolAnnotations(
            title="Check Extraction Job Status",
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def check_extraction_status(
        job_id: Optional[str] = Field(
            default=None,
            description="Job ID to check. If not provided, returns status of all jobs.",
        ),
    ) -> str:
        """Check the status of background extraction jobs."""
        if job_id:
            job = job_manager.get_job(job_id)
            if not job:
                return json.dumps(
                    {"error": f"Job {job_id} not found"}, indent=2
                )
            return json.dumps(job.to_status_dict(), indent=2)
        else:
            jobs = job_manager.list_jobs()
            if not jobs:
                return json.dumps(
                    {"message": "No extraction jobs found"}, indent=2
                )
            return json.dumps(
                [j.to_status_dict() for j in jobs], indent=2
            )

    # ========================================
    # TOOL 4: Cancel Extraction
    # ========================================

    @mcp.tool(
        name="cancel_extraction",
        annotations=ToolAnnotations(
            title="Cancel Extraction Job",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def cancel_extraction(
        job_id: str = Field(..., description="Job ID to cancel"),
    ) -> str:
        """Cancel a running extraction job."""
        success = job_manager.cancel_job(job_id)
        if success:
            return json.dumps(
                {
                    "status": "cancelled",
                    "job_id": job_id,
                    "message": f"Job {job_id} has been cancelled.",
                },
                indent=2,
            )
        else:
            job = job_manager.get_job(job_id)
            if not job:
                raise ToolError(f"Job {job_id} not found")
            return json.dumps(
                {
                    "status": job.status.value,
                    "job_id": job_id,
                    "message": f"Job {job_id} is already {job.status.value}, cannot cancel.",
                },
                indent=2,
            )

    return mcp


async def main(
    db_url: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    database: str = "neo4j",
    extraction_model: str = DEFAULT_EXTRACTION_MODEL,
    transport: Literal["stdio", "sse"] = "stdio",
    host: str = "127.0.0.1",
    port: int = 8002,
) -> None:
    """Main entry point for the MCP server."""

    db_url = db_url or os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    username = username or os.environ.get("NEO4J_USERNAME", "neo4j")
    password = password or os.environ.get("NEO4J_PASSWORD", "password")
    database = os.environ.get("NEO4J_DATABASE", database)
    extraction_model = os.environ.get("EXTRACTION_MODEL", extraction_model)

    logger.info(
        "Starting MCP Neo4j Entity Graph Server",
        db_url=db_url,
        database=database,
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

    mcp = create_mcp_server(
        neo4j_driver=neo4j_driver,
        database=database,
        extraction_model=extraction_model,
    )

    if transport == "stdio":
        logger.info("Running with stdio transport")
        await mcp.run_stdio_async()
    else:
        logger.info(f"Running with SSE transport on {host}:{port}")
        await mcp.run_sse_async(host=host, port=port)


def run():
    """Synchronous entry point for CLI."""
    asyncio.run(main())


if __name__ == "__main__":
    run()
