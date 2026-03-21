# Ingestion: `vlm_blocks` mode

**Experimental — prefer `docling` for production use.** Use only when docling is not available and sub-page block granularity matters. Follows the same sequence as `docling` mode with minor differences.

---

## Step 1 — Create the lexical graph (required)

Call `create_lexical_graph` with `parse_mode="vlm_blocks"`.

Key differences from docling:
- pymupdf handles text extraction; the VLM only classifies blocks and resolves reading order (faster than full docling layout analysis).
- Produces `Page` + `Element` + `Section` nodes.

Use `check_processing_status(job_id)` to monitor.

---

## Step 2 — Chunk the lexical graph (required)

Call `chunk_lexical_graph`. Same parameters as docling mode:
- `strategy="structured"` — recommended for section-aware docs.
- `strategy="token_window"` (default) — simple sliding window.
- `include_tables_as_chunks=True` (default).

---

## Step 3 — List documents (required)

Call `list_documents` to confirm ingestion and get document IDs.

---

## Step 4 — Spot-check parse quality (optional)

Call `verify_lexical_graph` on one document to check reading order and element types.

- Single document only.

---

## Step 5 — Assign section hierarchy (optional)

Call `assign_section_hierarchy` for documents with nested sections. Same behavior as docling mode — uses LLM to infer heading levels and updates `sectionContext` on chunks.

Call without `document_id` to process all active documents in parallel:
```
assign_section_hierarchy()
```

---

## Step 6 — Generate chunk descriptions (recommended when images or tables are present)

Call `generate_chunk_descriptions` without `document_id` to run for all active documents:
```
generate_chunk_descriptions(parallel=10)
```

**Non-informative image guard:** The VLM automatically detects logos, headers, footers, and decorative elements. These are stored as `"Non-informative image: [label]"` rather than fabricating domain content. They embed at low similarity scores and don't pollute semantic search.

---

## Step 7 — Generate embeddings (required for semantic search)

Call `embed_chunks` with **no parameters**. Auto-detects `textDescription`. Also creates a fulltext index. Synchronous — no polling needed.
