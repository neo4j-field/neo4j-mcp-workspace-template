# Neo4j Ingest MCP Server

This server is an extension of the Labs Cypher MCP server.

It is used to ingest local structured data in CSV format into Neo4j.

The workspace-owned query compiler is the required safety boundary between a
validated graph model and CSV execution:

- `compile_node_ingest_query` honors property `source.column_name` mappings and
  declared scalar types.
- `compile_relationship_ingest_query` binds the relationship variable, resolves
  endpoint keys from the data model, and writes relationship properties only to
  that variable.
- Both compiler tools reject unsafe labels, relationship types, property names,
  and source-column identifiers before any query reaches Neo4j.
- `ingest_csv_into_neo4j` executes a compiled query against an absolute CSV path.

The pinned data-modeling server's ingest-query helpers are compatibility drafts;
do not pass those drafts directly to `ingest_csv_into_neo4j`.

