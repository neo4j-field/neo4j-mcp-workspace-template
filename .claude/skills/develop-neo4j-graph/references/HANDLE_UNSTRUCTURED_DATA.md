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
| `pymupdf` | Direct text extraction | Text-heavy PDFs, research papers, reports | Fastest |
| `docling` | Full layout detection engine | Structured docs with tables, sections, mixed layout | Moderate |
| `page_image` | Each page → image → VLM describes holistically | Slides/PPT-as-PDF, diagrams, flowcharts, visually complex pages | Fast (parallelized) |
| `vlm_blocks` | pymupdf extracts bboxes → each block → VLM classifies + reading order | Mixed content where block-level granularity matters; faster alternative to docling | Faster than docling (experimental) |

**`page_image`** — use when meaning comes from visual layout rather than text (slides, pipeline diagrams, architecture charts, color/spatial arrangement). Text extraction alone would produce meaningless fragments. The page is the atomic unit: one chunk per page.

**`vlm_blocks`** — use for documents with a mix of text and visual blocks where sub-page granularity matters and docling is too slow.

**Do not use `page_image`** for long-form text documents (use `pymupdf`) or tables with structured section hierarchy (use `docling` or `vlm_blocks`).

---

## Ingestion — Required Tool Sequence

Use `neo4j-lexical-graph` then `neo4j-entity-graph`. Always follow this sequence:

### Step 1 — Create the lexical graph (required)

Call `create_lexical_graph` with the path to the PDF folder and the chosen `parse_mode`. This parses PDFs and creates `Document` and element nodes in Neo4j.

For `page_image` mode: each page becomes one Chunk — do not further sub-chunk, as the page is the atomic unit of meaning (the VLM has already described the full page holistically).

Use `check_processing_status` to monitor progress for large batches.

### Step 2 — Chunk the lexical graph (required for `docling`, `vlm_blocks`, `page_image` modes)

Call `chunk_lexical_graph` after `create_lexical_graph`. This splits parsed layout elements into `Chunk` nodes and is required for parse modes that produce structured elements rather than raw text chunks.

For `pymupdf` mode: chunking is integrated into `create_lexical_graph` — skip this step.

### Step 3 — Verify documents were parsed (required)

Call `list_documents` to confirm all expected PDFs were ingested and get document IDs. If count is zero, check the folder path and re-run before continuing.

### Step 4 — Optional: spot-check parse quality

Call `verify_lexical_graph` on **one representative document** to inspect reading order, elements, and chunks as stored in Neo4j — useful for catching parse issues (missed elements, wrong order, garbled blocks) on a new document type.

**Rules:**
- Single document only — never call on every document in a batch
- **Never use for `page_image` mode** — reconstruction is 5.8MB+ of base64-encoded images, unreadable and slow. Instead, confirm ingestion by checking page count via `list_documents` and spot-checking a single page with `read_node_image`

### Step 5 — Optional: assign section hierarchy

Call `assign_section_hierarchy` to detect document section headings and tag chunks with section context. Useful for structured legal/regulatory documents with nested article references. Not useful for slides or `page_image` mode.

### Step 6 — Generate chunk descriptions (REQUIRED before embed_chunks for `page_image` mode)

For `page_image` mode: call `generate_chunk_descriptions` **before** `embed_chunks`. Page nodes have no text until the VLM describes them — skipping this step causes `embed_chunks` to silently produce 0 embeddings with no error.

For other modes: optional — use if chunks would benefit from LLM-generated summaries for descriptive search.

Use `check_processing_status` to monitor.

### Step 7 — Generate embeddings (required for semantic search)

Call `embed_chunks` to generate vector embeddings on all `Chunk` nodes. Also creates a fulltext index by default (`create_fulltext_index=True`) — no separate index creation step needed.

`embed_chunks` is synchronous — no need to poll `check_processing_status` after it completes.

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
