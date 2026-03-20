# Handle Unstructured Data Input

Handle PDF documents: discovery, parse mode selection, and the required ingestion tool sequence.

---

## Discovery

- Sample data should be in `data/pdf/` (and subfolders if present)
- Use the Read tool with `pages: "1-2"` to sample content — do not use MCP tools at this stage
- Identify the document type to select the appropriate parse mode (see guide below)
- If using pre-existing CSV data: identify which entity types overlap between PDFs and structured nodes. These **bridge nodes** will be merged on a shared key property (e.g. `name`) — identify the key property during discovery, before ingestion.

### Parse Mode Guide

| Mode | Mechanism | Best for | Speed |
|------|-----------|----------|-------|
| `pymupdf` | Direct text extraction + optional image/table capture | Text-heavy PDFs, research papers, reports | Fastest |
| `docling` | Full layout detection engine | Structured docs with tables, sections, mixed layout | Moderate |
| `page_image` | Each page → image → VLM describes holistically | Slides/PPT-as-PDF, diagrams, flowcharts, visually complex pages | Fast (parallelized) |
| `vlm_blocks` | pymupdf extracts bboxes → each block → VLM classifies + reading order | Mixed content where block-level granularity matters; faster alternative to docling | Faster than docling (experimental) |

**`page_image`** — use when meaning comes from visual layout rather than text (slides, pipeline diagrams, architecture charts, color/spatial arrangement). Text extraction alone would produce meaningless fragments. The page is the atomic unit: one chunk per page.

**`vlm_blocks`** — use for documents with a mix of text and visual blocks where sub-page granularity matters and docling is too slow.

**Do not use `page_image`** for long-form text documents (use `pymupdf`) or tables with structured section hierarchy (use `docling` or `vlm_blocks`).

---

## Ingestion — Required Tool Sequence

Use `neo4j-lexical-graph` then `neo4j-entity-graph`. Follow the sequence for your parse mode:

---

### `pymupdf` mode

#### Step 1 — Create the lexical graph (required)

Call `create_lexical_graph` with `parse_mode="pymupdf"`.

Key parameters:
- `extract_tables=True` (default) — extracts tables as `Table` nodes with `imageBase64` + raw text. **Keep enabled** for table-dense documents (academic papers, reports) — tables generate extra embedded chunks and significantly improve entity extraction yield.
- `extract_images=True` (default) — extracts images as `Image` nodes with `imageBase64`. Set to `False` if the doc has no meaningful images (e.g. pure text reports).
- `extract_sections=False` — pymupdf does not detect section hierarchy; leave at default.

Chunking is integrated into `create_lexical_graph` for pymupdf — no separate `chunk_lexical_graph` step needed.

Use `check_processing_status` to monitor progress for large batches.

#### Step 2 — Verify documents were parsed (required)

Call `list_documents` to confirm all expected PDFs were ingested and get document IDs. If count is zero, check the folder path and re-run before continuing.

#### Step 3 — Optional: spot-check parse quality

Call `verify_lexical_graph` on **one representative document** to inspect reading order, elements, and chunks as stored in Neo4j — useful for catching parse issues on a new document type.

- Single document only — never call on every document in a batch.
- Check the chunk count and element types reported in the output.

#### Step 4 — Generate chunk descriptions (recommended when images or tables are present)

Call `generate_chunk_descriptions` for each document that contains `Image` or `Table` nodes.

**Why this matters:**
- `Table`/`Image` nodes have `imageBase64` but no meaningful `text` property — without descriptions, these nodes produce 0 embeddings and are invisible to semantic search.
- `generate_chunk_descriptions` sends the image to a VLM (vision model) and stores a rich natural-language description in `textDescription`.
- `embed_chunks` then uses `textDescription` for Table/Image nodes and `text` for regular Chunk nodes — all in one unified index (auto-detected).
- `extract_entities` also routes Table/Image chunks through the VLM extractor (image + text sent together) — descriptions improve extraction quality.

Call without `document_id` to run for all active documents at once:
```
generate_chunk_descriptions(parallel=10)
```

Or pass a specific `document_id` to process a single document.

#### Step 5 — Generate embeddings (required for semantic search)

Call `embed_chunks` with **no parameters** — the tool auto-detects whether `textDescription` was generated and selects the right embedding strategy:
- If `textDescription` exists on any Chunk: uses `COALESCE(textDescription, text)` — Table/Image nodes embedded from VLM description, text chunks from raw text.
- Otherwise: uses `text` directly.

The output reports `auto_detected_fallback=true` when this happens, confirming the unified strategy was applied.

`embed_chunks` also creates a fulltext index by default — no separate index creation step needed. It is synchronous — no need to poll `check_processing_status` after.

---

### `docling` mode

#### Step 1 — Create the lexical graph (required)

Call `create_lexical_graph` with `parse_mode="docling"`.

Key parameters:
- `extract_sections=True` (default) — extracts section headings. Keep enabled for structured docs.
- `extract_toc=True` (default) — extracts table of contents. Keep enabled.
- `skip_furniture=True` (default) — skips headers/footers.

Note: docling is slower than pymupdf. For large batches, budget more time.

Use `check_processing_status` to monitor.

#### Step 2 — Chunk the lexical graph (required)

Call `chunk_lexical_graph` after `create_lexical_graph`. Docling produces structured layout elements — chunking converts these into `Chunk` nodes for embedding and extraction.

Key parameters:
- `strategy="structured"` — recommended for section-aware docs (respects section boundaries).
- `strategy="token_window"` (default) — simple sliding window, ignores structure.
- `include_tables_as_chunks=True` (default) — creates separate chunks for tables.

#### Step 3 — Verify documents were parsed (required)

Call `list_documents` to confirm ingestion and get document IDs.

#### Step 4 — Optional: spot-check parse quality

Call `verify_lexical_graph` on one document. Docling produces richer structure (sections, captions, tables) — verify that sections and reading order look correct before proceeding.

- Single document only.
- Never use for `page_image` mode (base64 flood).

#### Step 5 — Optional: assign section hierarchy

Call `assign_section_hierarchy` for structured documents with nested sections (legal texts, regulatory documents, long-form reports). This:
- Uses LLM to infer the correct heading levels from section titles.
- Rebuilds `HAS_SUBSECTION` relationships.
- Updates `sectionContext` on all active Chunk nodes (e.g. `"Chapter 1 > Section 1.1 > Sub 1.1.1"`).

Not useful for slides or page_image mode. Skip for flat docs (no section hierarchy).

#### Step 6 — Generate chunk descriptions (recommended when images or tables are present)

Same rationale as pymupdf Step 4 — if docling extracted image/table elements with `imageBase64`, run `generate_chunk_descriptions` to add VLM descriptions for embedding and entity extraction.

#### Step 7 — Generate embeddings (required for semantic search)

Call `embed_chunks` with no parameters. Auto-detection applies the same way as pymupdf mode.

---

### `page_image` mode

#### Step 1 — Create the lexical graph (required)

Call `create_lexical_graph` with `parse_mode="page_image"`.

Key parameters:
- `store_page_images=True` — stores rendered page images on `Page` nodes. Required for later VLM description generation and `read_node_image` access.
- `dpi=150` (default) — rendering resolution. Increase to 200–300 for dense slides.

Each page becomes one `Page` node. Chunking is not needed — pages are already atomic units.

Use `check_processing_status` to monitor.

#### Step 2 — Chunk the lexical graph (required)

Call `chunk_lexical_graph` after `create_lexical_graph`. For `page_image` mode, this converts `Page` nodes into `Chunk` nodes.

Use default parameters — do not sub-chunk further (the page is the atomic unit).

#### Step 3 — Verify documents were parsed (required)

Call `list_documents` to confirm ingestion and get document IDs. Check that page count matches expected.

**Do not use `verify_lexical_graph`** for page_image mode — it reconstructs the document from base64 images (5.8MB+ per document), which is unreadable and slow. Use `read_node_image` to spot-check individual page images instead.

#### Step 4 — Generate chunk descriptions (**REQUIRED**)

Call `generate_chunk_descriptions` before `embed_chunks`. This is mandatory:
- Page nodes have no `text` property — the VLM must describe each page image first.
- Skipping this step causes `embed_chunks` to silently produce 0 embeddings with no error.

Call without `document_id` to run for all active documents at once:
```
generate_chunk_descriptions(parallel=10)
```

#### Step 5 — Generate embeddings (required for semantic search)

Call `embed_chunks` with no parameters. Auto-detection will find `textDescription` on Page/Chunk nodes and use it automatically.

---

### `vlm_blocks` mode

Follows the same sequence as `docling` mode (Steps 1–7), with these differences:
- `create_lexical_graph` uses `parse_mode="vlm_blocks"` and `extraction_model` (the VLM used for block classification).
- Produces `Page` + `Element` + `Section` nodes (not `Element`-only like docling).
- Faster than docling — pymupdf handles text extraction, VLM only classifies blocks.
- `assign_section_hierarchy` is supported and useful.

---

## Entity Reconciliation

After entity extraction, if CSV data is also present, run a reconciliation check to identify name mismatches between extracted entity nodes and existing structured nodes. Without reconciliation, bridge nodes will exist as duplicates and cross-graph relationships will not form.

```cypher
MATCH (extracted:Condition)
WHERE NOT EXISTS {
  MATCH (structured:Condition)
  WHERE toLower(structured.name) = toLower(extracted.name)
}
RETURN extracted.name AS unmatched_extracted_name
LIMIT 20
```

If mismatches exist, choose one of these strategies:
1. **Post-process with Cypher** — add a `canonicalName` property or MERGE the extracted node into the existing structured node using fuzzy match (e.g. `toLower() CONTAINS` or `apoc.text.similarity`)
2. **Normalize at extraction time** — adjust the Pydantic schema field description to instruct the LLM to use exact names from the structured data (include an explicit allowed values list when the vocabulary is small and known)

> LLMs frequently produce variant forms of the same entity (e.g. "Type 2 diabetes", "Type II Diabetes", "T2DM"). Plan for normalization during schema design.
