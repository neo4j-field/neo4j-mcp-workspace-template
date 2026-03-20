# Ingestion: `pymupdf` mode

Use for text-heavy PDFs, research papers, reports. Fastest mode. Chunking is integrated — no separate `chunk_lexical_graph` step needed.

---

## Step 1 — Create the lexical graph (required)

Call `create_lexical_graph` with `parse_mode="pymupdf"`.

Key parameters:
- `extract_tables=True` (default) — extracts tables as `Table` nodes with `imageBase64` + raw text. **Keep enabled** for table-dense documents — tables are embedded separately and improve entity extraction yield.
- `extract_images=True` (default) — extracts images as `Image` nodes with `imageBase64`. Set to `False` if the doc has no meaningful images.
- `extract_sections=False` — pymupdf does not detect section hierarchy; leave at default.

Returns a `job_id`. Use `check_processing_status(job_id)` to monitor for large batches.

---

## Step 2 — List documents (required)

Call `list_documents` to confirm all expected PDFs were ingested and get document IDs. If count is zero, check the folder path and re-run before continuing.

---

## Step 3 — Spot-check parse quality (optional)

Call `verify_lexical_graph` on **one representative document** to inspect reading order, elements, and chunks as stored in Neo4j.

- Single document only — never call on every document in a batch.

---

## Step 4 — Generate chunk descriptions (recommended when images or tables are present)

`Table`/`Image` nodes have `imageBase64` but no `text` — without descriptions they are invisible to semantic search and entity extraction.

Call without `document_id` to run for all active documents at once:
```
generate_chunk_descriptions(parallel=10)
```

After running:
- `textDescription` is set on each Table/Image node
- `embed_chunks` will auto-detect this and use `COALESCE(textDescription, text)`
- `extract_entities` will route Table/Image chunks through VLM extraction

---

## Step 5 — Generate embeddings (required for semantic search)

Call `embed_chunks` with **no parameters**. Auto-detects `textDescription` and applies the right strategy:
- Table/Image nodes → embedded from `textDescription`
- Text Chunk nodes → embedded from `text`
- All in one unified index (`chunk_text_embedding`)

Also creates a fulltext index (`chunk_text_fulltext`). Synchronous — no polling needed.
