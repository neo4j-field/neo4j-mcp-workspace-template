# ANALYTICAL MODE — Use Case Definition and Cypher Output

Used during **Step 2** (use case definition) and **Step 8** (Cypher output) of the `develop-neo4j-graph` skill when MODE = ANALYTICAL.

---

## Step 2: Use Case Definition (ANALYTICAL mode)

Work with the user to define the analytical use cases the graph should support. Use cases can be:
- Operational queries ("show all patients who have both condition X and medication Y")
- Aggregations ("how many drugs are in each therapeutic area")
- Exploratory patterns ("find the most common drug-condition co-occurrences")
- Reporting ("list all documents referencing a given entity")

Document 3–6 use cases. Each will map to one or more Cypher queries in Step 8.

During Step 3 (data modeling), verify the data model supports each defined use case. Note any use cases the model cannot address — these become known gaps.

---

## Step 8: Generate Cypher and Validate (ANALYTICAL mode)

### Generate Cypher per use case

For each use case defined in Step 2, write one or more Cypher queries. Persist them as a YAML file in `outputs/queries/<topic>_queries.yaml`.

#### YAML Format

```yaml
analytical_queries:
    use_case_key:
        name:
        cyphers:
```

#### Example

```yaml
analytical_queries:
  patient_condition_count:
    name: How many patients have each condition?
    cyphers:
      - |
        MATCH (p:Patient)-[:HAS_CONDITION]->(c:Condition)
        RETURN c.name AS condition, COUNT(p) AS patient_count
        ORDER BY patient_count DESC

  drug_condition_overlap:
    name: Which drugs are prescribed for the same condition?
    cyphers:
      - |
        MATCH (d:Drug)-[:TREATS]->(c:Condition)<-[:TREATS]-(d2:Drug)
        WHERE d <> d2
        RETURN c.name AS condition, collect(DISTINCT d.name) AS drugs
        ORDER BY size(drugs) DESC
        LIMIT 20
```

### Validate

Execute each Cypher query using `read_neo4j_cypher` from `neo4j-graphrag`. For each query:
- Confirm it returns expected results
- Check for empty or unexpectedly small result sets (may indicate missing data or schema mismatch)
- Note any gaps (missing relationships, unexpected entity counts)

### Generate Analytical Report

Save to `outputs/reports/<topic>_report.md`.

```markdown
# Graph Report — <Topic>

## Source Data
- List each source: filename/path, type (CSV/PDF), record/chunk count

## Use Cases
<List of defined use cases>

## Graph Data Model
<Mermaid diagram>
<Description of each node and relationship>

## Cypher Queries

### Use case: <name>
```cypher
<query>
```
**Results**: <summary of execution results>
**Coverage**: Full / Partial / Not answerable

[repeat for each use case]

## Extraction Quality (if PDF data present)
- Entity counts per label
- Duplicate analysis
- Entity-to-chunk link count

## Gaps and Limitations
- Use cases not addressed and why
- Schema gaps
- Missing data or relationships

## Recommended Next Steps
- Schema refinements
- Additional data sources
- Cypher optimizations
- Validator improvements (if PDF entities present)
```
