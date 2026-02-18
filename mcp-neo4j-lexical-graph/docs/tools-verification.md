# Verification Tools

## verify_lexical_graph

Run structural checks and content reconstruction on a document's graph. Produces statistics, identifies anomalies, and reconstructs the document as Markdown for visual comparison with the original PDF.

### Checks Performed

- **Orphan nodes**: Nodes not connected to their expected parent
- **Broken NEXT chains**: Missing or incorrect `NEXT_ELEMENT` / `NEXT_PAGE` / `NEXT_CHUNK` links
- **Statistics**: Node counts by type, element type distribution, section counts, chunk token stats (min/max/avg/median)
- **Content reconstruction**: Rebuilds the document as Markdown from elements (reading order via `NEXT_ELEMENT`) or from chunks (reading order via `NEXT_CHUNK`)

### Output Files

The tool writes to `output_dir`:

- `{document_id}_verify.json` -- full verification report (statistics, anomalies, counts)
- `{document_id}_elements.md` -- Markdown reconstructed from elements in reading order (docling mode). Includes inline base64 images for Image/Table elements
- `{document_id}_chunks.md` -- Markdown reconstructed from the chunk chain
- `{document_id}_pages.md` -- Markdown reconstructed from pages (page_image mode). Includes page images and extracted text side-by-side

### Parameters

| Name | Required | Default | Description |
|------|----------|---------|-------------|
| `document_id` | Yes | - | Document version id to verify |
| `output_dir` | Yes | - | Directory to write reports |

### Example Output

```json
{
  "status": "success",
  "document_id": "doc_v1",
  "statistics": {
    "pages": 13,
    "elements": 142,
    "sections": 18,
    "chunks": 47,
    "element_types": {
      "paragraph": 98,
      "table": 12,
      "image": 8,
      "table_of_contents": 2
    },
    "chunk_tokens": {
      "min": 85,
      "max": 523,
      "avg": 412,
      "median": 445
    }
  },
  "anomalies": [],
  "files_written": [
    "doc_v1_verify.json",
    "doc_v1_elements.md",
    "doc_v1_chunks.md"
  ]
}
```
