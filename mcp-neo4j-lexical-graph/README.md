# mcp-neo4j-lexical-graph

**Status:** POC (Proof of Concept)

MCP server for creating lexical graphs from PDF documents in Neo4j.

## Overview

This server provides tools to:
1. **Extract text from PDFs** and split into token-based chunks
2. **Create a lexical graph** in Neo4j with Document and Chunk nodes
3. **Batch process folders** of PDFs with optional metadata
4. **Generate embeddings** for semantic search (via LiteLLM - 100+ providers)
5. **Create fulltext indexes** for keyword search

## Graph Schema

```
(:Document {id, name, source, totalChunks, totalTokens, ...metadata})
    ↑
[:PART_OF]
    |
(:Chunk {id, text, index, text_embedding, tokenCount})
    |
[:NEXT] → (:Chunk) → [:NEXT] → ...
```

## Tools

### 1. `process_pdf_to_chunks`
Extract text from a PDF and split into overlapping chunks. Saves chunks to a JSON file.

**Parameters:**
| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `pdf_path` | Yes | - | Path to the PDF file |
| `document_id` | Yes | - | Unique identifier for the document |
| `output_dir` | Yes | - | Directory to save the chunks JSON file |
| `chunk_size` | No | 500 | Target chunk size in tokens |
| `chunk_overlap` | No | 50 | Overlap between chunks in tokens |

**Returns:** JSON with file path and summary (not the full chunks)

---

### 2. `create_lexical_graph`
Create Document and Chunk nodes in Neo4j from a chunks JSON file.

**Parameters:**
| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `chunks_file` | Yes | - | Path to chunks JSON file from `process_pdf_to_chunks` |
| `document_name` | Yes | - | Human-readable document name |

**Creates:**
- Document node with metadata
- Chunk nodes with text
- `PART_OF` relationships
- `NEXT` relationships for sequence
- Constraints on Document.id and Chunk.id

---

### 3. `create_lexical_graph_from_folder`
Batch process a folder of PDFs into Neo4j.

**Parameters:**
| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `folder_path` | Yes | - | Path to folder containing PDF files |
| `output_dir` | Yes | - | Directory to save manifest file |
| `metadata_csv` | No | None | Path to CSV with document metadata |
| `filename_column` | No | "filename" | Column name in CSV for filename |
| `id_strategy` | No | "filename" | How to generate IDs: "filename", "csv_column", or "hash" |
| `id_column` | No | None | Column for ID when id_strategy="csv_column" |
| `chunk_size` | No | 500 | Target chunk size in tokens |
| `chunk_overlap` | No | 50 | Overlap between chunks |
| `parallel` | No | 5 | Number of PDFs to process concurrently |
| `skip_existing` | No | False | Skip documents that already exist in DB |
| `save_chunks_to_disk` | No | False | Save chunk JSON files for debugging |

**Returns:** Summary with path to `manifest.json` containing full details

**Metadata CSV Example:**
```csv
filename,title,author,year
report.pdf,Annual Report,John Doe,2024
study.pdf,Clinical Study,Jane Smith,2023
```

---

### 4. `embed_chunks`
Add embeddings to nodes in Neo4j. Creates vector index and fulltext index.

**Parameters:**
| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `document_id` | No | None | Embed only this document's chunks |
| `parallel` | No | 10 | Concurrent embedding batches |
| `model` | No | text-embedding-3-small | Embedding model (see Embedding Providers) |
| `node_label` | No | "Chunk" | Label of nodes to embed |
| `id_property` | No | None | Property for node ID (None = use elementId()) |
| `text_property` | No | "text" | Property containing text to embed |
| `create_fulltext_index` | No | True | Create fulltext index for keyword search |

**Naming Convention:**
| Element | Pattern | Example |
|---------|---------|---------|
| Embedding property | `{text_property}_embedding` | `text_embedding` |
| Vector index | `{label}_{text_property}_embedding` | `chunk_text_embedding` |
| Fulltext index | `{label}_{text_property}_fulltext` | `chunk_text_fulltext` |

---

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

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `NEO4J_URI` | Yes | bolt://localhost:7687 | Neo4j connection URI |
| `NEO4J_USERNAME` | Yes | neo4j | Neo4j username |
| `NEO4J_PASSWORD` | Yes | password | Neo4j password |
| `NEO4J_DATABASE` | No | neo4j | Database name |
| `EMBEDDING_MODEL` | No | text-embedding-3-small | Default embedding model |

---

## Embedding Providers

This server uses [LiteLLM](https://docs.litellm.ai/docs/embedding/supported_embedding) for embeddings, supporting 100+ providers.

Set `EMBEDDING_MODEL` in your config and the corresponding API key:

| Provider | Model Format | API Key Variable |
|----------|--------------|------------------|
| OpenAI | `text-embedding-3-small`, `text-embedding-3-large`, `text-embedding-ada-002` | `OPENAI_API_KEY` |
| Azure | `azure/deployment-name` | `AZURE_API_KEY`, `AZURE_API_BASE` |
| Bedrock | `bedrock/amazon.titan-embed-text-v1` | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` |
| Cohere | `cohere/embed-english-v3.0` | `COHERE_API_KEY` |
| Voyage | `voyage/voyage-2` | `VOYAGE_API_KEY` |
| Ollama | `ollama/nomic-embed-text` | _(none - local)_ |

### Override Model at Runtime

You can override the default model when calling `embed_chunks`:

```python
# Use a different model for this call
embed_chunks(model="cohere/embed-english-v3.0")

# Or use a local Ollama model
embed_chunks(model="ollama/nomic-embed-text")
```

---

## Usage Examples

### Single PDF Processing

```python
# 1. Process PDF to chunks (saved to file)
result = process_pdf_to_chunks(
    pdf_path="/path/to/document.pdf",
    document_id="doc_001",
    output_dir="/path/to/output"
)

# 2. Create lexical graph
create_lexical_graph(
    chunks_file="/path/to/output/doc_001_chunks.json",
    document_name="My Document"
)

# 3. Add embeddings + create indexes
embed_chunks(document_id="doc_001")
```

### Batch Folder Processing

```python
# Process entire folder in one call
create_lexical_graph_from_folder(
    folder_path="/path/to/pdfs",
    output_dir="/path/to/output",
    metadata_csv="/path/to/metadata.csv",  # optional
    parallel=5
)

# Add embeddings to all chunks (creates both vector + fulltext indexes)
embed_chunks()
```

### Flexible Schema Support

```python
# Embed any node type with any text property
embed_chunks(
    node_label="Page",
    text_property="content",
    id_property="page_id"  # or None to use elementId()
)
# Creates: Page.content_embedding property
# Creates: page_content_embedding vector index
```

---

## Requirements

- Neo4j 5.13+ (for `db.create.setNodeVectorProperty`)
- Python 3.10+
- API key for your chosen embedding provider
