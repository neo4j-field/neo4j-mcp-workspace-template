# Chunking Tools

## chunk_lexical_graph

Create Chunk nodes from Elements in the Neo4j graph. Reads Elements and Sections from Neo4j (not from any external file). Supports chunk versioning: multiple chunk sets can coexist for the same document.

Only applies to documents created in `docling` mode. Documents created in `pymupdf` mode already have chunks from graph creation. Documents in `page_image` mode have no elements to chunk.

### Parameters

| Name | Required | Default | Description |
|------|----------|---------|-------------|
| `document_id` | No | `null` | Document version id to chunk. If `null`, chunks all active documents without chunks |
| `strategy` | No | `"token_window"` | Chunking strategy (see below) |
| `chunk_size` | No | `500` | Target tokens per chunk |
| `chunk_overlap` | No | `50` | Token overlap (`token_window` strategy only) |
| `include_tables_as_chunks` | No | `true` | Create separate chunks for table elements |
| `include_images_as_chunks` | No | `true` | Create separate chunks for image/chart elements |
| `clear_existing_chunks` | No | `false` | If `true`, delete ALL existing chunk sets. If `false`, keep previous sets as inactive |
| `prepend_section_heading` | No | `true` | Add section title to chunk text |

### Strategies

| Strategy | Description |
|----------|-------------|
| `token_window` | Simple sliding window. No structure awareness |
| `structured` | Section + token aware. Merges elements in reading order respecting element boundaries. Headings are never the last element in a chunk. Only triggers a new chunk if the current chunk is at least half the target size |
| `by_section` | One chunk per section (falls back to `by_page` if no sections) |
| `by_page` | One chunk per page |

### Chunk Properties

Each chunk node carries:

- `text` -- the chunk content (original extracted text)
- `documentName` -- source document name (for prefiltering)
- `sectionHeading` -- the immediately preceding heading
- `sectionContext` -- full heading chain when `assign_section_hierarchy` has been run (e.g., `"Chapter 1 > Section 1.1 > Sub 1.1.1"`)
- `tokenCount` -- approximate token count
- `chunkSetVersion` -- version number for this chunk set
- `active` -- whether this chunk set is the active one

### Example Output

```json
{
  "status": "success",
  "results": [
    {
      "document_id": "doc_v1",
      "chunks_created": 47,
      "chunk_set_version": 1,
      "strategy": "structured",
      "token_stats": {
        "min": 85,
        "max": 523,
        "avg": 412,
        "median": 445
      }
    }
  ]
}
```
