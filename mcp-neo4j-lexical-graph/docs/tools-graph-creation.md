# Graph Creation Tools

## create_lexical_graph

Parse PDF(s) and create the lexical graph in Neo4j. Supports document versioning -- if a document with the same sourceId already exists, a new version is created and the old one is deactivated.

Returns immediately with a `job_id`. Use `check_processing_status(job_id)` to monitor.

### Parameters

| Name | Required | Default | Description |
|------|----------|---------|-------------|
| `path` | Yes | - | Path to a PDF file or a folder of PDFs |
| `output_dir` | Yes | - | Directory for logs and manifests |
| `document_id` | No | filename | Custom sourceId. Ignored for folders |
| `parse_mode` | No | `"pymupdf"` | `"pymupdf"`, `"docling"`, `"page_image"`, or `"vlm_blocks"` |
| `store_page_images` | No | `false` | Render and store page images on Page nodes |
| `dpi` | No | `150` | DPI for page image rendering |
| `metadata_json` | No | `null` | JSON string of extra Document properties |
| `skip_furniture` | No | `true` | Skip headers/footers (docling and vlm_blocks modes) |
| `extract_sections` | No | `true` | Extract section hierarchy (docling and vlm_blocks modes) |
| `extract_toc` | No | `true` | Extract TOC entries (docling mode) |
| `chunk_size` | No | `500` | Target tokens per chunk (pymupdf mode) |
| `chunk_overlap` | No | `50` | Token overlap between chunks (pymupdf mode) |
| `extract_images` | No | `true` | Extract images as Image nodes with imageBase64 (pymupdf mode) |
| `extract_tables` | No | `true` | Extract tables as Table nodes with imageBase64 + text (pymupdf mode) |
| `max_vlm_parallel` | No | `10` | Max concurrent VLM calls per document (vlm_blocks mode) |
| `vlm_prompt` | No | `null` | Custom VLM system prompt override (vlm_blocks mode) |
| `text_preview_length` | No | `200` | Characters of text preview sent to VLM per block (vlm_blocks mode) |

### Parse Modes

- **pymupdf**: PyMuPDF extraction with optional image/table detection. Creates `Document` + `Chunk` nodes. Set `extract_images=false` and `extract_tables=false` for text-only.
- **docling**: Full layout analysis with sections, tables, captions. Creates `Document`, `Page`, `Element`, `Section` nodes. Requires the `docling` extra.
- **page_image**: Renders each page as an image alongside extracted text. Creates `Document` + `Page` nodes. Best for slides and VLM-based entity extraction.
- **vlm_blocks**: PyMuPDF block extraction + VLM reading order/classification. Creates `Document`, `Page`, `Element`, `Section` nodes (same as docling). Uses a VLM API to determine reading order and semantic roles for PyMuPDF's text blocks. No local GPU or docling dependency required. Cost: ~$0.005-0.01/page with GPT-5-mini.

### Example Output

```json
{
  "job_id": "job_abc123",
  "status": "queued",
  "files_total": 3,
  "total_pages": 42,
  "estimated_minutes": 2.1,
  "message": "Job queued. Use check_processing_status('job_abc123') to monitor."
}
```

---

## check_processing_status

Check the status of background lexical graph processing jobs. Returns progress info including elapsed time, estimated remaining time, files completed/remaining, pages processed, and elements extracted.

### Parameters

| Name | Required | Default | Description |
|------|----------|---------|-------------|
| `job_id` | No | `null` | Job ID to check. If `null`, returns status of all jobs |

### Example Output

```json
{
  "status": "running",
  "job_id": "job_abc123",
  "elapsed_seconds": 45,
  "files_completed": 1,
  "files_total": 3,
  "pages_processed": 12,
  "total_pages_expected": 42,
  "estimated_remaining_seconds": 90
}
```

---

## cancel_job

Cancel a running background processing job. If `cleanup=true`, deletes any documents that were already written to Neo4j by this job.

### Parameters

| Name | Required | Default | Description |
|------|----------|---------|-------------|
| `job_id` | Yes | - | Job ID to cancel |
| `cleanup` | No | `true` | Delete partial graph data created by the cancelled job |

### Example Output

```json
{
  "status": "cancelled",
  "job_id": "job_abc123",
  "documents_cleaned": 1,
  "message": "Job job_abc123 cancelled."
}
```
