# Ingestion: `docling` mode

Use for structured documents with complex layouts: tables, sections, mixed content. Slower than pymupdf but produces richer structure.

---

## Step 1 — Create the lexical graph (required)

Call `create_lexical_graph` with `parse_mode="docling"`.

Key parameters:
- `extract_sections=True` (default) — extracts section headings. Keep enabled.
- `extract_toc=True` (default) — extracts table of contents. Keep enabled.
- `skip_furniture=True` (default) — skips headers/footers.

Docling is slower than pymupdf. For large batches, budget more time.
Use `check_processing_status(job_id)` to monitor.

---

## Step 2 — Chunk the lexical graph (required)

Call `chunk_lexical_graph` after `create_lexical_graph`. Docling produces layout elements — this converts them into `Chunk` nodes for embedding and extraction.

Key parameters:
- `strategy="structured"` — recommended for section-aware docs (respects section boundaries).
- `strategy="token_window"` (default) — simple sliding window, ignores structure.
- `include_tables_as_chunks=True` (default) — creates separate chunks for tables.

---

## Step 3 — List documents (required)

Call `list_documents` to confirm ingestion and get document IDs.

---

## Step 4 — Spot-check parse quality (optional)

Call `verify_lexical_graph` on one document. Verify that sections and reading order look correct.

- Single document only.

---

## Step 5 — Assign section hierarchy (optional)

Call `assign_section_hierarchy` for documents with nested sections (legal texts, regulatory docs, long-form reports). This:
- Uses LLM to infer correct heading levels from section titles.
- Rebuilds `HAS_SUBSECTION` relationships.
- Updates `sectionContext` on active Chunk nodes (e.g. `"Chapter 1 > Section 1.1 > Sub 1.1.1"`).

Skip for flat documents with no section hierarchy.

---

## Step 6 — Generate chunk descriptions (recommended when images or tables are present)

If docling extracted image/table elements with `imageBase64`, run `generate_chunk_descriptions` to add VLM descriptions for embedding and entity extraction.

Call without `document_id` to run for all active documents at once:
```
generate_chunk_descriptions(parallel=10)
```

---

## Step 7 — Generate embeddings (required for semantic search)

Call `embed_chunks` with **no parameters**. Auto-detects `textDescription` and applies the right strategy. Also creates a fulltext index. Synchronous — no polling needed.
