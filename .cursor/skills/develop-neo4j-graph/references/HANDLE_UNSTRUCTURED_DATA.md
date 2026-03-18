# Handle Unstructured Data Input

Run discovery on unstructured data such as PDFs to inform the graph data modeling process.

## Discovery

* Sample data should be persisted in this project under `data/` to be ingested at a later stage. (Do not persist entire datasets unless they are under 10 rows.)
* Note there may be nested folders in the `data/` directory.
* Identify entities and relationships that exist throughout the documents and pertain to the provided use cases.

If using pre-existing structured data, ensure that there is some overlap between the entity data model and the structured data model. This overlap allows extracted entities to be merged with structured nodes and is crucial to graphs incorporating both CSVs and PDFs. Identify the **bridge node labels** and their shared key property during discovery, before ingestion.

## Ingestion — Required Tool Sequence

Use the [`neo4j-lexical-graph`](../../../../mcp-neo4j-lexical-graph/README.md) MCP server followed by the [`neo4j-entity-graph`](../../../../mcp-neo4j-entity-graph/README.md) MCP server. Always follow this sequence:

### Step 1 — Create the lexical graph (required)

Call `create_lexical_graph` with the path to the PDF folder. This creates `Document` and `Chunk` nodes in Neo4j and is required before any other lexical graph tools.

### Step 2 — Verify documents were parsed (required)

Call `list_documents` immediately after `create_lexical_graph` to confirm that all expected documents were successfully parsed and stored. If document count is zero, check the folder path and re-run before continuing.

### Step 3 — Generate embeddings (required for semantic search)

Call `embed_chunks` to generate vector embeddings on all `Chunk` nodes. Also creates a fulltext index by default. Required for `vector_search` and `fulltext_search` queries in `neo4j-graphrag`.

### Step 4 — Optional: enrich chunk metadata

These tools are optional but improve retrieval quality:

* `generate_chunk_descriptions` — adds an LLM-generated summary to each chunk; useful for descriptive search
* `assign_section_hierarchy` — detects document section headings and tags chunks with section context

### Step 5 — Extract entities (required for entity graph)

Call `extract_entities` with the Pydantic schema path from `outputs/schemas/`. This runs asynchronously in the background.

Call `check_extraction_status` repeatedly until status is `complete` before proceeding.

### Step 6 — Verify the lexical graph (recommended)

Call `verify_lexical_graph` to confirm node counts, relationship counts, and embedding coverage are as expected.

## Entity Reconciliation

After entity extraction, extracted entity nodes must be reconciled with any matching structured nodes that were ingested from CSV. Without reconciliation, bridge nodes will exist as duplicates and relationships between the lexical graph and the structured graph will not form.

Run a reconciliation check with `read_neo4j_cypher` to identify name mismatches:

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
1. **Post-process with Cypher** — add a `canonicalName` property or MERGE the extracted node into the existing structured node using a fuzzy match (e.g. `toLower() CONTAINS` or `apoc.text.similarity`)
2. **Normalize at extraction time** — adjust the Pydantic schema description to instruct the LLM to use the exact names from the structured data (include an `enum` or explicit list of valid values when the vocabulary is small and known)

> **Note on entity name normalization:** LLMs frequently produce variant forms of the same entity (e.g. "Type 2 diabetes", "Type II Diabetes", "T2DM"). Plan for this during schema design and add a post-extraction normalization step if the entity vocabulary is domain-constrained.
