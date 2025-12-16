# mcp-neo4j-lexical-graph

**Status:** POC (Proof of Concept)

MCP server for creating lexical graphs from PDF documents in Neo4j.

## Overview

This server provides tools to:
1. **Extract text from PDFs** and split into token-based chunks
2. **Create a lexical graph** in Neo4j with Document and Chunk nodes
3. **Generate embeddings** for semantic search

## Graph Schema

```
(:Document {id, name, source, totalChunks, totalTokens})
    ↑
[:PART_OF]
    |
(:Chunk {id, text, index, embedding, tokenCount})
    |
[:NEXT] → (:Chunk) → [:NEXT] → ...
```

## Tools

### 1. `process_pdf_to_chunks`
Extract text from a PDF and split into overlapping chunks. Saves chunks to a JSON file.

**Parameters:**
- `pdf_path`: Path to the PDF file
- `document_id`: Unique identifier for the document
- `output_dir`: Directory to save the chunks JSON file
- `chunk_size`: Target chunk size in tokens (default: 500)
- `chunk_overlap`: Overlap between chunks (default: 50)

**Returns:** JSON with file path and summary (not the full chunks)

### 2. `create_lexical_graph`
Create Document and Chunk nodes in Neo4j from a chunks JSON file.

**Parameters:**
- `chunks_file`: Path to the chunks JSON file from `process_pdf_to_chunks`
- `document_name`: Human-readable name

**Creates:**
- Document node
- Chunk nodes
- `PART_OF` relationships
- `NEXT` relationships for sequence
- Constraints and vector index

### 3. `embed_chunks`
Add embeddings to Chunk nodes.

**Parameters:**
- `document_id`: (Optional) Embed only this document's chunks
- `parallel`: Concurrent embedding batches (default: 10)
- `model`: Embedding model (default: text-embedding-3-small)

## Installation

```bash
cd mcp-neo4j-lexical-graph
uv sync
```

## Configuration

Add to your `mcp.json`:

```json
{
  "mcpServers": {
    "neo4j-lexical-graph": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/mcp-neo4j-lexical-graph",
        "run",
        "mcp-neo4j-lexical-graph"
      ],
      "env": {
        "NEO4J_URI": "bolt://localhost:7687",
        "NEO4J_USERNAME": "neo4j",
        "NEO4J_PASSWORD": "password",
        "NEO4J_DATABASE": "neo4j",
        "EMBEDDING_MODEL": "text-embedding-3-small",
        "OPENAI_API_KEY": "sk-..."
      }
    }
  }
}
```

## Usage Example

```python
# 1. Process PDF to chunks (saved to file)
result = process_pdf_to_chunks(
    pdf_path="/path/to/document.pdf",
    document_id="doc_001",
    output_dir="/path/to/output"
)
# Returns: {"chunks_file": "/path/to/output/doc_001_chunks.json", ...}

# 2. Create lexical graph from chunks file
create_lexical_graph(
    chunks_file="/path/to/output/doc_001_chunks.json",
    document_name="My Document"
)

# 3. Add embeddings
embed_chunks(document_id="doc_001")
```

## Vector Search

After embedding, you can use the `chunk_text_embedding` vector index:

```cypher
CALL db.index.vector.queryNodes('chunk_text_embedding', 5, $embedding)
YIELD node, score
RETURN node.text, score
```

## Requirements

- Neo4j 5.11+ (for vector indexes)
- Neo4j 5.13+ (for `db.create.setNodeVectorProperty`)
- Python 3.10+
- OpenAI API key (for embeddings)
