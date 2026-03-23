# mcp-neo4j-lexical-graph

MCP server for creating rich lexical graphs from PDF documents in Neo4j. Designed for Neo4j sales engineers to quickly build PDF-to-graph and GraphRAG agent chatbot POCs.

Supports four parsing strategies (PyMuPDF, Docling, page-image, VLM block ordering), pluggable chunking, document versioning, VLM-based description generation, and vector/fulltext search with Neo4j 2026.01 native VECTOR type and document-name prefiltering.

## Graph Model

```mermaid
graph LR
    Doc[Document] -->|HAS_PAGE| Page
    Doc -->|HAS_ELEMENT| Img[Image]
    Doc -->|HAS_ELEMENT| Tbl[Table]
    Doc -->|HAS_SECTION| Sec[Section]
    Sec -->|HAS_SUBSECTION| Sec
    Chunk -->|PART_OF| Doc
    Chunk -->|NEXT_CHUNK| Chunk
    Chunk -->|HAS_ELEMENT| Img
    Chunk -->|HAS_ELEMENT| Tbl
    Page -->|NEXT_PAGE| Page
```

Node types depend on the parse mode used. See [Parse Modes](#parse-modes) below.

## Parse Modes

| Mode | Nodes created | Best for |
|------|--------------|----------|
| `pymupdf` | Document, Chunk, Image, Table | General-purpose text + visual extraction |
| `docling` | Document, Page, Element, Section, (then Chunk via chunking tool) | Complex layouts, section-aware chunking |
| `page_image` | Document, Page | Slides/presentations for VLM-based extraction |
| `vlm_blocks` | Document, Page, Element, Section, (then Chunk via chunking tool) | **Experimental.** Complex layouts without docling dependency (uses VLM API). Prefer `docling` for production use. |

## Quick Start

```bash
cd mcp-neo4j-lexical-graph
uv sync
```

### Cursor MCP Configuration

Add to your `.cursor/mcp.json`:

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
        "NEO4J_PASSWORD": "your-password",
        "NEO4J_DATABASE": "neo4j",
        "EMBEDDING_MODEL": "text-embedding-3-small",
        "EXTRACTION_MODEL": "gpt-5-mini",
        "OPENAI_API_KEY": "sk-..."
      }
    }
  }
}
```

## Tools

Tools must be called in a specific order — which tools to call depends on the parse mode and document type. See the workflow table below.

### Workflow Order

| # | Tool | pymupdf | docling | page_image | vlm_blocks | Notes |
|---|------|---------|---------|------------|------------|-------|
| 1 | `create_lexical_graph` | ✓ | ✓ | ✓ | ✓ | Always first. Async — returns job_id. |
| 2 | `check_processing_status` | ✓ | ✓ | ✓ | ✓ | Poll until complete after any async op. |
| 3 | `cancel_job` | opt | opt | opt | opt | Only if aborting a running job. |
| 4 | `chunk_lexical_graph` | ✗ | ✓ | ✓ | ✓ | Required for docling/vlm_blocks/page_image. Integrated into create for pymupdf. |
| 5 | `list_documents` | ✓ | ✓ | ✓ | ✓ | Confirm ingestion, get document IDs. |
| 6 | `verify_lexical_graph` | opt | opt | ✗ never | opt | Single-doc spot-check only. Never for page_image (base64 flood). |
| 7 | `assign_section_hierarchy` | ✗ | opt | ✗ | opt | For structured docs with nested sections. Uses EXTRACTION_MODEL. |
| 8 | `generate_chunk_descriptions` | recommended¹ | recommended¹ | **required** | recommended¹ | VLM descriptions for Image/Table/Page nodes. Required before embed_chunks for page_image. |
| 9 | `embed_chunks` | ✓ | ✓ | ✓ | ✓ | Synchronous. Call with no parameters — auto-detects textDescription. |
| 10 | `set_active_version` | opt | opt | opt | opt | Only when re-ingesting a document. |
| 11 | `clean_inactive` | opt | opt | opt | opt | After set_active_version, to remove old versions. |
| 12 | `delete_document` | opt | opt | opt | opt | Destructive — removes document + all children. |

¹ Recommended when `extract_images=True` or `extract_tables=True` (pymupdf) or when the document contains images/tables (docling/vlm_blocks). Without descriptions, Image/Table nodes are invisible to semantic search.

### Tool Reference

| Tool | Description |
|------|-------------|
| `create_lexical_graph` | Parse PDF(s) and create the graph (async, returns job_id). `max_parallel=0` auto-detects worker count from RAM/CPU. |
| `check_processing_status` | Monitor background job progress |
| `cancel_job` | Cancel a running background job (optional cleanup of partial data) |
| `chunk_lexical_graph` | Create Chunk nodes from Elements (4 strategies: token_window, structured, by_section, by_page) |
| `list_documents` | Inventory of documents with version and chunk count info |
| `verify_lexical_graph` | Structural checks + Markdown reconstruction (single-doc only) |
| `assign_section_hierarchy` | LLM-based section level assignment + rebuilds HAS_SUBSECTION + updates sectionContext on chunks. Omit `document_id` to run all active documents in parallel. |
| `generate_chunk_descriptions` | VLM descriptions for Image/Table/Page nodes — stored as textDescription. `document_id` optional: omit to run for all active documents. |
| `embed_chunks` | Vector embeddings + fulltext index. Auto-detects textDescription for unified Table/Image/text embedding. |
| `set_active_version` | Activate a specific document/chunk version |
| `clean_inactive` | Delete inactive document versions and chunk sets |
| `delete_document` | Remove a document version with cascade (pages, elements, sections, chunks) |

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `NEO4J_URI` | Yes | `bolt://localhost:7687` | Neo4j connection URI |
| `NEO4J_USERNAME` | Yes | `neo4j` | Neo4j username |
| `NEO4J_PASSWORD` | Yes | - | Neo4j password |
| `NEO4J_DATABASE` | No | `neo4j` | Database name |
| `EMBEDDING_MODEL` | No | `text-embedding-3-small` | Default embedding model ([LiteLLM providers](https://docs.litellm.ai/docs/embedding/supported_embedding)) |
| `EXTRACTION_MODEL` | No | `gpt-5-mini` | LLM/VLM for section hierarchy and description generation |
| `OPENAI_API_KEY` | Depends | - | Required when using OpenAI models for embedding or extraction. Other providers use their own key (e.g. `ANTHROPIC_API_KEY`, `AZURE_API_KEY`). See [LiteLLM docs](https://docs.litellm.ai/docs/providers) |

## Requirements

- **Neo4j 2026.01+** (native VECTOR type, vector search with filters)
- **Python 3.10+**
- API key for your embedding provider (OpenAI, Azure, Cohere, Voyage, Ollama, etc.)
- API key for VLM if using `vlm_blocks` mode, `generate_chunk_descriptions`, or `assign_section_hierarchy`
