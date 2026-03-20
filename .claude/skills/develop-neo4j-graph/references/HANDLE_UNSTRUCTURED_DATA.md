# Handle Unstructured Data Input

Handle PDF documents: discovery, parse mode selection, and entity reconciliation.

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

Once you have selected a parse mode, load the mode-specific reference:
- [`PYMUPDF_MODE.md`](./PYMUPDF_MODE.md)
- [`DOCLING_MODE.md`](./DOCLING_MODE.md)
- [`PAGE_IMAGE_MODE.md`](./PAGE_IMAGE_MODE.md)
- [`VLM_BLOCKS_MODE.md`](./VLM_BLOCKS_MODE.md)

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
