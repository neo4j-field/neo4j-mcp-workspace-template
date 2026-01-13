"""MCP server for entity extraction from graph nodes.

Tools:
- extract_entities_from_graph: Extract entities from source nodes and create entity graph
- convert_schema: Convert data modeling output to extraction schema

Optimized for high parallelism with LiteLLM multi-provider support.
"""

import asyncio
import json
import logging
import os
import sys
from typing import Literal, Optional

import structlog
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from neo4j import AsyncGraphDatabase, AsyncDriver
from pydantic import Field

from .extractor import EntityExtractor
from .models import ExtractionSchema, ProgressUpdate, ChunkExtractionResult

# Configure structlog to write to stderr (required for MCP stdio transport)
structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer()
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    cache_logger_on_first_use=True
)

logger = structlog.get_logger()

# Default extraction model
DEFAULT_EXTRACTION_MODEL = "gpt-5-mini"


def create_mcp_server(
    neo4j_driver: AsyncDriver,
    database: str = "neo4j",
    extraction_model: str = DEFAULT_EXTRACTION_MODEL
) -> FastMCP:
    """Create the entity graph MCP server with all tools."""
    
    mcp = FastMCP("mcp-neo4j-entity-graph")
    
    # ========================================
    # Helper: Write batch of extractions to Neo4j
    # ========================================
    
    async def write_batch_to_neo4j(
        results: list[ChunkExtractionResult],
        schema: ExtractionSchema,
        source_label: str
    ) -> dict:
        """Write a batch of extraction results to Neo4j in optimized transactions.
        
        Batches all entities by label and all relationships by type for efficient writes.
        Uses a single session for the entire batch.
        
        Returns stats dict with entities_created, relationships_created, extracted_from_created
        """
        stats = {
            "entities_created": 0,
            "relationships_created": 0,
            "extracted_from_created": 0
        }
        
        # Collect all entities by label across all chunks
        entities_by_label: dict[str, list[dict]] = {}
        for chunk_result in results:
            for entity in chunk_result.entities:
                if entity.label not in entities_by_label:
                    entities_by_label[entity.label] = []
                
                entity_schema = schema.get_entity_schema(entity.label)
                if entity_schema:
                    key_property = entity_schema.key_property
                    key_value = entity.properties.get(key_property)
                    if key_value:
                        entities_by_label[entity.label].append({
                            "key_value": key_value,
                            "properties": entity.properties,
                            "chunk_id": chunk_result.chunk_id
                        })
        
        # Collect all relationships by type across all chunks
        rels_by_type: dict[str, list[dict]] = {}
        for chunk_result in results:
            for rel in chunk_result.relationships:
                key = f"{rel.type}_{rel.source_label}_{rel.target_label}"
                if key not in rels_by_type:
                    rels_by_type[key] = []
                
                source_schema = schema.get_entity_schema(rel.source_label)
                target_schema = schema.get_entity_schema(rel.target_label)
                
                if source_schema and target_schema:
                    rels_by_type[key].append({
                        "type": rel.type,
                        "source_label": rel.source_label,
                        "target_label": rel.target_label,
                        "source_key_property": source_schema.key_property,
                        "target_key_property": target_schema.key_property,
                        "source_key_value": rel.source_key,
                        "target_key_value": rel.target_key,
                        "properties": rel.properties
                    })
        
        # Use a single session for all writes
        async with neo4j_driver.session(database=database) as session:
            # Write all entities by label
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
                    MERGE (e)-[:EXTRACTED_FROM]->(c)
                    RETURN count(DISTINCT e) as entities_created, count(*) as rels_created
                """
                
                result = await session.run(query, entities=entities)
                record = await result.single()
                if record:
                    stats["entities_created"] += record["entities_created"]
                    stats["extracted_from_created"] += record["rels_created"]
            
            # Write all relationships by type
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
    # TOOL 1: Extract Entities from Graph
    # ========================================
    
    @mcp.tool(
        name="extract_entities_from_graph",
        annotations=ToolAnnotations(
            title="Extract Entities from Graph",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )
    async def extract_entities_from_graph(
        schema_json: str = Field(..., description="JSON string with extraction schema (entity_types, relationship_types), or path to schema file"),
        source_label: str = Field(default="Chunk", description="Label of source nodes to extract from"),
        source_text_property: str = Field(default="text", description="Property containing text to extract from"),
        force: bool = Field(default=False, description="If true, extract from all nodes. If false, only from nodes without prior extraction."),
        parallel: int = Field(default=20, description="Maximum concurrent extractions (default: 20, reduce to 5-10 if hitting rate limits)"),
        batch_size: int = Field(default=10, description="Number of chunks to batch before writing to Neo4j"),
        model: Optional[str] = Field(default=None, description="LLM model to use (defaults to EXTRACTION_MODEL env var)")
    ) -> str:
        """
        Extract entities and relationships from graph nodes using LLM.
        
        This tool:
        1. Queries all nodes with the specified label (filtered by prior extraction unless force=true)
        2. Extracts entities/relationships using LLM with structured output
        3. Creates entity nodes directly in Neo4j
        4. Creates EXTRACTED_FROM relationships to source nodes for provenance
        
        **Returns:** Summary of extracted entities and relationships
        """
        import pathlib
        
        actual_model = model or extraction_model
        
        logger.info(
            "Starting entity extraction from graph",
            source_label=source_label,
            force=force,
            model=actual_model,
            parallel=parallel,
            batch_size=batch_size
        )
        
        try:
            # Parse schema
            if schema_json.strip().startswith("{"):
                schema_data = json.loads(schema_json)
            else:
                schema_file = pathlib.Path(schema_json)
                if not schema_file.exists():
                    raise ToolError(f"Schema file not found: {schema_json}")
                schema_data = json.loads(schema_file.read_text())
            
            schema = ExtractionSchema.model_validate(schema_data)
            
            # Build query to get source nodes
            if force:
                query = f"""
                    MATCH (n:{source_label})
                    WHERE n.{source_text_property} IS NOT NULL
                    RETURN n.id as id, n.{source_text_property} as text
                """
            else:
                query = f"""
                    MATCH (n:{source_label})
                    WHERE n.{source_text_property} IS NOT NULL
                      AND NOT (n)<-[:EXTRACTED_FROM]-()
                    RETURN n.id as id, n.{source_text_property} as text
                """
            
            # Get source nodes from Neo4j
            async with neo4j_driver.session(database=database) as session:
                result = await session.run(query)
                records = await result.data()
            
            if not records:
                return json.dumps({
                    "status": "success",
                    "message": "No nodes to process (all may have been extracted already)",
                    "nodes_processed": 0,
                    "entities_created": 0,
                    "relationships_created": 0
                }, indent=2)
            
            chunks = [{"id": r["id"], "text": r["text"]} for r in records]
            total_chunks = len(chunks)
            logger.info(f"Found {total_chunks} nodes to process")
            
            # Create extractor (validates model support)
            try:
                extractor = EntityExtractor(model=actual_model)
            except ValueError as e:
                raise ToolError(str(e))
            
            # Track totals
            total_stats = {
                "entities_extracted": 0,
                "entities_created": 0,
                "relationships_extracted": 0,
                "relationships_created": 0,
                "extracted_from_created": 0,
                "entity_labels": set()
            }
            
            # Process chunks in batches for optimized Neo4j writes
            semaphore = asyncio.Semaphore(parallel)
            extraction_buffer: list[ChunkExtractionResult] = []
            buffer_lock = asyncio.Lock()
            completed = 0
            batches_written = 0
            
            async def extract_chunk(chunk: dict) -> ChunkExtractionResult:
                """Extract from one chunk."""
                async with semaphore:
                    return await extractor.extract_from_text(
                        text=chunk["text"],
                        schema=schema,
                        chunk_id=chunk["id"]
                    )
            
            async def flush_buffer():
                """Write buffered results to Neo4j."""
                nonlocal batches_written
                async with buffer_lock:
                    if not extraction_buffer:
                        return {}
                    
                    to_write = extraction_buffer.copy()
                    extraction_buffer.clear()
                
                batches_written += 1
                logger.info(f"Writing batch {batches_written} ({len(to_write)} chunks) to Neo4j")
                return await write_batch_to_neo4j(to_write, schema, source_label)
            
            # Extract all chunks in parallel
            tasks = [extract_chunk(chunk) for chunk in chunks]
            
            for coro in asyncio.as_completed(tasks):
                result = await coro
                completed += 1
                
                # Track extraction stats
                total_stats["entities_extracted"] += len(result.entities)
                total_stats["relationships_extracted"] += len(result.relationships)
                total_stats["entity_labels"].update(e.label for e in result.entities)
                
                # Add to buffer
                async with buffer_lock:
                    extraction_buffer.append(result)
                    buffer_len = len(extraction_buffer)
                
                # Log progress
                logger.info(
                    f"✅ [{completed}/{total_chunks}] Chunk extracted",
                    chunk_id=result.chunk_id,
                    entities=len(result.entities),
                    relationships=len(result.relationships)
                )
                
                # Flush buffer when it reaches batch_size
                if buffer_len >= batch_size:
                    write_stats = await flush_buffer()
                    total_stats["entities_created"] += write_stats.get("entities_created", 0)
                    total_stats["relationships_created"] += write_stats.get("relationships_created", 0)
                    total_stats["extracted_from_created"] += write_stats.get("extracted_from_created", 0)
            
            # Flush any remaining results
            write_stats = await flush_buffer()
            total_stats["entities_created"] += write_stats.get("entities_created", 0)
            total_stats["relationships_created"] += write_stats.get("relationships_created", 0)
            total_stats["extracted_from_created"] += write_stats.get("extracted_from_created", 0)
            
            await extractor.close()
            
            summary = {
                "status": "success",
                "model": actual_model,
                "source_label": source_label,
                "nodes_processed": total_chunks,
                "batches_written": batches_written,
                "entities_extracted": total_stats["entities_extracted"],
                "entities_created": total_stats["entities_created"],
                "relationships_extracted": total_stats["relationships_extracted"],
                "relationships_created": total_stats["relationships_created"],
                "extracted_from_relationships": total_stats["extracted_from_created"],
                "entity_labels": list(total_stats["entity_labels"]),
                "message": f"Extracted {total_stats['entities_extracted']} entities from {total_chunks} {source_label} nodes. Created {total_stats['entities_created']} entity nodes with EXTRACTED_FROM provenance."
            }
            
            logger.info("Entity extraction completed", **summary)
            
            return json.dumps(summary, indent=2)
            
        except json.JSONDecodeError as e:
            raise ToolError(f"Invalid schema JSON: {e}")
        except Exception as e:
            logger.error("Failed to extract entities", error=str(e))
            raise ToolError(f"Failed to extract entities: {e}")
    
    # ========================================
    # TOOL 2: Convert Modeling Schema
    # ========================================
    
    @mcp.tool(
        name="convert_schema",
        annotations=ToolAnnotations(
            title="Convert Modeling Schema to Extraction Schema",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def convert_schema(
        modeling_output: str = Field(..., description="JSON output from the Data Modeling MCP server"),
        output_path: str = Field(..., description="Path to save the extraction schema JSON file")
    ) -> str:
        """
        Convert a data model from the Data Modeling MCP server to an extraction schema.
        
        This is a helper tool to bridge between the data modeling workflow and entity extraction.
        
        **Input:** JSON from Data Modeling MCP (nodes with labels, key_property, properties)
        **Output:** Writes extraction schema JSON to output_path for use with extract_entities_from_graph
        
        **Note:** This is a temporary tool - functionality may move to the Modeling MCP in the future.
        
        **Returns:** Summary with file path (not the schema content)
        """
        import pathlib
        
        try:
            modeling_data = json.loads(modeling_output)
            
            # Convert nodes to entity types
            entity_types = []
            for node in modeling_data.get("nodes", []):
                entity_type = {
                    "label": node.get("label"),
                    "description": node.get("key_property", {}).get("description", f"A {node.get('label')} entity"),
                    "key_property": node.get("key_property", {}).get("name"),
                    "properties": [
                        {
                            "name": prop.get("name"),
                            "type": prop.get("type", "STRING"),
                            "description": prop.get("description")
                        }
                        for prop in node.get("properties", [])
                    ]
                }
                entity_types.append(entity_type)
            
            # Convert relationships
            relationship_types = []
            for rel in modeling_data.get("relationships", []):
                rel_type = {
                    "type": rel.get("type"),
                    "description": f"Relationship from {rel.get('start_node_label')} to {rel.get('end_node_label')}",
                    "source_entity": rel.get("start_node_label"),
                    "target_entity": rel.get("end_node_label"),
                    "properties": [
                        {
                            "name": prop.get("name"),
                            "type": prop.get("type", "STRING"),
                            "description": prop.get("description")
                        }
                        for prop in rel.get("properties", [])
                    ]
                }
                relationship_types.append(rel_type)
            
            extraction_schema = {
                "entity_types": entity_types,
                "relationship_types": relationship_types
            }
            
            # Write schema JSON file
            output_file = pathlib.Path(output_path)
            output_file.parent.mkdir(parents=True, exist_ok=True)
            output_file.write_text(json.dumps(extraction_schema, indent=2))
            
            # Generate and write Pydantic model Python file
            from .schema_generator import generate_pydantic_code
            pydantic_code = generate_pydantic_code(extraction_schema)
            pydantic_path = output_file.with_suffix('.py')
            pydantic_path.write_text(pydantic_code)
            
            logger.info("Extraction schema and Pydantic model saved", 
                       schema_path=output_path,
                       pydantic_path=str(pydantic_path))
            
            return json.dumps({
                "status": "success",
                "schema_path": output_path,
                "pydantic_path": str(pydantic_path),
                "entity_types": len(entity_types),
                "relationship_types": len(relationship_types),
                "message": f"Extraction schema saved to {output_path}, Pydantic model saved to {pydantic_path}"
            }, indent=2)
            
        except json.JSONDecodeError as e:
            raise ToolError(f"Invalid modeling output JSON: {e}")
        except Exception as e:
            raise ToolError(f"Failed to convert schema: {e}")
    
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
        extraction_model=extraction_model
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
        extraction_model=extraction_model
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
