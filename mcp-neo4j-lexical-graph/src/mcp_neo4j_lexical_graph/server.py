"""MCP server for creating lexical graphs from PDF documents.

Tools:
- process_pdf_to_chunks: Extract text from PDF and create chunks (single file)
- create_lexical_graph: Create Document and Chunk nodes in Neo4j (single file)
- create_lexical_graph_from_folder: Batch process folder of PDFs into Neo4j
- embed_chunks: Add embeddings to existing Chunk nodes
"""

import asyncio
import csv
import hashlib
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

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
        
        **Note:** Embeddings and vector index are added separately with embed_chunks tool.
        
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
        model: str = Field(default=embedding_model, description="Embedding model to use (via LiteLLM)"),
        node_label: str = Field(default="Chunk", description="Label of nodes to embed (e.g., 'Chunk', 'Page')"),
        id_property: Optional[str] = Field(default=None, description="Property name for node ID (e.g., 'id', 'chunk_id'). If not provided, uses elementId() for universal compatibility."),
        text_property: str = Field(default="text", description="Property name for text content to embed"),
        create_fulltext_index: bool = Field(default=True, description="Create a fulltext index on the text property for keyword search")
    ) -> str:
        """
        Add embeddings to nodes in Neo4j.
        
        This tool generates embeddings for nodes that don't have them yet
        and stores them efficiently using db.create.setNodeVectorProperty.
        
        Configure node_label, id_property, and text_property to work with any schema:
        - Default: Chunk nodes with 'id' and 'text' properties
        - Example: node_label="Chunk", id_property="chunk_id", text_property="text"
        
        If document_id is provided, only embeds chunks for that document.
        Otherwise, embeds all matching nodes without embeddings.
        
        Optionally creates a fulltext index on the text property for keyword search.
        
        **Progress:** Reports progress during embedding generation.
        
        **Returns:** Summary of embedded nodes
        """
        # Determine ID selection strategy
        use_element_id = id_property is None
        id_select = "elementId(c)" if use_element_id else f"c.{id_property}"
        
        # Embedding property name follows pattern: {text_property}_embedding
        embedding_property = f"{text_property}_embedding"
        
        logger.info(
            "Starting chunk embedding",
            document_id=document_id,
            model=model,
            parallel=parallel,
            node_label=node_label,
            id_property=id_property or "elementId()",
            text_property=text_property,
            embedding_property=embedding_property
        )
        
        try:
            # Build dynamic query based on parameters
            if document_id:
                query = f"""
                    MATCH (c:{node_label})-[:PART_OF]->(d:Document {{id: $documentId}})
                    WHERE c.{embedding_property} IS NULL AND c.{text_property} IS NOT NULL
                    RETURN {id_select} as id, c.{text_property} as text
                    ORDER BY c.index
                """
            else:
                query = f"""
                    MATCH (c:{node_label})
                    WHERE c.{embedding_property} IS NULL AND c.{text_property} IS NOT NULL
                    RETURN {id_select} as id, c.{text_property} as text
                """
            
            # Get nodes without embeddings
            async with neo4j_driver.session(database=database) as session:
                if document_id:
                    result = await session.run(query, documentId=document_id)
                else:
                    result = await session.run(query)
                
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
            # Build dynamic update query based on ID strategy
            if use_element_id:
                update_query = f"""
                    UNWIND $embeddings AS item
                    MATCH (c:{node_label}) WHERE elementId(c) = item.id
                    CALL db.create.setNodeVectorProperty(c, '{embedding_property}', item.embedding)
                    RETURN count(c) as updated
                """
            else:
                update_query = f"""
                    UNWIND $embeddings AS item
                    MATCH (c:{node_label} {{{id_property}: item.id}})
                    CALL db.create.setNodeVectorProperty(c, '{embedding_property}', item.embedding)
                    RETURN count(c) as updated
                """
            
            batch_size = 100
            total_updated = 0
            
            for i in range(0, len(embeddings_data), batch_size):
                batch = embeddings_data[i:i + batch_size]
                
                async with neo4j_driver.session(database=database) as session:
                    result = await session.run(update_query, embeddings=batch)
                    record = await result.single()
                    total_updated += record["updated"] if record else 0
                
                logger.debug(f"Updated embedding batch {i // batch_size + 1}")
            
            # Create vector index if embeddings were added
            # Get dimensions from first embedding
            vector_index_created = False
            fulltext_index_created = False
            
            if embeddings_data:
                dimensions = len(embeddings_data[0]["embedding"])
                vector_index_name = f"{node_label.lower()}_{text_property}_embedding"
                try:
                    index_query = f"""
                        CREATE VECTOR INDEX {vector_index_name} IF NOT EXISTS
                        FOR (c:{node_label}) ON (c.{embedding_property})
                        OPTIONS {{indexConfig: {{
                            `vector.dimensions`: $dimensions,
                            `vector.similarity_function`: 'cosine'
                        }}}}
                    """
                    async with neo4j_driver.session(database=database) as session:
                        await session.run(index_query, dimensions=dimensions)
                    vector_index_created = True
                    logger.info(f"Vector index '{vector_index_name}' created on {node_label}.{embedding_property} with {dimensions} dimensions")
                except Exception as e:
                    # Index might already exist with different config
                    logger.warning(f"Vector index note: {e}")
            
            # Create fulltext index if requested
            if create_fulltext_index:
                try:
                    fulltext_query = f"""
                        CREATE FULLTEXT INDEX {node_label.lower()}_{text_property}_fulltext IF NOT EXISTS
                        FOR (c:{node_label}) ON EACH [c.{text_property}]
                    """
                    async with neo4j_driver.session(database=database) as session:
                        await session.run(fulltext_query)
                    fulltext_index_created = True
                    logger.info(f"Fulltext index created for {node_label}.{text_property}")
                except Exception as e:
                    logger.warning(f"Fulltext index note: {e}")
            
            summary = {
                "status": "success",
                "document_id": document_id,
                "node_label": node_label,
                "id_property": id_property,
                "text_property": text_property,
                "embedding_property": embedding_property,
                "model": model,
                "nodes_processed": total_chunks,
                "nodes_embedded": total_updated,
                "vector_index_created": vector_index_created,
                "fulltext_index_created": fulltext_index_created,
                "message": f"Successfully embedded {total_updated} {node_label} nodes"
            }
            
            logger.info("Embedding completed", **summary)
            
            return json.dumps(summary, indent=2)
            
        except Exception as e:
            logger.error("Failed to embed chunks", error=str(e))
            raise ToolError(f"Failed to embed chunks: {e}")
    
    # ========================================
    # TOOL 4: Create Lexical Graph from Folder
    # ========================================
    
    @mcp.tool(
        name="create_lexical_graph_from_folder",
        annotations=ToolAnnotations(
            title="Create Lexical Graph from Folder",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    async def create_lexical_graph_from_folder(
        folder_path: str = Field(..., description="Path to folder containing PDF files"),
        output_dir: str = Field(..., description="Directory to save manifest and optionally chunk files"),
        metadata_csv: Optional[str] = Field(None, description="Optional: Path to CSV with document metadata"),
        filename_column: str = Field(default="filename", description="Column name in CSV for filename"),
        id_strategy: str = Field(default="filename", description="How to generate document IDs: 'filename', 'csv_column', or 'hash'"),
        id_column: Optional[str] = Field(None, description="If id_strategy='csv_column', which column to use for document ID"),
        chunk_size: int = Field(default=default_chunk_size, description="Target chunk size in tokens"),
        chunk_overlap: int = Field(default=default_chunk_overlap, description="Overlap between chunks in tokens"),
        parallel: int = Field(default=5, description="Number of PDFs to process in parallel"),
        skip_existing: bool = Field(default=False, description="Skip documents that already exist in DB instead of erroring"),
        save_chunks_to_disk: bool = Field(default=False, description="Save chunk JSON files to disk for debugging"),
    ) -> str:
        """
        Process a folder of PDFs and create lexical graph in Neo4j.
        
        This tool:
        - Scans folder for PDF files
        - Optionally reads metadata from CSV
        - Processes PDFs in parallel
        - Creates Document and Chunk nodes in Neo4j
        - Returns summary with path to detailed manifest
        
        **ID Strategy:**
        - 'filename': Use PDF filename (without extension) as document ID
        - 'csv_column': Use a column from metadata CSV as document ID
        - 'hash': Generate SHA256 hash from file content
        
        **Metadata CSV:** If provided, columns become Document node properties.
        PDFs not in CSV are processed with a warning. CSV entries without matching PDF are skipped with warning.
        
        **Returns:** JSON summary with path to manifest file containing details
        """
        logger.info(
            "Creating lexical graph from folder",
            folder_path=folder_path,
            metadata_csv=metadata_csv,
            id_strategy=id_strategy,
            parallel=parallel
        )
        
        folder = Path(folder_path)
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        
        if not folder.exists() or not folder.is_dir():
            raise ToolError(f"Folder not found: {folder_path}")
        
        # Find all PDF files
        pdf_files = list(folder.glob("*.pdf")) + list(folder.glob("*.PDF"))
        if not pdf_files:
            raise ToolError(f"No PDF files found in {folder_path}")
        
        logger.info(f"Found {len(pdf_files)} PDF files")
        
        # Load metadata CSV if provided
        metadata: Dict[str, Dict[str, Any]] = {}
        csv_files_not_found: List[str] = []
        
        if metadata_csv:
            csv_path = Path(metadata_csv)
            if not csv_path.exists():
                raise ToolError(f"Metadata CSV not found: {metadata_csv}")
            
            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                if filename_column not in reader.fieldnames:
                    raise ToolError(f"Column '{filename_column}' not found in CSV. Available: {reader.fieldnames}")
                
                for row in reader:
                    filename = row[filename_column]
                    metadata[filename] = {k: v for k, v in row.items() if k != filename_column}
            
            logger.info(f"Loaded metadata for {len(metadata)} files from CSV")
            
            # Check for CSV entries without matching PDFs
            pdf_names = {p.name for p in pdf_files}
            for csv_filename in metadata.keys():
                if csv_filename not in pdf_names:
                    csv_files_not_found.append(csv_filename)
        
        # Create constraints (idempotent)
        async with neo4j_driver.session(database=database) as session:
            await session.run(QUERIES["create_document_constraint"])
            await session.run(QUERIES["create_chunk_constraint"])
        
        # Check which documents already exist
        existing_doc_ids = set()
        async with neo4j_driver.session(database=database) as session:
            result = await session.run("MATCH (d:Document) RETURN d.id as id")
            records = await result.data()
            existing_doc_ids = {r["id"] for r in records}
        
        # Prepare processing tasks
        results: List[Dict[str, Any]] = []
        warnings: List[str] = []
        pdfs_not_in_csv: List[str] = []
        
        # Add warnings for CSV files not found
        for csv_file in csv_files_not_found:
            warnings.append(f"CSV entry '{csv_file}' has no matching PDF in folder - skipped")
        
        # Helper to generate document ID
        def get_document_id(pdf_path: Path) -> str:
            if id_strategy == "filename":
                return pdf_path.stem
            elif id_strategy == "hash":
                with open(pdf_path, 'rb') as f:
                    return hashlib.sha256(f.read()).hexdigest()[:16]
            elif id_strategy == "csv_column":
                if not id_column:
                    raise ToolError("id_column required when id_strategy='csv_column'")
                file_meta = metadata.get(pdf_path.name, {})
                if id_column not in file_meta:
                    raise ToolError(f"Column '{id_column}' not found in metadata for {pdf_path.name}")
                return str(file_meta[id_column])
            else:
                raise ToolError(f"Unknown id_strategy: {id_strategy}")
        
        # Helper to process a single PDF
        async def process_single_pdf(pdf_path: Path) -> Dict[str, Any]:
            doc_id = get_document_id(pdf_path)
            file_metadata = metadata.get(pdf_path.name, {})
            
            # Track if PDF is not in CSV
            if metadata_csv and pdf_path.name not in metadata:
                pdfs_not_in_csv.append(pdf_path.name)
            
            # Check if document already exists
            if doc_id in existing_doc_ids:
                if skip_existing:
                    return {
                        "status": "skipped",
                        "document_id": doc_id,
                        "filename": pdf_path.name,
                        "reason": "Document already exists"
                    }
                else:
                    return {
                        "status": "error",
                        "document_id": doc_id,
                        "filename": pdf_path.name,
                        "error": f"Document '{doc_id}' already exists in database"
                    }
            
            try:
                # Process PDF to chunks
                chunker = PDFChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
                chunk_result = chunker.process_pdf(str(pdf_path), doc_id)
                
                # Optionally save chunks to disk
                if save_chunks_to_disk:
                    chunks_file = output / f"{doc_id}_chunks.json"
                    with open(chunks_file, 'w', encoding='utf-8') as f:
                        f.write(chunk_result.to_json())
                
                # Create Document node with metadata
                doc_name = file_metadata.get("title", pdf_path.stem)
                
                async with neo4j_driver.session(database=database) as session:
                    # Build dynamic SET clause for metadata
                    set_clauses = ["d.name = $name", "d.source = $source", 
                                   "d.totalChunks = $totalChunks", "d.totalTokens = $totalTokens"]
                    params = {
                        "id": doc_id,
                        "name": doc_name,
                        "source": str(pdf_path),
                        "totalChunks": len(chunk_result.chunks),
                        "totalTokens": chunk_result.total_tokens
                    }
                    
                    # Add metadata properties
                    for key, value in file_metadata.items():
                        safe_key = key.replace(" ", "_").replace("-", "_")
                        set_clauses.append(f"d.{safe_key} = ${safe_key}")
                        params[safe_key] = value
                    
                    query = f"""
                        MERGE (d:Document {{id: $id}})
                        SET {', '.join(set_clauses)}
                        RETURN d
                    """
                    await session.run(query, **params)
                
                # Create Chunk nodes in batches
                chunks_created = 0
                batch_size = 100
                
                for i in range(0, len(chunk_result.chunks), batch_size):
                    batch = chunk_result.chunks[i:i + batch_size]
                    neo4j_chunks = [
                        {
                            "id": c.id,
                            "text": c.text,
                            "index": c.index,
                            "startChar": c.start_char,
                            "endChar": c.end_char,
                            "tokenCount": c.token_count,
                        }
                        for c in batch
                    ]
                    
                    async with neo4j_driver.session(database=database) as session:
                        result = await session.run(
                            QUERIES["create_chunks_batch"],
                            chunks=neo4j_chunks,
                            documentId=doc_id
                        )
                        record = await result.single()
                        chunks_created += record["created"] if record else 0
                
                # Create NEXT relationships
                async with neo4j_driver.session(database=database) as session:
                    result = await session.run(
                        QUERIES["create_next_relationships"],
                        documentId=doc_id
                    )
                    record = await result.single()
                    next_rels = record["relationships"] if record else 0
                
                return {
                    "status": "success",
                    "document_id": doc_id,
                    "filename": pdf_path.name,
                    "chunks_created": chunks_created,
                    "next_relationships": next_rels,
                    "total_tokens": chunk_result.total_tokens,
                    "metadata_applied": bool(file_metadata)
                }
                
            except Exception as e:
                logger.error(f"Failed to process {pdf_path.name}", error=str(e))
                return {
                    "status": "error",
                    "document_id": doc_id,
                    "filename": pdf_path.name,
                    "error": str(e)
                }
        
        # Process PDFs in parallel with semaphore
        semaphore = asyncio.Semaphore(parallel)
        
        async def process_with_semaphore(pdf_path: Path) -> Dict[str, Any]:
            async with semaphore:
                return await process_single_pdf(pdf_path)
        
        # Run all tasks
        tasks = [process_with_semaphore(pdf) for pdf in pdf_files]
        results = await asyncio.gather(*tasks)
        
        # Add warnings for PDFs not in CSV
        for pdf_name in pdfs_not_in_csv:
            warnings.append(f"PDF '{pdf_name}' not found in metadata CSV - processed without metadata")
        
        # Compute summary
        successful = [r for r in results if r["status"] == "success"]
        skipped = [r for r in results if r["status"] == "skipped"]
        errors = [r for r in results if r["status"] == "error"]
        
        total_chunks = sum(r.get("chunks_created", 0) for r in successful)
        total_tokens = sum(r.get("total_tokens", 0) for r in successful)
        
        # Write manifest file
        manifest = {
            "timestamp": datetime.now().isoformat(),
            "folder_path": str(folder_path),
            "metadata_csv": metadata_csv,
            "id_strategy": id_strategy,
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
            "summary": {
                "total_pdfs": len(pdf_files),
                "successful": len(successful),
                "skipped": len(skipped),
                "errors": len(errors),
                "total_chunks": total_chunks,
                "total_tokens": total_tokens
            },
            "warnings": warnings,
            "results": results
        }
        
        manifest_path = output / "manifest.json"
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2)
        
        # Build summary response
        summary = {
            "status": "success" if not errors else "partial_success" if successful else "failed",
            "documents_processed": len(successful),
            "documents_skipped": len(skipped),
            "documents_failed": len(errors),
            "total_chunks": total_chunks,
            "total_tokens": total_tokens,
            "manifest_file": str(manifest_path),
            "warnings": warnings if warnings else None,
            "errors": [{"filename": e["filename"], "error": e["error"]} for e in errors] if errors else None,
            "message": f"Processed {len(successful)}/{len(pdf_files)} PDFs. Details in {manifest_path}"
        }
        
        # Remove None values
        summary = {k: v for k, v in summary.items() if v is not None}
        
        logger.info("Folder processing completed", **summary)
        
        return json.dumps(summary, indent=2)
    
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

