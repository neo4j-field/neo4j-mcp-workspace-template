# Handle Unstructured Data Input

Run discovery on unstructured data such as PDFs to inform the graph data modeling process.

## Discovery
* Sample data should be persisted in this project under `data/` to be ingested at a later stage. (Do not persist entire datasets unless they are under 10 rows.)
* Note there may be nested folders in the `data/` directory.
* Identify entities and relationships that exist throughout the documents and pertain to the provided use cases.

If using pre existing structured data, ensure that there is some overlap between the entity data model and structured data data model. 
This allows the structured data to be connected to the lexical graph and is crucial to graphs incorporating both structured data such as CSVs and unstructured data like PDFs.

## Ingestion

Use the [`neo4j-lexical-graph`](../../../../mcp-neo4j-lexical-graph/README.md) MCP server to ingest unstructured data like PDFs.

This server provides tools to:
1. **Extract text from PDFs** and split into token-based chunks
2. **Create a lexical graph** in Neo4j with Document and Chunk nodes
3. **Batch process folders** of PDFs with optional metadata
4. **Generate embeddings** for semantic search (via LiteLLM - 100+ providers)
5. **Create fulltext indexes** for keyword search

Then use the [`neo4j-entity-graph`](../../../../mcp-neo4j-entity-graph/README.md) MCP server to create an entity graph from lexical graph nodes.