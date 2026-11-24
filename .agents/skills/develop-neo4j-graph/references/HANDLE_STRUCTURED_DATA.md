# Handle Structured Data Input

Run discovery on structured data such as CSV files to inform the graph data modeling process.

## Discovery

* Sample data should be persisted as CSV data in this project under `data/` to be ingested at a later stage. (Do not persist entire datasets unless they are under 100 rows.)
* Note there may be nested folders in the `data/` directory.
* Analyze the source data by writing your own analysis scripts. Use the Python REPL and Pandas if these tools are available.
* Insights will be used to inform the graph data modeling process.

### Cross-File ID Consistency Check

Before designing the data model, spot-check that join keys are consistent across files that should be related. Mismatched IDs prevent relationships from being created and result in orphan nodes.

> **Note on large files:** Avoid loading entire CSVs into memory for this check. Sample the first N rows or read only the relevant ID column to keep the analysis fast.

```python
import pandas as pd

# Read only the join key columns to avoid loading full files
ids_a = set(pd.read_csv("data/csv/file_a.csv", usecols=["patient_id"])["patient_id"])
ids_b = set(pd.read_csv("data/csv/file_b.csv", usecols=["patient_id"])["patient_id"])

print("IDs in B not found in A:", ids_b - ids_a)
print("Overlap count:", len(ids_a & ids_b))
```

A partial overlap is expected and acceptable — not every record in one file needs a match in another. What matters is that the overlap is **non-zero** and roughly proportional to what the data represents. If the overlap is zero or unexpectedly small, the ID formats likely differ (e.g. different prefixes, numeric offsets) and the data should be repaired before ingestion rather than worked around in Cypher. Repair scripts should use absolute file paths.

## Ingestion

* Use the `neo4j-ingest` MCP server to compile and load data into Neo4j.
* Call `compile_node_ingest_query(node=...)` for each node definition, then pass
  the returned query to `ingest_csv_into_neo4j` with the node's absolute CSV path.
* Call `compile_relationship_ingest_query(data_model=..., relationship=...)` for
  each relationship definition, then pass the returned query to
  `ingest_csv_into_neo4j` with the relationship's absolute CSV path.
* Do not execute `get_node_cypher_ingest_query` or
  `get_relationship_cypher_ingest_query` output from the pinned modeling server.
  Those are compatibility drafts, not the workspace safety boundary.
* Note: each CSV file may be ingested more than once if it contains more than one node or relationship
* Always use **absolute paths** to CSV files (not relative paths)

The compiler uses each property's declared `source.column_name`, so a camelCase
graph property such as `patientId` can safely read a snake_case CSV column such as
`patient_id`. It also emits supported Neo4j scalar conversions such as `date()`,
`toInteger()`, and `toFloat()` from the declared property type. Unsafe labels,
relationship types, graph-property names, and source-column identifiers are
rejected before any database call.

Example of a corrected ingest query for a `Patient` node where the model uses camelCase but CSV uses snake_case:

```cypher
UNWIND $records AS record
MERGE (n:Patient {patientId: record.patient_id})
SET n.name      = record.name,
    n.dob       = date(record.dob),
    n.gender    = record.gender,
    n.age       = toInteger(record.age)
```

### Relationship Ingestion Safety Contract

The owned compiler enforces all of the following:

1. The `MERGE` binds the relationship to a variable.
2. Relationship properties are set on that variable, never on `start` or `end`.
3. `sourceId` and `targetId` match the actual CSV headers and node key types.
4. Labels, relationship types, and property identifiers came from the validated
   data model rather than user-provided free text.

For example, it generates this assignment-query shape:

```cypher
UNWIND $records AS record
MATCH (start:Person {personId: record.sourceId})
MATCH (end:Project {projectId: record.targetId})
MERGE (start)-[relationship:ASSIGNED_TO]->(end)
SET relationship.role = record.role
```

It never generates the known-bad upstream shape:

```cypher
MERGE (start)-[:ASSIGNED_TO]->(end)
SET end += {role: record.role}
```
