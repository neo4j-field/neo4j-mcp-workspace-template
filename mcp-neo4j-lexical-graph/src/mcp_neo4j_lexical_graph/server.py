"""MCP server for creating lexical graphs from PDF documents.

Tools:
- process_pdf_to_chunks: Extract text from PDF and create chunks
- create_lexical_graph: Create Document and Chunk nodes in Neo4j
- embed_chunks: Add embeddings to existing Chunk nodes
"""

import asyncio
import json
import logging
import os
import sys
from typing import Any, Literal, Optional

import structlog
from fastmcp import FastMCP

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
from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from neo4j import AsyncGraphDatabase, AsyncDriver
from pydantic import Field

from .chunker import PDFChunker
from .embedder import ChunkEmbedder
from .models import Chunk, ChunkingResult, Document, ProgressUpdate

logger = structlog.get_logger()

# Cypher queries for lexical graph operations
QUERIES = {
    # Constraints
    "create_document_constraint": """
        CREATE CONSTRAINT document_id IF NOT EXISTS
        FOR (d:Document) REQUIRE d.id IS UNIQUE
    """,
    "create_chunk_constraint": """
        CREATE CONSTRAINT chunk_id IF NOT EXISTS
        FOR (c:Chunk) REQUIRE c.id IS UNIQUE
    """,
    
    # Vector index (Neo4j 5.11+)
    # Using 1536 dimensions for text-embedding-3-small
    "create_vector_index": """
        CREATE VECTOR INDEX chunk_text_embedding IF NOT EXISTS
        FOR (c:Chunk) ON (c.embedding)
        OPTIONS {indexConfig: {
            `vector.dimensions`: $dimensions,
            `vector.similarity_function`: 'cosine'
        }}
    """,
    
    # Node creation
    "create_document": """
        MERGE (d:Document {id: $id})
        SET d.name = $name,
            d.source = $source,
            d.totalChunks = $totalChunks,
            d.totalTokens = $totalTokens
        RETURN d
    """,
    
    "create_chunks_batch": """
        UNWIND $chunks AS chunk
        MERGE (c:Chunk {id: chunk.id})
        SET c.text = chunk.text,
            c.index = chunk.index,
            c.startChar = chunk.startChar,
            c.endChar = chunk.endChar,
            c.tokenCount = chunk.tokenCount
        WITH c, chunk
        MATCH (d:Document {id: $documentId})
        MERGE (c)-[:PART_OF]->(d)
        RETURN count(c) as created
    """,
    
    # NEXT relationships for chunk sequence
    "create_next_relationships": """
        MATCH (d:Document {id: $documentId})<-[:PART_OF]-(c:Chunk)
        WITH c ORDER BY c.index
        WITH collect(c) AS chunks
        UNWIND range(0, size(chunks)-2) AS i
        WITH chunks[i] AS current, chunks[i+1] AS next
        MERGE (current)-[:NEXT]->(next)
        RETURN count(*) as relationships
    """,
    
    # Embedding update using db.create.setNodeVectorProperty (Neo4j 5.13+)
    "update_chunk_embeddings": """
        UNWIND $embeddings AS item
        MATCH (c:Chunk {id: item.id})
        CALL db.create.setNodeVectorProperty(c, 'embedding', item.embedding)
        RETURN count(c) as updated
    """,
    
    # Query chunks without embeddings
    "get_chunks_without_embeddings": """
        MATCH (c:Chunk)
        WHERE c.embedding IS NULL
        RETURN c.id as id, c.text as text
        ORDER BY c.id
    """,
    
    # Query chunks by document
    "get_chunks_by_document": """
        MATCH (c:Chunk)-[:PART_OF]->(d:Document {id: $documentId})
        WHERE c.embedding IS NULL
        RETURN c.id as id, c.text as text
        ORDER BY c.index
    """,
    
    # Get embedding dimensions from existing chunks
    "get_embedding_dimensions": """
        MATCH (c:Chunk)
        WHERE c.embedding IS NOT NULL
        RETURN size(c.embedding) as dimensions
        LIMIT 1
    """
}


def create_mcp_server(
    neo4j_driver: AsyncDriver,
    database: str = "neo4j",
    embedding_model: str = "text-embedding-3-small",
    default_chunk_size: int = 500,
    default_chunk_overlap: int = 50
) -> FastMCP:
    """Create the lexical graph MCP server with all tools."""
    
    mcp = FastMCP("mcp-neo4j-lexical-graph")
    
    # ========================================
    # TOOL 1: Process PDF to Chunks
    # ========================================
    
    @mcp.tool(
        name="process_pdf_to_chunks",
        annotations=ToolAnnotations(
            title="Process PDF to Chunks",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def process_pdf_to_chunks(
        pdf_path: str = Field(..., description="Path to the PDF file to process"),
        document_id: str = Field(..., description="Unique identifier for the document"),
        output_dir: str = Field(..., description="Directory to save the chunks JSON file"),
        chunk_size: int = Field(default=default_chunk_size, description="Target chunk size in tokens"),
        chunk_overlap: int = Field(default=default_chunk_overlap, description="Overlap between chunks in tokens")
    ) -> str:
        """
        Extract text from a PDF and split into chunks.
        
        This tool processes a PDF file using PyMuPDF and splits the text into
        overlapping chunks based on token count. The chunks are saved to a JSON
        file in the specified output directory.
        
        **Returns:** JSON with file path and summary (not the full chunks)
        """
        logger.info(
            "Processing PDF to chunks",
            pdf_path=pdf_path,
            document_id=document_id,
            output_dir=output_dir,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap
        )
        
        try:
            # Create output directory if needed
            output_path = os.path.join(output_dir, f"{document_id}_chunks.json")
            os.makedirs(output_dir, exist_ok=True)
            
            chunker = PDFChunker(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap
            )
            result = chunker.process_pdf(pdf_path, document_id)
            
            # Write chunks to file
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(result.to_json())
            
            logger.info(f"Chunks saved to {output_path}")
            
            # Return summary (not the full chunks)
            summary = {
                "status": "success",
                "chunks_file": output_path,
                "document_id": result.document_id,
                "source_path": result.source_path,
                "total_pages": result.total_pages,
                "total_chunks": len(result.chunks),
                "total_tokens": result.total_tokens,
                "message": f"Processed {len(result.chunks)} chunks. Use create_lexical_graph with chunks_file={output_path}"
            }
            
            return json.dumps(summary, indent=2)
            
        except FileNotFoundError as e:
            raise ToolError(f"PDF file not found: {pdf_path}")
        except Exception as e:
            logger.error("Failed to process PDF", error=str(e))
            raise ToolError(f"Failed to process PDF: {e}")
    
    # ========================================
    # TOOL 2: Create Lexical Graph
    # ========================================
    
    @mcp.tool(
        name="create_lexical_graph",
        annotations=ToolAnnotations(
            title="Create Lexical Graph",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def create_lexical_graph(
        chunks_file: str = Field(..., description="Path to the chunks JSON file from process_pdf_to_chunks"),
        document_name: str = Field(..., description="Human-readable document name")
    ) -> str:
        """
        Create Document and Chunk nodes in Neo4j from processed chunks.
        
        This tool creates the lexical graph structure:
        - Document node with metadata
        - Chunk nodes with text content
        - (Chunk)-[:PART_OF]->(Document) relationships
        - (Chunk)-[:NEXT]->(Chunk) relationships for sequence
        - Constraints on Document.id and Chunk.id
        - Vector index for future embeddings
        
        **Note:** Embeddings are added separately with embed_chunks tool.
        
        **Returns:** Summary of created nodes and relationships
        """
        logger.info(
            "Creating lexical graph",
            chunks_file=chunks_file,
            document_name=document_name
        )
        
        try:
            # Read chunks from file
            with open(chunks_file, 'r', encoding='utf-8') as f:
                chunks_data = json.load(f)
            
            # Extract metadata from chunks file
            document_id = chunks_data.get("document_id")
            source_path = chunks_data.get("source_path", "")
            
            if not document_id:
                raise ToolError("chunks_file must contain document_id")
            
            # Handle both ChunkingResult format and direct chunk list
            if "chunks" in chunks_data:
                chunks_list = chunks_data["chunks"]
                total_tokens = chunks_data.get("total_tokens", 0)
            else:
                chunks_list = chunks_data
                total_tokens = sum(c.get("token_count", 0) for c in chunks_list)
            
            total_chunks = len(chunks_list)
            
            logger.info(f"Loaded {total_chunks} chunks for document {document_id}")
            
            # Create constraints (idempotent)
            async with neo4j_driver.session(database=database) as session:
                await session.run(QUERIES["create_document_constraint"])
                await session.run(QUERIES["create_chunk_constraint"])
                logger.debug("Constraints created/verified")
            
            # Create Document node
            async with neo4j_driver.session(database=database) as session:
                await session.run(
                    QUERIES["create_document"],
                    id=document_id,
                    name=document_name,
                    source=source_path,
                    totalChunks=total_chunks,
                    totalTokens=total_tokens
                )
                logger.debug("Document node created", document_id=document_id)
            
            # Create Chunk nodes in batches
            batch_size = 100
            chunks_created = 0
            
            for i in range(0, total_chunks, batch_size):
                batch = chunks_list[i:i + batch_size]
                
                # Convert to Neo4j format
                neo4j_chunks = []
                for chunk in batch:
                    neo4j_chunks.append({
                        "id": chunk.get("id"),
                        "text": chunk.get("text"),
                        "index": chunk.get("index"),
                        "startChar": chunk.get("start_char"),
                        "endChar": chunk.get("end_char"),
                        "tokenCount": chunk.get("token_count"),
                    })
                
                async with neo4j_driver.session(database=database) as session:
                    result = await session.run(
                        QUERIES["create_chunks_batch"],
                        chunks=neo4j_chunks,
                        documentId=document_id
                    )
                    record = await result.single()
                    chunks_created += record["created"] if record else 0
                
                logger.debug(f"Created chunk batch {i // batch_size + 1}")
            
            # Create NEXT relationships
            async with neo4j_driver.session(database=database) as session:
                result = await session.run(
                    QUERIES["create_next_relationships"],
                    documentId=document_id
                )
                record = await result.single()
                next_rels = record["relationships"] if record else 0
            
            # Create vector index (will be used after embedding)
            # Default to 1536 dimensions for text-embedding-3-small
            try:
                async with neo4j_driver.session(database=database) as session:
                    await session.run(
                        QUERIES["create_vector_index"],
                        dimensions=1536
                    )
                    logger.debug("Vector index created/verified")
            except Exception as e:
                # Index might already exist with different config
                logger.warning(f"Vector index creation note: {e}")
            
            summary = {
                "status": "success",
                "document_id": document_id,
                "document_name": document_name,
                "chunks_created": chunks_created,
                "next_relationships": next_rels,
                "total_tokens": total_tokens,
                "message": f"Created lexical graph with {chunks_created} chunks. Use embed_chunks to add embeddings."
            }
            
            logger.info(
                "Lexical graph created",
                **summary
            )
            
            return json.dumps(summary, indent=2)
            
        except FileNotFoundError:
            raise ToolError(f"Chunks file not found: {chunks_file}")
        except json.JSONDecodeError as e:
            raise ToolError(f"Invalid JSON in chunks file: {e}")
        except Exception as e:
            logger.error("Failed to create lexical graph", error=str(e))
            raise ToolError(f"Failed to create lexical graph: {e}")
    
    # ========================================
    # TOOL 3: Embed Chunks
    # ========================================
    
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
        document_id: Optional[str] = Field(None, description="Document ID to embed chunks for. If not provided, embeds all chunks without embeddings."),
        parallel: int = Field(default=10, description="Maximum concurrent embedding batches"),
        model: str = Field(default=embedding_model, description="Embedding model to use (via LiteLLM)")
    ) -> str:
        """
        Add embeddings to Chunk nodes in Neo4j.
        
        This tool generates embeddings for chunks that don't have them yet
        and stores them efficiently using db.create.setNodeVectorProperty.
        
        If document_id is provided, only embeds chunks for that document.
        Otherwise, embeds all chunks without embeddings.
        
        **Progress:** Reports progress during embedding generation.
        
        **Returns:** Summary of embedded chunks
        """
        logger.info(
            "Starting chunk embedding",
            document_id=document_id,
            model=model,
            parallel=parallel
        )
        
        try:
            # Get chunks without embeddings
            async with neo4j_driver.session(database=database) as session:
                if document_id:
                    result = await session.run(
                        QUERIES["get_chunks_by_document"],
                        documentId=document_id
                    )
                else:
                    result = await session.run(QUERIES["get_chunks_without_embeddings"])
                
                records = await result.data()
            
            if not records:
                return json.dumps({
                    "status": "success",
                    "message": "No chunks need embedding",
                    "embedded": 0
                })
            
            total_chunks = len(records)
            logger.info(f"Found {total_chunks} chunks to embed")
            
            # Create chunk objects for embedding
            chunks = [
                Chunk(
                    id=r["id"],
                    text=r["text"],
                    index=0,  # Not used for embedding
                    start_char=0,
                    end_char=0,
                    token_count=0
                )
                for r in records
            ]
            
            # Progress tracking
            progress_messages = []
            
            def on_progress(update: ProgressUpdate):
                progress_messages.append(update.message)
                logger.info(update.message)
            
            # Generate embeddings
            embedder = ChunkEmbedder(model=model)
            embedded_chunks = await embedder.embed_chunks(
                chunks,
                parallel=parallel,
                progress_callback=on_progress
            )
            
            # Prepare embeddings for Neo4j
            embeddings_data = [
                {"id": c.id, "embedding": c.embedding}
                for c in embedded_chunks
                if c.embedding is not None
            ]
            
            # Write embeddings to Neo4j in batches
            batch_size = 100
            total_updated = 0
            
            for i in range(0, len(embeddings_data), batch_size):
                batch = embeddings_data[i:i + batch_size]
                
                async with neo4j_driver.session(database=database) as session:
                    result = await session.run(
                        QUERIES["update_chunk_embeddings"],
                        embeddings=batch
                    )
                    record = await result.single()
                    total_updated += record["updated"] if record else 0
                
                logger.debug(f"Updated embedding batch {i // batch_size + 1}")
            
            summary = {
                "status": "success",
                "document_id": document_id,
                "model": model,
                "chunks_processed": total_chunks,
                "chunks_embedded": total_updated,
                "message": f"Successfully embedded {total_updated} chunks"
            }
            
            logger.info("Chunk embedding completed", **summary)
            
            return json.dumps(summary, indent=2)
            
        except Exception as e:
            logger.error("Failed to embed chunks", error=str(e))
            raise ToolError(f"Failed to embed chunks: {e}")
    
    return mcp


async def main(
    db_url: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    database: str = "neo4j",
    embedding_model: str = "text-embedding-3-small",
    transport: Literal["stdio", "sse"] = "stdio",
    host: str = "127.0.0.1",
    port: int = 8001,
) -> None:
    """Main entry point for the MCP server."""
    
    # Get config from environment or parameters
    db_url = db_url or os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    username = username or os.environ.get("NEO4J_USERNAME", "neo4j")
    password = password or os.environ.get("NEO4J_PASSWORD", "password")
    database = database or os.environ.get("NEO4J_DATABASE", "neo4j")
    embedding_model = embedding_model or os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
    
    logger.info(
        "Starting MCP Neo4j Lexical Graph Server",
        db_url=db_url,
        database=database,
        embedding_model=embedding_model
    )
    
    # Create Neo4j driver
    neo4j_driver = AsyncGraphDatabase.driver(db_url, auth=(username, password))
    
    # Verify connection
    try:
        async with neo4j_driver.session(database=database) as session:
            await session.run("RETURN 1")
        logger.info("Neo4j connection verified")
    except Exception as e:
        logger.error(f"Failed to connect to Neo4j: {e}")
        raise
    
    # Create MCP server
    mcp = create_mcp_server(
        neo4j_driver=neo4j_driver,
        database=database,
        embedding_model=embedding_model
    )
    
    # Run server
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

