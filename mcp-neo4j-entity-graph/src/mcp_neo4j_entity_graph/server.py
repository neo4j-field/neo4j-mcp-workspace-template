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
from .extraction_identity import extraction_fingerprint, source_fingerprint, digest, classify_source
from .ownership import (
    write_entity as write_owned_entity, write_relationship as write_owned_relationship,
    remove_contributions, collect_unused_entities, identifier, coalesce_result,
)
from .job_manager import ExtractionJobInfo, JobManager, JobStatus
from .models import (
    ChunkExtractionOutcome,
    ChunkExtractionResult,
    ClassifiedChunk,
    ExtractionMetadata,
    ExtractionSchema,
    PassType,
)
from .ontology_loader import load_ontology
from .schema_generator import generate_extraction_models_code
from .text_extractor import TextExtractor
from .vlm_extractor import VlmExtractor

from platformdirs import user_cache_dir

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
    ontology_database: str = "ontology",
    extraction_model: str = DEFAULT_EXTRACTION_MODEL,
    ontology_driver: Optional[AsyncDriver] = None,
) -> FastMCP:
    """Create the entity graph MCP server with all tools.

    Args:
        neo4j_driver: Driver for the Documents DB (chunk reads / entity writes)
        database: Default Neo4j database for chunk reads / entity writes (Document DB)
        ontology_database: Neo4j database for ontology reads (Ontology DB)
        extraction_model: Default LLM model for extraction
        ontology_driver: Driver for the Ontology DB. Defaults to neo4j_driver when
            both databases are on the same instance (local / single-instance Aura).
    """
    if ontology_driver is None:
        ontology_driver = neo4j_driver

    mcp = FastMCP("mcp-neo4j-entity-graph")
    job_manager = JobManager()

    # ========================================
    # Neo4j read: classify chunks
    # ========================================

    async def query_and_classify_chunks(
        source_label: str,
        force: bool,
        fingerprint: str,
        source_ids: Optional[list[str]],
    ) -> tuple[list[ClassifiedChunk], int]:
        """Query Neo4j for source nodes and classify them as text or VLM."""

        # Hash actual source inputs before selecting work. Provenance links alone
        # are not evidence that this schema/configuration completed successfully.
        count_query = f"""
            MATCH (n:{source_label})
            WHERE (n.text IS NOT NULL OR n.imageBase64 IS NOT NULL)
              AND ($source_ids IS NULL OR n.id IN $source_ids)
            RETURN count(n) AS eligible_sources
        """
        query = f"""
            MATCH (n:{source_label})
            WHERE (n.text IS NOT NULL OR n.imageBase64 IS NOT NULL)
              AND ($source_ids IS NULL OR n.id IN $source_ids)
            RETURN
                n.id AS id,
                n.text AS text,
                coalesce(n.type, 'text') AS type,
                n:Page AS isPage,
                n.documentName AS documentName,
                n.sectionContext AS sectionContext,
                n.imageBase64 AS imageBase64,
                n.imageMimeType AS imageMimeType,
                n.textAsHtml AS textAsHtml,
                n.caption AS caption,
                [(n)<-[p:PROCESSED_SOURCE]-(run:EntityExtractionRun)
                 WHERE run.fingerprint = $fingerprint AND run.status = 'complete'
                   AND coalesce(p.invalidated, false) = false
                 | p.sourceFingerprint] AS completedFingerprints
        """

        async with neo4j_driver.session(database=database) as session:
            count_result = await session.run(count_query, source_ids=source_ids)
            count_record = await count_result.single()
            result = await session.run(query, fingerprint=fingerprint, source_ids=source_ids)
            records = await result.data()
        eligible_sources = count_record["eligible_sources"] if count_record else 0

        chunks: list[ClassifiedChunk] = []
        for r in records:
            chunk = classify_source(r)
            chunks.append(chunk)
            if not force and source_fingerprint(chunk) in (r.get("completedFingerprints") or []):
                chunks.pop()

        return chunks, eligible_sources

    # ========================================
    # Neo4j write: batch results
    # ========================================

    async def write_batch_to_neo4j(
        results: list[ChunkExtractionResult],
        schema: ExtractionSchema,
        source_label: str,
        metadata: ExtractionMetadata,
        *,
        property_policy: str = "preserve_existing",
        transaction: Any,
        scope_id: str,
        write_entities: bool = True,
        write_relationships: bool = True,
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
                    if key_value is not None and key_value != "":
                        entities_by_label[entity.label].append(
                            {
                                "key_value": key_value,
                                "properties": {
                                    k: v for k, v in entity.properties.items() if v is not None
                                },
                                "proposed_json": json.dumps(
                                    entity.properties, ensure_ascii=False, default=str
                                ),
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
                            "properties": {k: v for k, v in rel.properties.items() if v is not None},
                            "chunk_id": chunk_result.chunk_id,
                        }
                    )

        meta_props = {
            "model": metadata.model,
            "runId": metadata.run_id,
            "extractionFingerprint": metadata.fingerprint,
            "extractedAt": metadata.timestamp,
            "passNumber": metadata.pass_number,
            "passType": metadata.pass_type.value,
        }

        if write_entities:
            ids = set()
            for label, entities in entities_by_label.items():
                entity_schema = schema.get_entity_schema(label)
                for entity in entities:
                    object_id = await write_owned_entity(
                        transaction, source_label, label, entity_schema.key_property,
                        entity, meta_props, property_policy, scope_id,
                    )
                    ids.add(object_id)
                    stats["extracted_from_created"] += 1
            stats["entities_created"] = len(ids)
        if write_relationships:
            for rels in rels_by_type.values():
                for rel in rels:
                    await write_owned_relationship(transaction, source_label, rel, meta_props, scope_id, property_policy)
                    stats["relationships_created"] += 1

        return stats

    async def count_persisted_sources(
        source_ids: list[str],
        source_label: str,
        metadata: ExtractionMetadata,
        transaction: Any,
    ) -> int:
        """Count source units linked by this exact extraction run."""
        if not source_ids:
            return 0
        query = f"""
            MATCH (c:{source_label})<-[r:EXTRACTED_FROM]-()
            WHERE c.id IN $source_ids AND r.extractedAt = $extracted_at
            RETURN count(DISTINCT c) AS sources_persisted
        """
        result = await transaction.run(
            query, source_ids=source_ids, extracted_at=metadata.timestamp,
        )
        record = await result.single()
        return record["sources_persisted"] if record else 0

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
        property_policy: str,
        fingerprint: str,
        scope_id: str,
    ) -> None:
        """Background task that performs the actual extraction."""
        tasks: list[asyncio.Task] = []
        try:
            # A forced/incompatible attempt may partially write before failing.
            # Invalidate older completion evidence before any such write so a
            # later request cannot silently reuse a now-partial graph state.
            async with neo4j_driver.session(database=database) as session:
                result = await session.run(
                    f"MATCH (n:{source_label})<-[p:PROCESSED_SOURCE]-(:EntityExtractionRun) "
                    "WHERE n.id IN $source_ids SET p.invalidated = true",
                    source_ids=[c.id for c in chunks],
                )
                await result.consume()
            job_manager.update_status(job.id, JobStatus.EXTRACTING)

            text_chunks = [c for c in chunks if not c.needs_vlm]
            vlm_chunks = [c for c in chunks if c.needs_vlm]

            text_extractor = TextExtractor(model=job.model)
            vlm_extractor = VlmExtractor(model=job.model)

            metadata = ExtractionMetadata(
                model=job.model, run_id=job.id, fingerprint=fingerprint,
                pass_number=job.pass_number,
                pass_type=job.pass_type,
            )

            all_results: list[ChunkExtractionResult] = []
            # Run text and VLM extraction concurrently
            text_semaphore = asyncio.Semaphore(text_parallel)
            vlm_semaphore = asyncio.Semaphore(vlm_parallel)

            async def extract_text_chunk(chunk: ClassifiedChunk) -> ChunkExtractionResult:
                async with text_semaphore:
                    job_manager.update_progress(
                        job.id, sources_attempted=job.sources_attempted + 1
                    )
                    try:
                        return await text_extractor.extract_chunk(chunk, schema, output_model)
                    except Exception as exc:
                        return ChunkExtractionResult(
                            chunk_id=chunk.id,
                            outcome=ChunkExtractionOutcome.FAILED,
                            error=f"Unexpected text extraction failure: {exc}",
                        )

            async def extract_vlm_chunk(chunk: ClassifiedChunk) -> ChunkExtractionResult:
                async with vlm_semaphore:
                    job_manager.update_progress(
                        job.id, sources_attempted=job.sources_attempted + 1
                    )
                    try:
                        return await vlm_extractor.extract_chunk(chunk, schema, output_model)
                    except Exception as exc:
                        return ChunkExtractionResult(
                            chunk_id=chunk.id,
                            outcome=ChunkExtractionOutcome.FAILED,
                            error=f"Unexpected VLM extraction failure: {exc}",
                        )

            # Create all tasks
            for c in text_chunks:
                tasks.append(asyncio.create_task(extract_text_chunk(c)))
            for c in vlm_chunks:
                tasks.append(asyncio.create_task(extract_vlm_chunk(c)))

            for coro in asyncio.as_completed(tasks):
                result = await coro
                if result.outcome == ChunkExtractionOutcome.FAILED:
                    failed_ids = [*job.failed_source_ids, result.chunk_id]
                    failure_details = {
                        **job.failure_details,
                        result.chunk_id: result.error or "unknown extraction failure",
                    }
                    job_manager.update_progress(
                        job.id,
                        chunks_failed=job.chunks_failed + 1,
                        sources_failed=job.sources_failed + 1,
                        failed_source_ids=failed_ids,
                        failure_details=failure_details,
                    )
                else:
                    result = coalesce_result(result, schema, property_policy)
                    all_results.append(result)
                    job_manager.update_progress(
                        job.id,
                        chunks_completed=job.chunks_completed + 1,
                        sources_succeeded=job.sources_succeeded
                        + (result.outcome == ChunkExtractionOutcome.SUCCESS),
                        sources_empty=job.sources_empty
                        + (result.outcome == ChunkExtractionOutcome.EMPTY),
                        entities_extracted=job.entities_extracted + len(result.entities),
                        relationships_extracted=job.relationships_extracted
                        + len(result.relationships),
                    )

                logger.info(
                    (
                        f"[{job.chunks_completed + job.chunks_failed}/"
                        f"{job.selected_sources}] Source processed"
                    ),
                    chunk_id=result.chunk_id,
                    outcome=result.outcome.value,
                    entities=len(result.entities),
                    rels=len(result.relationships),
                )

            # Canonical first-wins precedence must not depend on API completion order.
            all_results.sort(key=lambda r: r.chunk_id)
            if job.sources_failed:
                job_manager.update_status(
                    job.id, JobStatus.FAILED,
                    error=f"Coverage failure: {job.sources_failed}/{job.selected_sources} selected source units failed extraction",
                )
            else:
                async def publish(tx):
                    # Lock source rows in a stable order and invalidate completion
                    # again at publication, after any concurrent earlier publish.
                    result = await tx.run(
                        f"MATCH (n:{source_label}) WHERE n.id IN $source_ids "
                        "WITH n ORDER BY n.id "
                        "SET n.__extractionPublicationLock = coalesce(n.__extractionPublicationLock, 0) + 1 "
                        "WITH n OPTIONAL MATCH (n)<-[p:PROCESSED_SOURCE]-(:EntityExtractionRun) "
                        "SET p.invalidated = true",
                        source_ids=[c.id for c in chunks],
                    )
                    await result.consume()
                    current = await (await tx.run(
                        f"MATCH (n:{source_label}) WHERE n.id IN $source_ids RETURN "
                        "n.id AS id, n.text AS text, coalesce(n.type, 'text') AS type, n:Page AS isPage, "
                        "n.documentName AS documentName, n.sectionContext AS sectionContext, "
                        "n.imageBase64 AS imageBase64, n.imageMimeType AS imageMimeType, "
                        "n.textAsHtml AS textAsHtml, n.caption AS caption",
                        source_ids=[c.id for c in chunks],
                    )).data()
                    actual = sorted((r["id"], source_fingerprint(classify_source(r))) for r in current)
                    expected = sorted((c.id, source_fingerprint(c)) for c in chunks)
                    if actual != expected:
                        raise RuntimeError("Source inputs changed while extraction was running; retry with current inputs")
                    # The transaction rolls back cleanup and new output together.
                    candidates = await remove_contributions(
                        tx, source_label, [c.id for c in chunks], scope_id,
                    )
                    totals = {"entities_created": 0, "relationships_created": 0, "extracted_from_created": 0}
                    batches = 0
                    for offset in range(0, len(all_results), batch_size):
                        batch_stats = await write_batch_to_neo4j(
                            all_results[offset:offset + batch_size], schema, source_label,
                            metadata, property_policy=property_policy, transaction=tx,
                            scope_id=scope_id, write_relationships=False,
                        )
                        for key in totals:
                            totals[key] += batch_stats[key]
                        batches += 1
                    if totals["extracted_from_created"] != sum(len(r.entities) for r in all_results):
                        raise RuntimeError("Entity persistence mismatch")
                    relationships = await write_batch_to_neo4j(
                        all_results, schema, source_label, metadata, transaction=tx,
                        scope_id=scope_id, property_policy=property_policy, write_entities=False,
                    )
                    totals["relationships_created"] = relationships["relationships_created"]
                    if totals["relationships_created"] != sum(len(r.relationships) for r in all_results):
                        raise RuntimeError("Relationship persistence mismatch")
                    await collect_unused_entities(tx, candidates)
                    persisted = await count_persisted_sources(
                        [r.chunk_id for r in all_results if r.outcome == ChunkExtractionOutcome.SUCCESS],
                        source_label, metadata, tx,
                    )
                    result = await tx.run(
                        f"""
                        MERGE (run:EntityExtractionRun {{runId: $run_id}})
                        SET run.fingerprint=$fingerprint, run.model=$model, run.sourceLabel=$source_label,
                            run.scopeId=$scope, run.completedAt=datetime(), run.status='writing'
                        WITH run UNWIND $sources AS source
                        MATCH (n:{source_label} {{id: source.id}})
                        MERGE (run)-[p:PROCESSED_SOURCE {{sourceFingerprint: source.hash}}]->(n)
                        SET p.invalidated=false
                        WITH run, count(p) AS published
                        SET run.status = CASE WHEN published=$expected THEN 'complete' ELSE 'failed' END
                        RETURN published
                        """,
                        run_id=job.id, fingerprint=fingerprint, model=job.model,
                        source_label=source_label, scope=scope_id,
                        sources=[{"id": c.id, "hash": source_fingerprint(c)} for c in chunks],
                        expected=len(chunks),
                    )
                    record = await result.single()
                    if record is None or record["published"] != len(chunks):
                        raise RuntimeError("Could not publish completion for every selected source")
                    return {**totals, "batches_written": batches, "sources_persisted": persisted}

                job_manager.update_status(job.id, JobStatus.WRITING)
                async with neo4j_driver.session(database=database) as session:
                    published = await session.execute_write(publish)
                job_manager.update_progress(job.id, **published)
                job_manager.update_status(job.id, JobStatus.COMPLETE)
            logger.info(
                "Extraction job finished",
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
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

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
        key_normalization: Optional[dict[str, Literal["strip", "strip_lower"]]] = Field(
            default=None,
            description="Per-entity-label key policy, shared by relationship endpoints. Default strip preserves case; strip_lower must match CSV keys.",
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
            pydantic_code = generate_extraction_models_code(
                schema, key_normalization=key_normalization
            )
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
    # TOOL: Setup Ontology DB
    # ========================================

    @mcp.tool(
        name="setup_ontology_db",
        annotations=ToolAnnotations(
            title="Setup Ontology DB constraints",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def setup_ontology_db() -> str:
        """Create constraints and indexes on the Ontology DB.

        Idempotent — safe to call multiple times. Run once after the Ontology DB
        is first created. The Ontology DB schema is documented in
        `mcp-neo4j-entity-graph/docs/ONTOLOGY_DB_SCHEMA.md`.
        """
        statements = [
            "CREATE CONSTRAINT ontology_name_unique IF NOT EXISTS FOR (o:Ontology) REQUIRE o.name IS UNIQUE",
            "CREATE CONSTRAINT node_type_name_unique IF NOT EXISTS FOR (nt:NodeType) REQUIRE nt.name IS UNIQUE",
            "CREATE CONSTRAINT relationship_type_name_unique IF NOT EXISTS FOR (rt:RelationshipType) REQUIRE rt.name IS UNIQUE",
            "CREATE CONSTRAINT alias_map_name_unique IF NOT EXISTS FOR (am:AliasMap) REQUIRE am.name IS UNIQUE",
            "CREATE CONSTRAINT blocklist_name_unique IF NOT EXISTS FOR (bl:Blocklist) REQUIRE bl.name IS UNIQUE",
            "CREATE INDEX property_def_name IF NOT EXISTS FOR (pd:PropertyDef) ON (pd.name)",
        ]
        try:
            async with ontology_driver.session(database=ontology_database) as session:
                for stmt in statements:
                    await session.run(stmt)
            logger.info("Ontology DB setup complete", database=ontology_database)
            return json.dumps(
                {
                    "status": "success",
                    "database": ontology_database,
                    "constraints_created": len(statements),
                    "message": (
                        f"Ontology DB '{ontology_database}' is ready. "
                        f"Create your ontology by writing :Ontology, :NodeType, :PropertyDef, "
                        f":RelationshipType, :AliasMap, :Blocklist nodes."
                    ),
                },
                indent=2,
            )
        except Exception as e:
            logger.error("Failed to setup ontology DB", error=str(e))
            raise ToolError(f"Failed to setup ontology DB: {e}")

    # ========================================
    # TOOL: Generate Schema from Ontology
    # ========================================

    @mcp.tool(
        name="generate_schema_from_ontology",
        annotations=ToolAnnotations(
            title="Generate Pydantic schema from Ontology DB",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def generate_schema_from_ontology(
        ontology_name: str = Field(
            ...,
            description="Name of the :Ontology node in the Ontology DB to compile.",
        ),
    ) -> str:
        """Read an ontology from the Ontology DB and compile it to a Pydantic schema.

        The compiled schema is cached in a platform-appropriate user cache dir,
        keyed by `ontology_name` (overwritten on each call). Use this cache path
        as the `schema` argument to `extract_entities`, OR pass `ontology_name`
        directly to `extract_entities` to regenerate-then-extract in one step.

        The Ontology DB graph schema is documented in
        `mcp-neo4j-entity-graph/docs/ONTOLOGY_DB_SCHEMA.md`.
        """
        try:
            schema, normalizers = await load_ontology(
                ontology_driver, ontology_database, ontology_name
            )
        except ValueError as e:
            raise ToolError(str(e))
        except Exception as e:
            logger.error("Failed to load ontology", error=str(e))
            raise ToolError(f"Failed to load ontology '{ontology_name}': {e}")

        try:
            code = generate_extraction_models_code(schema, normalizers)
        except Exception as e:
            logger.error("Failed to generate Pydantic code", error=str(e))
            raise ToolError(f"Failed to generate Pydantic code: {e}")

        cache_root = pathlib.Path(user_cache_dir("mcp-neo4j-entity-graph")) / "schemas"
        cache_root.mkdir(parents=True, exist_ok=True)
        cache_path = cache_root / f"{ontology_name}.py"
        cache_path.write_text(code)

        logger.info(
            "Pydantic schema generated from ontology",
            ontology=ontology_name,
            path=str(cache_path),
            entities=len(schema.entity_types),
            relationships=len(schema.relationship_types),
        )

        return json.dumps(
            {
                "status": "success",
                "ontology_name": ontology_name,
                "cache_path": str(cache_path),
                "entity_types": len(schema.entity_types),
                "relationship_types": len(schema.relationship_types),
                "schema_content": code,
                "message": (
                    f"Compiled '{ontology_name}' to {cache_path}. "
                    f"Pass ontology_name='{ontology_name}' to extract_entities to use it."
                ),
            },
            indent=2,
        )

    # ========================================
    # TOOL 2: Extract Entities (async)
    # ========================================

    @mcp.tool(
        name="extract_entities",
        annotations=ToolAnnotations(
            title="Extract Entities from Graph",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )
    async def extract_entities(
        schema: Optional[str] = Field(
            default=None,
            description=(
                "Path to a Pydantic .py schema file generated by convert_schema. "
                "Use this OR ontology_name (exactly one is required)."
            ),
        ),
        ontology_name: Optional[str] = Field(
            default=None,
            description=(
                "Name of an :Ontology in the Ontology DB. When provided, the schema "
                "is regenerated from the ontology before extraction (always fresh — "
                "picks up edits made in Bloom). Use this OR schema (exactly one is required)."
            ),
        ),
        source_label: str = Field(
            default="Chunk",
            description="Label of source nodes to extract from (Chunk or Page)",
        ),
        source_ids: Optional[list[str]] = Field(
            default=None, description="Optional source node IDs to rebuild. Default: all eligible sources.",
        ),
        extraction_scope: Optional[str] = Field(
            default=None,
            description="Stable ownership scope across schema revisions. Defaults to ontology name or absolute schema path. Other scopes coexist.",
        ),
        property_policy: Literal["preserve_existing", "overwrite"] = Field(
            default="preserve_existing",
            description="Entity and relationship property conflict policy. Preserve existing non-null values by default; overwrite explicitly replaces them. Null proposals do not delete external properties; omitted/null fields withdraw prior owned assertions during replacement. Proposed values and conflicts are recorded on source contribution records.",
        ),
        force: bool = Field(
            default=False,
            description="If true, re-extract all eligible nodes. Otherwise skip only sources with matching successful completion evidence, source content, schema, extractor, model and configuration.",
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
            description="Extraction pass type. Only 'full' is currently supported. ('entities_only', 'relationships_only', 'corrective' are planned for a future release.)",
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
        if batch_size < 1 or text_parallel < 1 or vlm_parallel < 1:
            raise ToolError("batch_size and extraction parallelism must be positive")

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

        # Resolve schema source: ontology_name (regenerate) or schema (existing path)
        if ontology_name and schema:
            raise ToolError(
                "Provide exactly one of `ontology_name` or `schema`, not both."
            )
        if not ontology_name and not schema:
            raise ToolError(
                "Provide either `ontology_name` (recommended for the lawyer demo flow) "
                "or `schema` (path to a .py file from convert_schema)."
            )

        if ontology_name:
            try:
                ontology_schema, ontology_normalizers = await load_ontology(
                    ontology_driver, ontology_database, ontology_name
                )
            except ValueError as e:
                raise ToolError(str(e))
            except Exception as e:
                raise ToolError(f"Failed to load ontology '{ontology_name}': {e}")

            try:
                code = generate_extraction_models_code(ontology_schema, ontology_normalizers)
            except Exception as e:
                raise ToolError(f"Failed to compile ontology '{ontology_name}': {e}")

            cache_root = pathlib.Path(user_cache_dir("mcp-neo4j-entity-graph")) / "schemas"
            cache_root.mkdir(parents=True, exist_ok=True)
            cache_path = cache_root / f"{ontology_name}.py"
            cache_path.write_text(code)
            schema = str(cache_path)
            logger.info(
                "Regenerated schema from ontology before extraction",
                ontology=ontology_name,
                cache_path=str(cache_path),
            )

        # Load Pydantic schema
        schema_path = pathlib.Path(schema)
        if not schema_path.exists():
            raise ToolError(f"Schema file not found: {schema}")
        if schema_path.suffix != ".py":
            raise ToolError(f"Schema must be a .py file generated by convert_schema, got: {schema_path.suffix}")

        try:
            schema_source = schema_path.read_bytes()
            output_model = load_extraction_output_model(schema, source_bytes=schema_source)
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
            identifier(source_label)
            scope_id = digest({"source_label": source_label, "scope": extraction_scope or (
                f"ontology:{ontology_name}" if ontology_name else str(schema_path.resolve())
            )})
            fingerprint = extraction_fingerprint(
                schema_path, model=actual_model, source_label=source_label,
                property_policy=property_policy, pass_type=pt.value, pass_number=pass_number,
                schema_source=schema_source, scope_id=scope_id,
            )
            chunks, eligible_sources = await query_and_classify_chunks(source_label, force, fingerprint, source_ids)
        except Exception as e:
            raise ToolError(f"Failed to query chunks from Neo4j: {e}")

        if not chunks:
            return json.dumps(
                {
                    "status": "success",
                    "message": "No chunks to process (all may have been extracted already, or no matching nodes found)",
                    "job_id": None,
                    "eligible_sources": eligible_sources,
                    "selected_sources": 0,
                    "extraction_fingerprint": fingerprint,
                },
                indent=2,
            )

        # Legacy links have no reliable deletion/property ownership. Refuse
        # rather than guessing that their connected nodes belong to extraction.
        async with neo4j_driver.session(database=database) as session:
            record = await (await session.run(
                f"MATCH (c:{identifier(source_label)})<-[r:EXTRACTED_FROM]-(e) "
                "WHERE c.id IN $source_ids AND (coalesce(r.ownershipVersion, 0) <> 1 "
                "OR r.extractionScope IS NULL OR r.proposedPropertiesJson IS NULL "
                "OR e.__extractionValues IS NULL) "
                "RETURN count(r) AS legacy",
                source_ids=[c.id for c in chunks],
            )).single()
            if record and record["legacy"]:
                raise ToolError(
                    "Legacy EXTRACTED_FROM links lack ownership metadata. Use a fresh source namespace "
                    "or an explicitly reviewed ownership migration; existing data was not replaced."
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
            eligible_sources=eligible_sources,
            selected_sources=len(chunks),
            pass_type=pt,
            pass_number=pass_number,
        )

        job.extraction_fingerprint = fingerprint

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
                property_policy=property_policy,
                fingerprint=fingerprint,
                scope_id=scope_id,
            )
        )
        job_manager.register_task(job.id, task)

        return json.dumps(
            {
                "status": "started",
                "extraction_fingerprint": fingerprint,
                "job_id": job.id,
                "model": actual_model,
                "total_chunks": len(chunks),
                "eligible_sources": eligible_sources,
                "selected_sources": len(chunks),
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
    ontology_database: str = "ontology",
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
    ontology_database = os.environ.get("NEO4J_ONTOLOGY_DATABASE", ontology_database)
    extraction_model = os.environ.get("EXTRACTION_MODEL", extraction_model)

    # Separate Aura instance for the Ontology DB — fall back to Documents DB credentials
    # when NEO4J_ONTOLOGY_URI is unset (single-instance / local setup).
    ontology_url = os.environ.get("NEO4J_ONTOLOGY_URI", "").strip() or db_url
    ontology_username = os.environ.get("NEO4J_ONTOLOGY_USERNAME", "").strip() or username
    ontology_password = os.environ.get("NEO4J_ONTOLOGY_PASSWORD", "").strip() or password

    logger.info(
        "Starting MCP Neo4j Entity Graph Server",
        db_url=db_url,
        database=database,
        ontology_url=ontology_url,
        ontology_database=ontology_database,
        extraction_model=extraction_model,
    )

    neo4j_driver = AsyncGraphDatabase.driver(db_url, auth=(username, password))

    # Create a dedicated ontology driver only when it points at a different instance.
    if ontology_url != db_url or ontology_username != username:
        ontology_driver: AsyncDriver = AsyncGraphDatabase.driver(
            ontology_url, auth=(ontology_username, ontology_password)
        )
    else:
        ontology_driver = neo4j_driver

    try:
        async with neo4j_driver.session(database=database) as session:
            await session.run("RETURN 1")
        logger.info("Neo4j documents DB connection verified")
    except Exception as e:
        logger.error(f"Failed to connect to documents DB: {e}")
        raise

    if ontology_driver is not neo4j_driver:
        try:
            async with ontology_driver.session(database=ontology_database) as session:
                await session.run("RETURN 1")
            logger.info("Neo4j ontology DB connection verified")
        except Exception as e:
            logger.error(f"Failed to connect to ontology DB: {e}")
            raise

    mcp = create_mcp_server(
        neo4j_driver=neo4j_driver,
        ontology_driver=ontology_driver,
        database=database,
        ontology_database=ontology_database,
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
