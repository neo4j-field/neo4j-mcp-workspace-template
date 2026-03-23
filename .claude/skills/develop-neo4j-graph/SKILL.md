---
name: develop-neo4j-graph
description: Develop Neo4j graphs end-to-end: analyze source data, design data models, ingest CSV and/or PDF data, extract entities, and validate with queries. Use when importing data to Neo4j, designing graph data models, creating knowledge graphs, or building chatbots or analytical applications backed by Neo4j.
---

# Develop Neo4j Graph

## Pre-flight: Confirm Models

Before starting, read `.env` and report the configured models:
- `EMBEDDING_MODEL` — used by `embed_chunks`
- `EXTRACTION_MODEL` — used by `extract_entities`

**Never substitute, correct, or override these values.** Model names in `.env` are user-configured and may include models you don't recognize (recently released models, LiteLLM aliases, custom endpoints). If a name looks unfamiliar, that is intentional — use it as-is.

If extraction or embedding fails with a model error, report the exact error and stop. Do not silently switch to a different model.

---

## Progress Checklist

Copy this checklist to track progress:

```
- [ ] Step 1: Discovery — read source data, identify entities
- [ ] Step 2: Use case discussion → determine MODE (CHATBOT or ANALYTICAL)
- [ ] Step 3: Graph data model
- [ ] Step 4: Ingest data (CSV and/or PDF)
- [ ] Step 4.5: Verify ingestion counts
- [ ] Step 5 [PDF only]: Export schema and review validators
- [ ] Step 6 [PDF only]: Extract entities
- [ ] Step 7 [PDF only]: Verify extraction results
- [ ] Step 8: Output [MODE-SPECIFIC]
```

---

## Step 1: Discovery

Read source data samples to understand content and structure. Do not use MCP tools at this stage.

**CSV data:** Read samples from `data/csv/`. Reference [HANDLE_STRUCTURED_DATA.md](./references/HANDLE_STRUCTURED_DATA.md) for discovery guidance, including the cross-file ID consistency check.

**PDF data:** List files in `data/pdf/` (and subfolders) using Glob. For each PDF, use the Read tool with `pages: "1-2"` to sample content. Reference the Parse Mode Guide in [HANDLE_UNSTRUCTURED_DATA.md](./references/HANDLE_UNSTRUCTURED_DATA.md) to identify the appropriate parse mode for each document type.

Summarize what you found: data types present, content domain, entity types visible, structural observations.

---

## Step 2: Use Case Discussion → Mode Selection

Ask the user what they want to accomplish with the data. **Do not ask them to choose a mode explicitly.**

To determine the mode, ask yourself: *does the user describe how someone will interact with the application (natural language Q&A), or what the data should reveal (patterns, aggregations, cohort analysis)?*

- **CHATBOT mode** signals: user mentions asking questions, a chatbot, a search interface, natural language queries, or retrieving answers on demand. The interaction is the point.

- **ANALYTICAL mode** signals: user mentions tracking, identifying patterns, correlations, treatment outcomes, cohort comparisons, monitoring, or surfacing insights across the dataset. The findings are the point — even if the result will power an application.

**When ambiguous** (e.g. "building an application" without specifying how users interact with it, or "connect X with Y" which could be retrieval or analysis), ask one clarifying question:
> "Will users primarily explore the data through natural language questions, or should the application surface structured patterns and reports from the data?"

**Set MODE = CHATBOT or ANALYTICAL. State it clearly. You will return to this at Step 8.**

---

## Step 3: Graph Data Model

Reference [GRAPH_DATA_MODELING_MCP.md](./references/GRAPH_DATA_MODELING_MCP.md) for the full modeling process using the `neo4j-data-modeling` MCP server.

**If handling both CSV and PDF data**, design four distinct sub-models, each visualized separately with `get_mermaid_config_str`:

1. **Structured data model** — nodes and relationships derived from CSV only
2. **Entity extraction model** — focused subset of nodes to extract from PDFs via LLM; must partially overlap with the structured model via **bridge nodes** (merged on a shared key property such as `name`)
3. **Lexical graph model** — `Document → Chunk`, created by `neo4j-lexical-graph`; no design needed, provided by the server
4. **Unified model** — all three layers combined; show explicitly how extracted entities connect to structured nodes (bridge nodes + MERGE key)

**[CHATBOT mode]** Map each confirmed target question to the nodes/relationships that will answer it. Flag any questions the current model cannot address.

Save the final model JSON to `outputs/data_models/<topic>_data_model.json`.

---

## Step 4: Ingest Data

### CSV data — `neo4j-ingest`

Reference [HANDLE_STRUCTURED_DATA.md](./references/HANDLE_STRUCTURED_DATA.md) for ingestion details.
Always use absolute paths. Use `ingest_csv_into_neo4j`.

### PDF data — `neo4j-lexical-graph`

Load the mode-specific reference file for the exact tool sequence:
- **pymupdf** → [PYMUPDF_MODE.md](./references/PYMUPDF_MODE.md)
- **docling** → [DOCLING_MODE.md](./references/DOCLING_MODE.md)
- **page_image** → [PAGE_IMAGE_MODE.md](./references/PAGE_IMAGE_MODE.md)
- **vlm_blocks** → [VLM_BLOCKS_MODE.md](./references/VLM_BLOCKS_MODE.md)

Quick reference (all modes):

| Step | Tool | pymupdf | docling | page_image | vlm_blocks |
|------|------|---------|---------|------------|------------|
| 1 | `create_lexical_graph` | ✓ | ✓ | ✓ | ✓ |
| 2 | `chunk_lexical_graph` | ✗ skip | ✓ | ✓ | ✓ |
| 3 | `list_documents` | ✓ | ✓ | ✓ | ✓ |
| 4 | `verify_lexical_graph` | optional | optional | ✗ never | optional |
| 5 | `assign_section_hierarchy` | ✗ skip | optional | ✗ skip | optional |
| 6 | `generate_chunk_descriptions` | if images/tables | if images/tables | **required** | if images/tables |
| 7 | `embed_chunks` | ✓ | ✓ | ✓ | ✓ |

**`generate_chunk_descriptions` — call without `document_id`** to run for all active documents at once.

**`embed_chunks` — call with no parameters.** Auto-detects `textDescription` and applies the right embedding strategy (VLM descriptions for Table/Image/Page nodes, raw text for others — all in one unified index).

---

## Step 4.5: Verify Ingestion Counts

After all ingestion is complete, run count checks for every node label and key relationship type using `read_neo4j_cypher` from `neo4j-graphrag`:

```cypher
MATCH (n:NodeLabel) RETURN COUNT(n) AS count
```

For CSV nodes: verify counts match source row counts (accounting for deduplication).

Check for orphan nodes:
```cypher
MATCH (n:NodeLabel) WHERE NOT (n)--() RETURN COUNT(n) AS orphans
```

If orphans are found, check for cross-file ID mismatches before proceeding.

---

## Step 5 [PDF only]: Export Schema and Review Validators

Use `convert_schema` from `neo4j-entity-graph` — **not** `export_to_pydantic_models` from the data-modeling server.

- Input: the entity extraction sub-model (not the full unified model)
- Set `output_path` to `outputs/schemas/<topic>_schema.json`
- Output: `<topic>_schema.json` (extraction config) + `<topic>_schema.json.py` (Pydantic models)

Review the Pydantic `.py` file. For each node's key property, verify or add a normalizing validator:

```python
@field_validator('name')
@classmethod
def normalize_name(cls, v: str) -> str:
    return v.strip().lower()
```

This prevents duplicate nodes from minor text variations (e.g. `"Aspirin"` vs `"aspirin "`). Present the validators to the user and confirm before proceeding.

---

## Step 6 [PDF only]: Extract Entities

Use `extract_entities` from `neo4j-entity-graph`:

- Pass the schema JSON path from Step 5
- Extraction is async — poll with `check_extraction_status` until complete
- Report progress to the user: chunks processed, entities found so far

---

## Step 7 [PDF only]: Verify Extraction Results

Use `read_neo4j_cypher` from `neo4j-graphrag`:

```cypher
-- Count per label
MATCH (n:NodeLabel) RETURN count(n) as count

-- Check for duplicates on key property
MATCH (n:NodeLabel)
WITH n.keyProp as key, count(*) as cnt
WHERE cnt > 1
RETURN key, cnt ORDER BY cnt DESC LIMIT 10

-- Verify entity-chunk links
MATCH (n)-[:EXTRACTED_FROM]->(c:Chunk) RETURN count(*) as entity_chunk_links
```

If CSV data is also present, run entity reconciliation to check for name mismatches between extracted and structured nodes. See [HANDLE_UNSTRUCTURED_DATA.md](./references/HANDLE_UNSTRUCTURED_DATA.md).

If significant duplicates: document them for next iteration. Do not re-run extraction.

---

## Step 8: Output [MODE-SPECIFIC]

**Reminder — current MODE: CHATBOT or ANALYTICAL (set in Step 2).**

**[CHATBOT mode]** → Load [CHATBOT_MODE.md](./references/CHATBOT_MODE.md):
Answer each confirmed target question using `neo4j-graphrag` tools (vector search, fulltext search, Cypher, read_node_image), then generate the chatbot report saved to `outputs/reports/<topic>_chatbot_report.md`.

**[ANALYTICAL mode]** → Load [ANALYTICAL_MODE.md](./references/ANALYTICAL_MODE.md):
Generate Cypher queries per use case in YAML format, validate them against the graph, then generate the analytical report saved to `outputs/reports/<topic>_report.md`.

---

## MCP Server Quick Reference

| Server | Steps | Key Tools |
|--------|-------|-----------|
| `neo4j-data-modeling` | 3 | `list_example_data_models`, `get_example_data_model`, `get_mermaid_config_str`, `validate_data_model` |
| `neo4j-ingest` | 4 | `ingest_csv_into_neo4j` |
| `neo4j-lexical-graph` | 4 | `create_lexical_graph`, `chunk_lexical_graph`, `list_documents`, `generate_chunk_descriptions`, `embed_chunks`, `check_processing_status`, `verify_lexical_graph` (spot-check, single doc only), `assign_section_hierarchy` (optional) |
| `neo4j-entity-graph` | 5–6 | `convert_schema`, `extract_entities`, `check_extraction_status` |
| `neo4j-graphrag` | 4.5–8 | `read_neo4j_cypher`, `write_neo4j_cypher`, `get_neo4j_schema_and_indexes`, `vector_search`, `fulltext_search`, `search_cypher_query`, `read_node_image` |
