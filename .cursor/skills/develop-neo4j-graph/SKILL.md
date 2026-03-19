---
name: develop-neo4j-graph
description: Develop Neo4j graphs end-to-end: analyze source data, design data models, ingest data, and validate with Cypher queries. Use when importing data to Neo4j, designing graph data models, creating knowledge graphs, or working with the Neo4j Data Modeling MCP server.
---

# Develop Neo4j Graph

## Progress Checklist

Copy this checklist to track progress:

```
- [ ] Step 1: Run discovery on sample of source data
- [ ] Step 2: Iteratively design the graph data model
- [ ] Step 3: Ingest source data according to finalized data model
- [ ] Step 3.5: Verify ingestion counts match source data
- [ ] Step 4: Generate Cypher according to use cases
- [ ] Step 5: Validate that graph adequately addresses use cases
```

## 1. Run discovery on sample of source data

* Read samples of source data provided by the user. These may be tables or unstructured data from PDFs or websites.
* Assess whether the use cases provided by the user apply to the source data.
  * Use cases should always be provided, unless the user is only interested in simply exploring graph.
* Reference [HANDLE_STRUCTURED_DATA.md](./references/HANDLE_STRUCTURED_DATA.md) for guidance on handling structured source data
* Reference [HANDLE_UNSTRUCTURED_DATA.md](./references/HANDLE_UNSTRUCTURED_DATA.md) for guidance on handling unstructured source data


## 2. Iteratively Design The Graph Data Model

Reference the process contained in [GRAPH_DATA_MODELING_MCP.md](./references/GRAPH_DATA_MODELING_MCP.md) to develop the graph data model.

When handling both structured and unstructured data, design and validate **four distinct sub-models**, each visualized separately with `get_mermaid_config_str`:

1. **Structured data model** — nodes and relationships derived from CSVs/structured sources only; validated by the data modeling MCP server
2. **Entity extraction model** — a focused subset of nodes (and relationships between them) to be extracted from documents; this is NOT the full unified model. Only include entity types that are meaningful to extract from text and that will bridge back to the structured graph. Validated by the data modeling MCP server.
3. **Lexical graph model** — `Document → Chunk` graph created by `neo4j-lexical-graph`; no design needed, it is provided by the server
4. **Unified model** — combines all three layers; show explicitly how extracted entities connect to structured nodes (e.g. `Condition` extracted from `Chunk` linking to `Condition` from patient CSV via shared `name` key)

When designing the entity extraction model, identify which structured node labels will serve as **bridge nodes** — nodes that exist in both the structured graph and will be extracted from documents via MERGE on a shared key property (e.g. `name`). The bridge node key property values must be normalized to match between the two sources.

## 3. Ingest source data according to finalized data model

Use the provided MCP servers in this project to ingest both structured and unstructured data.

* Reference [HANDLE_STRUCTURED_DATA.md](./references/HANDLE_STRUCTURED_DATA.md) for guidance on handling structured source data
* Reference [HANDLE_UNSTRUCTURED_DATA.md](./references/HANDLE_UNSTRUCTURED_DATA.md) for guidance on handling unstructured source data

## 3.5 Verify ingestion counts match source data

After all nodes and relationships are ingested, run a count check for every node label and key relationship type using `read_neo4j_cypher`:

```cypher
MATCH (n:NodeLabel) RETURN COUNT(n) AS count
```

For each node, verify:
- The count matches the number of rows in the source CSV (accounting for deduplication)
- No orphan nodes exist (nodes with no relationships when relationships are expected)

For orphan checks use:
```cypher
MATCH (n:NodeLabel) WHERE NOT (n)--() RETURN COUNT(n) AS orphans
```

If orphans are found, check for cross-file ID mismatches before proceeding to Step 4.

## 4. Generate Cypher according to use cases defined during discovery

* Each use case should have one or more Cypher queries attached to it that provide the appropriate context
* These Cypher queries should be persisted in a yaml file that follows this format

### YAML Format
```yaml
analytical_queries:
    use_case_key:
        name:
        cyphers:
```

### Example Analytical Cypher YAML
```yaml
analytical_queries:
  apple_count:
    name: How many apples are in the basket?
    cyphers:
      - MATCH (a:Apple)-[:IN_BASKET]->(b:Basket {id: $basketId}) RETURN COUNT(*)
  
  apple_and_basket_counts:
    name: How many apples are there and how many baskets are there?
    cyphers:
      - |
        MATCH (a:Apple) 
        WITH DISTINCT a
        RETURN COUNT(*) as apple_count
      - |
        MATCH (b:Basket) 
        WITH DISTINCT b
        RETURN COUNT(*) as basket_count
```

## 5. Validate that graph adequately addresses the use cases
* Use the Cypher MCP Server to execute the analytical Cypher queries against the Neo4j database
* Analyze the results and ensure that they are addressing the original use cases

## 6. Generate Report
A final report should be presented to the end user. This will include the following details.
* Source data and descriptions
* Use cases defined for the application
* Final graph data model and descriptions of each node and relationship
* Cypher queries that address the use cases and descriptions of each query
* Any gaps in the final application due to
  * Missing source data
  * Inadequate Cypher
  * Unclear use cases
  * Any additional reasons
* Final summary of the state of the application with direction for next steps
