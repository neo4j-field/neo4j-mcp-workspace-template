# Examples — Manual end-to-end validation

These files exist to **validate** the ontology-as-graph flow end-to-end before building the lawyer-facing skill. Run through them manually against a real Neo4j instance.

---

## Files

- `legal_ontology.cypher` — A small but complete legal ontology that exercises every normalizer category (generic, parameterized alias_map, blocklist, regex_normalize, enum_validate, compose_name_from_fields, plus a relationship with a property).
- `validate.py` — Standalone script that connects to Neo4j, calls `setup_ontology_db()`, runs the example Cypher, and calls `generate_schema_from_ontology` programmatically (no MCP client needed).

---

## Prerequisites

1. A running Neo4j instance (local Docker, Desktop, or AuraDB)
2. Two databases: `documents` (or rename to whatever you prefer) and `ontology`
3. `.env` configured with `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, `NEO4J_DATABASE=documents`, `NEO4J_ONTOLOGY_DATABASE=ontology`, `OPENAI_API_KEY`, `EXTRACTION_MODEL`, `EMBEDDING_MODEL`

---

## Step-by-step validation

### 1. Create the two databases (if not already)

```cypher
// Run on the system DB
CREATE DATABASE documents IF NOT EXISTS;
CREATE DATABASE ontology IF NOT EXISTS;
```

(AuraDB Free supports only one user database — use one cluster for documents and a separate trial cluster for ontology, or skip this and configure to share one DB for the demo.)

### 2. Initialize the Ontology DB constraints

From a Python session in the `mcp-neo4j-entity-graph/` package:

```python
from neo4j import AsyncGraphDatabase
import asyncio
from mcp_neo4j_entity_graph.server import create_mcp_server

async def init():
    driver = AsyncGraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "password"))
    mcp = create_mcp_server(driver, database="documents", ontology_database="ontology")
    # Find and call the setup tool
    tool = await mcp.get_tool("setup_ontology_db")
    print(await tool.run({}))
    await driver.close()

asyncio.run(init())
```

OR, just run `validate.py` which does all of this.

### 3. Load the example ontology

In Neo4j Browser (connected to the `ontology` database):

```bash
:source examples/legal_ontology.cypher
```

Or via cypher-shell:
```bash
cypher-shell -u neo4j -p password -d ontology -f examples/legal_ontology.cypher
```

### 4. Verify ontology in Bloom

Open Neo4j Bloom → connect to the `ontology` database. You should see the ontology graph: `(:Ontology) -[:CONTAINS]-> (:NodeType) -[:HAS_PROPERTY]-> (:PropertyDef) -[:USES_ALIAS_MAP]-> (:AliasMap) -[:HAS_ALIAS]-> (:Alias)` etc.

Lawyers will edit this graph in Bloom — verify the structure is readable.

### 5. Generate the Pydantic schema

```python
# (continuing from above; or use validate.py)
tool = await mcp.get_tool("generate_schema_from_ontology")
result = await tool.run({"ontology_name": "legal_demo"})
print(result)
```

Expected: a JSON response with `cache_path` pointing at `~/Library/Caches/mcp-neo4j-entity-graph/schemas/legal_demo.py` (macOS), and `schema_content` containing the generated Python.

### 6. Inspect the generated file

```bash
python -m py_compile "$(python -c 'from platformdirs import user_cache_dir; print(user_cache_dir("mcp-neo4j-entity-graph"))')/schemas/legal_demo.py"
```

If this exits 0, the file is syntactically valid.

Open the file and verify:
- `OrganizationEntity`, `PartyEntity`, `ContractEntity`, `PenaltyEntity` classes exist
- `_node_label` and `_key_property` ClassVars are correct
- Each property with a normalizer in the ontology has a corresponding `@field_validator`
- `PenaltyEntity` has a `@model_validator(mode="after")` for compose_name_from_fields
- Module-level `_ALIAS_MAP_JURISDICTION_ALIASES` and `_BLOCKLIST_NOT_A_PARTY` constants are emitted
- `from mcp_neo4j_entity_graph.normalizer_runtime import ...` is at the top

### 7. Quick validator smoke test (no LLM)

```python
import importlib.util, sys
from platformdirs import user_cache_dir
from pathlib import Path

p = Path(user_cache_dir("mcp-neo4j-entity-graph")) / "schemas/legal_demo.py"
spec = importlib.util.spec_from_file_location("extraction_models", p)
mod = importlib.util.module_from_spec(spec)
sys.modules["extraction_models"] = mod
spec.loader.exec_module(mod)

# Alias_map test
contract = mod.ContractEntity(title="My Contract", jurisdiction="NY")
assert contract.jurisdiction == "New York"

# Blocklist test
party_skip = mod.PartyEntity(name="the parties")
assert party_skip.name == "__SKIP__"

# Date + monetary test
contract2 = mod.ContractEntity(title="X", signedDate="March 15, 2025", amount="€1.5 billion")
assert contract2.signedDate == "2025-03-15"
assert contract2.amount == 1500000000.0

# Compose name
penalty = mod.PenaltyEntity(amount="$500K", currency="dollar")
print(penalty.name)  # "USD 500000.0 penalty"

# Enum validate
contract3 = mod.ContractEntity(title="X", contractType="service")
assert contract3.contractType == "service"
contract4 = mod.ContractEntity(title="X", contractType="weird")
assert contract4.contractType == "__SKIP__"

print("All validators OK")
```

### 8. End-to-end with documents (full PDF flow)

After Steps 1–7 work:
1. Ingest a sample PDF via `mcp-neo4j-lexical-graph` (`create_lexical_graph`, `embed_chunks`).
2. Call `extract_entities(ontology_name="legal_demo")` — internally regenerates schema from Ontology DB and runs the LLM extraction.
3. Query the documents DB:
   ```cypher
   MATCH (n) WHERE labels(n)[0] IN ['Party', 'Contract', 'Penalty']
   RETURN labels(n)[0] AS label, count(n) AS count;
   ```
4. Confirm no `name = "__SKIP__"` nodes (those should have been filtered).
5. Confirm no `name = "the parties"` Party nodes (blocklisted).
6. Confirm `Contract.jurisdiction` values are canonical (`"New York"`, not `"NY"`).
7. Confirm `Contract.signedDate` values are ISO format.

### 9. Bloom edit loop

1. In Bloom, edit the `JURISDICTION_ALIASES` AliasMap — add a new alias (e.g. `{from: "TX", to: "Texas"}`).
2. Re-run `extract_entities(ontology_name="legal_demo")` (or just `generate_schema_from_ontology` to inspect).
3. Verify the regenerated `legal_demo.py` includes the new alias in `_ALIAS_MAP_JURISDICTION_ALIASES`.

This proves the **iteration loop** works: lawyer edits ontology in Bloom → next extraction picks up changes automatically.

---

## What "pass" looks like

All of the following must be true:

- `setup_ontology_db()` succeeds and creates 5 constraints + 1 index
- `legal_ontology.cypher` runs without errors and creates the expected nodes
- Bloom shows the ontology graph clearly
- `generate_schema_from_ontology("legal_demo")` produces a valid `.py` file
- The generated file's validators behave correctly (Step 7 smoke test)
- Full PDF extraction (Step 8) writes entities with normalized values to the documents DB
- A Bloom edit on the ontology (Step 9) is reflected in the next extraction
