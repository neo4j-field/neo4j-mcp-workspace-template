# Ingestion: `page_image` mode

Use for slides, presentations, diagrams, and visually complex pages where meaning comes from layout rather than text. Each page becomes one chunk — the page is the atomic unit.

---

## Step 1 — Create the lexical graph (required)

Call `create_lexical_graph` with `parse_mode="page_image"`.

Key parameters:
- `store_page_images=True` — stores rendered page images on `Page` nodes. Required for VLM description generation and `read_node_image` access.
- `dpi=150` (default) — rendering resolution. Increase to 200–300 for dense slides.

Use `check_processing_status(job_id)` to monitor.

---

## Step 2 — Chunk the lexical graph (required)

Call `chunk_lexical_graph` after `create_lexical_graph`. Converts `Page` nodes into `Chunk` nodes.

Use default parameters — do not sub-chunk further (the page is the atomic unit).

---

## Step 3 — List documents (required)

Call `list_documents` to confirm ingestion and check page count matches expected.

**Do not use `verify_lexical_graph`** for page_image mode — it floods the context with base64 images (5.8MB+ per document). Use `read_node_image` to spot-check individual pages instead.

---

## Step 4 — Generate chunk descriptions (**REQUIRED**)

Page nodes have no `text` property — the VLM must describe each page image before embedding. Skipping this causes `embed_chunks` to silently produce 0 embeddings.

Call without `document_id` to run for all active documents at once:
```
generate_chunk_descriptions(parallel=10)
```

---

## Step 5 — Generate embeddings (required for semantic search)

Call `embed_chunks` with **no parameters**. Auto-detects `textDescription` on Page/Chunk nodes. Also creates a fulltext index. Synchronous — no polling needed.
