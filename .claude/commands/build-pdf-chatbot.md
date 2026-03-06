# Build PDF Chatbot — Neo4j Knowledge Graph from PDFs

Build a question-answering chatbot backed by a Neo4j knowledge graph, from a set of PDF documents. Covers discovery, schema design, lexical graph construction, entity extraction with validators, and Q&A validation.

## Progress Checklist

Copy this checklist to track progress:

```
- [ ] Step 1: Discover PDF content and domain
- [ ] Step 2: Align on use case and confirm target questions
- [ ] Step 3: Design graph data model
- [ ] Step 4: Build lexical graph (parse, chunk, embed, index)
- [ ] Step 5: Export schema and review Pydantic validators
- [ ] Step 6: Extract entities
- [ ] Step 7: Verify extraction results
- [ ] Step 8: Answer confirmed questions using the graph
- [ ] Step 9: Generate report
```

---

## Step 1: Discover PDF Content

- List the PDFs in `data/pdf/` (and subfolders if present) using the Glob or Bash tool
- For each PDF, use the **Read tool** with `pages: "1-2"` to sample content directly — do not use any MCP server for this step
- Note the PDF type to inform parse mode selection (see Parse Mode Guide below)
- Summarize: domain, document type, approximate entity types visible, content layout

### Parse Mode Guide

| Mode | Mechanism | Best for | Speed |
|------|-----------|----------|-------|
| `pymupdf` | Direct text extraction | Text-heavy PDFs, research papers, reports | Fastest |
| `docling` | Full layout detection engine | Structured docs with tables, sections, mixed layout | Moderate |
| `page_image` | Each page → image → VLM describes holistically | Slides/PPT-as-PDF, diagrams, flowcharts, pipelines, visually complex pages | Fast (parallelized) |
| `vlm_blocks` | pymupdf extracts text + bboxes → each block image sent to VLM for classification and reading order | Mixed content where block-level granularity matters; faster alternative to docling | Faster than docling (experimental) |

**When to use `page_image`:** Content where meaning comes from visual layout rather than text alone — slides where relationships are conveyed through arrows, boxes, color, and spatial arrangement; pipeline diagrams; architecture charts. Text extraction would produce meaningless fragments. The page is the atomic unit: one chunk per page, the VLM describes what it sees holistically.

**When to use `vlm_blocks`:** Documents with a mix of text and visual blocks where you want sub-page granularity. pymupdf handles text extraction (fast), and a VLM classifies each block type (figure, table, heading, body) and resolves reading order — making it a faster, experimental alternative to docling for layout-aware chunking.

**When NOT to use `page_image`:** Long-form text documents — use `pymupdf`. Rich tables with structured section hierarchy — use `docling` or `vlm_blocks`.

---

## Step 2: Use Case and Target Questions

1. Ask the user for their use case context (domain, audience, what decisions the chatbot should support)
2. Based on the PDF content and use case, propose **5-8 realistic target questions** a user might ask the chatbot. Examples should:
   - Be specific and answerable from the document content
   - Cover different query types: factual lookup, comparison, relationship traversal, aggregation
   - Reflect the stated use case
3. Present the proposed questions and ask the user to:
   - Confirm, edit, or remove questions
   - Add questions you may have missed
4. Finalize the question list — these become the validation targets for the entire pipeline

---

## Step 3: Graph Data Model

Use the `neo4j-data-modeling` MCP server. Follow this process:

**1. Analysis**
- Use `list_example_data_models` to check for relevant examples
- Use `get_example_data_model` to retrieve any relevant examples
- Design entities and relationships that support the confirmed target questions
- Key properties should be unique identifiers (used for deduplication during extraction)

**2. Generation**
- Generate the data model — every node must have a `key_property` that will serve as a unique identifier during entity extraction
- Use `get_mermaid_config_str` to validate and get a Mermaid visualization
- Correct any validation errors and repeat

**3. Iteration**
- Show the Mermaid visualization and explain the model
- Map each target question to the nodes/relationships that will answer it
- Note any questions that cannot be answered by the current model
- Request feedback, iterate until approved

**4. Persist**
- Save the final data model JSON to `outputs/data_models/<topic>_data_model.json`

---

## Step 4: Build Lexical Graph

Use the `neo4j-lexical-graph` MCP server.

**1. Parse and create lexical graph**
- Use `create_lexical_graph` with the appropriate `parse_mode` determined in Step 1
- For `page_image` mode: each page becomes one Chunk — do not further sub-chunk, as the page is the atomic unit of meaning (the vision model has already described the full page holistically)
- Process all PDFs in `data/pdf/` (or the relevant subfolder)
- Use `check_processing_status` to monitor progress for large batches

**2. Verify**
- Use `list_documents` to confirm all PDFs were ingested and get document IDs
- Use `verify_lexical_graph` only on a single representative document to spot-check quality: it produces a Markdown rendering of the document as stored in Neo4j (reading order, elements, chunks) — useful for catching parse issues (missed elements, wrong order, garbled blocks) without querying Neo4j manually
- Do not call `verify_lexical_graph` on every document in a large batch — use it selectively when you suspect a parsing issue or want to validate the chosen parse mode on a new document type
- **For `page_image` mode: do not use `verify_lexical_graph`** — the reconstruction is 5.8MB+ of base64-encoded images, unreadable and slow. Instead, confirm ingestion quality by checking page count via `list_documents` and spot-checking a single node image with `read_node_image`

**3. Generate chunk descriptions (required for `page_image` mode)**
- For `page_image` mode: call `generate_chunk_descriptions` **before** `embed_chunks` — Page nodes have no text until the VLM describes them; skipping this step means `embed_chunks` silently produces 0 results
- For other modes: optional — use if chunks would benefit from LLM-generated summaries
- Use `check_processing_status` to monitor

**4. Embed chunks**
- Use `embed_chunks` to generate vector embeddings for semantic search
- `embed_chunks` also creates a fulltext index by default (`create_fulltext_index=True`) — no separate index creation step needed
- Use `check_processing_status` to monitor

---

## Step 5: Export Schema and Review Validators

Use `neo4j-entity-graph` → `convert_schema`:

**1. Export**
- Pass the saved data model JSON to `convert_schema`
- Set `output_path` to `outputs/schemas/<topic>_schema.json`
- This creates two files:
  - `outputs/schemas/<topic>_schema.json` — extraction schema (used by entity extraction)
  - `outputs/schemas/<topic>_schema.json.py` — Pydantic models

**2. Review the Pydantic `.py` file**
- Open `outputs/schemas/<topic>_schema.json.py` and review each model
- For each node's key property, verify or add a validator to normalize values (lowercase, strip whitespace, canonical form) — this prevents duplicate nodes from minor text variations
- Example validator pattern:
  ```python
  @field_validator('name')
  @classmethod
  def normalize_name(cls, v: str) -> str:
      return v.strip().lower()
  ```
- Add merge-strategy comments if relevant (e.g., whether to MERGE or CREATE in Neo4j)
- Present the validators to the user and ask for confirmation before proceeding

---

## Step 6: Extract Entities

Use `neo4j-entity-graph` → `extract_entities`:

- Pass the `output_path` from Step 5 as the schema reference
- Extraction is async — use `check_extraction_status` to monitor progress
- Report progress to the user: chunks processed, entities found so far

---

## Step 7: Verify Extraction Results

Use `neo4j-graphrag` → `read_neo4j_cypher`:

Run verification queries to confirm extraction quality:

```cypher
// Count extracted entities per label
CALL db.labels() YIELD label
CALL apoc.cypher.run('MATCH (n:' + label + ') RETURN count(n) as count', {}) YIELD value
RETURN label, value.count ORDER BY value.count DESC
```

Or simpler, check each expected node label individually:
```cypher
MATCH (n:<NodeLabel>) RETURN count(n) as count
```

Also check for potential duplicates on key properties:
```cypher
MATCH (n:<NodeLabel>)
WITH n.<keyProp> as key, count(*) as cnt
WHERE cnt > 1
RETURN key, cnt ORDER BY cnt DESC LIMIT 10
```

If significant duplicates are found, note them in the report and suggest validator improvements. Do not re-run extraction — document for next iteration.

Also verify entity-to-chunk relationships exist:
```cypher
MATCH (n)-[:EXTRACTED_FROM]->(c:Chunk) RETURN count(*) as entity_chunk_links
```

---

## Step 8: Answer Confirmed Questions

For each confirmed question from Step 2, answer it using the graph. Try the most appropriate retrieval method first, then note what worked.

### Retrieval methods (in order of preference per question type)

| Question type | Preferred method | MCP tool |
|---------------|-----------------|----------|
| Semantic / open-ended | Vector search | `vector_search` |
| Keyword / name lookup | Fulltext search | `fulltext_search` |
| Relationship traversal / structured | Cypher | `read_neo4j_cypher` |
| Complex / multi-hop | Graph-grounded | `search_cypher_query` |
| Inspect visual source of an answer | Read node image | `read_node_image` |

### Using `read_node_image`

All parse modes can produce nodes with images stored as base64:
- `page_image` — every Chunk node is a full page image
- `pymupdf`, `docling`, `vlm_blocks` — Image and Table element nodes may contain images

When a retrieval result references a node that likely has visual content, use `read_node_image` with the node's `elementId` to display the actual image. This is valuable for:
- Verifying the answer came from the right source
- Answering questions about diagrams, tables, or pipeline steps where the image itself is the answer
- Debugging unexpected or low-quality answers by inspecting what the VLM saw

The tool reads the `imageBase64` property by default and detects MIME type from `imageMimeType`. Use `return_properties` to include relevant text properties alongside the image.

For each question, record:
- **Question** — the confirmed question text
- **Method used** — vector / fulltext / cypher / combined / image
- **Query** — the actual query or Cypher used
- **Answer** — the result from the graph
- **Image inspected** — yes/no, and what it showed
- **Quality** — subjective assessment: Complete / Partial / Not answered
- **Improvement note** — what would make this answer better (more data, schema change, better chunking, different parse mode, etc.)

---

## Step 9: Generate Report

Save the report as `outputs/reports/<topic>_chatbot_report.md`.

Structure:

```markdown
# PDF Chatbot Report — <Topic>

## Source Documents
- List each PDF with: filename, domain, parse mode used, chunk count

## Use Case
<User-stated use case>

## Graph Data Model
<Mermaid diagram>
<Description of each node and relationship>

## Target Questions and Answers

### Q1: <question>
- **Method**: <vector / fulltext / cypher>
- **Query**: <query used>
- **Answer**: <answer from graph>
- **Quality**: Complete / Partial / Not answered
- **Improvement**: <note>

[repeat for each question]

## Extraction Quality
- Entity counts per label
- Duplicate analysis
- Entity-to-chunk link count

## Gaps and Limitations
- Questions not answered and why
- Schema gaps
- Parse mode observations

## Recommended Next Steps
- Validator improvements
- Schema refinements
- Additional data sources
- Alternative parse modes to try
```

---

## MCP Server Quick Reference

| Server | Step | Key Tools |
|--------|------|-----------|
| `neo4j-data-modeling` | 3 | `list_example_data_models`, `get_example_data_model`, `get_mermaid_config_str`, `validate_data_model` |
| `neo4j-lexical-graph` | 4 | `create_lexical_graph`, `list_documents`, `generate_chunk_descriptions` (required for `page_image`), `embed_chunks`, `check_processing_status`, `verify_lexical_graph` (spot-check only, single doc) |
| `neo4j-entity-graph` | 5–6 | `convert_schema`, `extract_entities`, `check_extraction_status` |
| `neo4j-graphrag` | 7–8 | `get_neo4j_schema_and_indexes`, `read_neo4j_cypher`, `write_neo4j_cypher`, `vector_search`, `fulltext_search`, `search_cypher_query`, `read_node_image` |
