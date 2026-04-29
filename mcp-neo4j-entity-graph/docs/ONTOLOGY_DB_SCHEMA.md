# Ontology DB — Graph Schema Contract

This document specifies the Neo4j graph schema for the **Ontology DB** — a separate Neo4j database that stores extraction ontologies as graph data. The `mcp-neo4j-entity-graph` server reads from this database to generate Pydantic extraction schemas on demand.

The Ontology DB is the **single source of truth** for extraction ontologies. The generated Pydantic `.py` files are derived artifacts cached server-side; the Ontology DB is what's versioned, edited (via Bloom or Cypher), and shared across users.

---

## Node labels

### `:Ontology`
A named extraction ontology. One Ontology aggregates the entity types, relationships, alias maps, and blocklists used together for a specific extraction task or matter.

| Property | Type | Required | Description |
|---|---|---|---|
| `name` | STRING | yes | Unique identifier (e.g. `"legal_contracts"`, `"ec_press_corner"`) |
| `description` | STRING | no | Free-text description |
| `version` | STRING | no | Version label (e.g. `"v1"`, `"2026-04"`) — single-version per ontology in v1; full versioning is post-demo |
| `created_at` | STRING (ISO date) | no | Creation timestamp |

### `:NodeType`
An entity type to extract (e.g. `Person`, `Contract`, `Organization`).

| Property | Type | Required | Description |
|---|---|---|---|
| `name` | STRING | yes | Node label in PascalCase (e.g. `"Contract"`) |
| `description` | STRING | yes | Description used to guide LLM extraction |

### `:PropertyDef`
A property on a `:NodeType` or `:RelationshipType`.

| Property | Type | Required | Description |
|---|---|---|---|
| `name` | STRING | yes | Property name in camelCase (e.g. `"jurisdiction"`) |
| `type` | STRING | yes | Neo4j type: `STRING`, `INTEGER`, `FLOAT`, `BOOLEAN` |
| `description` | STRING | no | LLM extraction hint |
| `required` | BOOLEAN | no | Whether the property is required (default: false) |
| `is_key` | BOOLEAN | no | Whether this is the entity's key property (exactly one per `:NodeType`) |
| `normalizer` | STRING | no | Normalizer tag — see normalizer registry below |
| `regex_pattern` | STRING | no | For `regex_normalize` / `regex_skip` normalizers |
| `regex_replacement` | STRING | no | For `regex_normalize` only |
| `enum_values` | LIST<STRING> | no | For `enum_validate` normalizer |
| `name_template` | STRING | no | For `compose_name_from_fields` model validator (e.g. `"{currency} {amount} fine"`) |

### `:RelationshipType`
A relationship type between two `:NodeType`s.

| Property | Type | Required | Description |
|---|---|---|---|
| `name` | STRING | yes | Relationship type in SCREAMING_SNAKE_CASE (e.g. `"PARTY_TO"`) |
| `description` | STRING | yes | LLM extraction hint |

### `:AliasMap`
A named collection of aliases. Used by the `alias_map` parameterized normalizer.

| Property | Type | Required | Description |
|---|---|---|---|
| `name` | STRING | yes | Identifier (e.g. `"ORG_ALIASES"`) |
| `description` | STRING | no | What this map canonicalizes |

### `:Alias`
A single alias entry: maps `from` (raw form) → `to` (canonical form).

| Property | Type | Required | Description |
|---|---|---|---|
| `from` | STRING | yes | Raw value as it appears in documents (e.g. `"EC"`) |
| `to` | STRING | yes | Canonical value (e.g. `"European Commission"`) |

### `:Blocklist`
A named collection of terms that should cause an entity to be skipped (return `__SKIP__` from the validator).

| Property | Type | Required | Description |
|---|---|---|---|
| `name` | STRING | yes | Identifier (e.g. `"ORG_BLOCKLIST"`) |
| `description` | STRING | no | What this blocklist excludes |

### `:BlockedTerm`
A single blocked term.

| Property | Type | Required | Description |
|---|---|---|---|
| `value` | STRING | yes | The blocked value (case-sensitive match) |

---

## Relationships

```
(:Ontology)        -[:CONTAINS]->          (:NodeType)
(:Ontology)        -[:CONTAINS]->          (:RelationshipType)
(:Ontology)        -[:DEFINES]->           (:AliasMap)
(:Ontology)        -[:DEFINES]->           (:Blocklist)

(:NodeType)        -[:HAS_PROPERTY]->      (:PropertyDef)
(:RelationshipType)-[:HAS_PROPERTY]->      (:PropertyDef)
(:RelationshipType)-[:FROM]->              (:NodeType)
(:RelationshipType)-[:TO]->                (:NodeType)

(:PropertyDef)     -[:USES_ALIAS_MAP]->    (:AliasMap)
(:PropertyDef)     -[:USES_BLOCKLIST]->    (:Blocklist)

(:AliasMap)        -[:HAS_ALIAS]->         (:Alias)
(:Blocklist)       -[:HAS_TERM]->          (:BlockedTerm)
```

**Cardinality notes:**
- A `:NodeType` has exactly one `:PropertyDef` with `is_key=true` (the entity's merge key).
- A `:RelationshipType` has exactly one `:FROM` and one `:TO` `:NodeType`.
- A `:PropertyDef` can use at most one `:AliasMap` and at most one `:Blocklist` (multiple alias maps not supported in v1 — combine into a single `:AliasMap` if needed).
- Reusing alias maps and blocklists across properties is encouraged: define `ORG_ALIASES` once, link multiple `:PropertyDef`s to it.

---

## Normalizer registry

The `normalizer` property on `:PropertyDef` selects how the property value is normalized before being written to Neo4j during extraction. Valid values:

### Generic (no extra config needed)
| Tag | Effect |
|---|---|
| `whitespace` | Collapse internal whitespace + strip |
| `strip_the` | Remove leading "the " / "The " |
| `strip_acronym_suffix` | Remove trailing `(ABC)` parentheticals |
| `lowercase` | Lowercase |
| `uppercase` | Uppercase |
| `titlecase` | Title Case |
| `email` | Lowercase + strip |
| `phone` | E.164 normalization (strips formatting) |
| `url` | Lowercase domain, strip trailing slash |
| `date` | Multiple formats → ISO `YYYY-MM-DD` |
| `monetary_amount` | `"€1.3 billion"`, ranges → float |
| `percentage` | `"15%"` → float |
| `integer` | Parse int, handle commas |

### Parameterized (require additional config)
| Tag | Required config |
|---|---|
| `alias_map` | `:USES_ALIAS_MAP` relationship to an `:AliasMap` |
| `blocklist` | `:USES_BLOCKLIST` relationship to a `:Blocklist` |
| `regex_normalize` | `regex_pattern` + `regex_replacement` properties |
| `regex_skip` | `regex_pattern` property — match → `__SKIP__` |
| `enum_validate` | `enum_values` property — value not in list → `__SKIP__` |
| `compose_name_from_fields` | `name_template` property (e.g. `"{currency} {amount} fine"`) — applied as a `model_validator(mode="after")` to synthesize a missing name |

### `__SKIP__` sentinel
When any normalizer returns the string literal `"__SKIP__"`, the entity is dropped from the extraction output. This handles cases like person names without a surname, blocked terms, or values failing enum validation.

---

## Constraints

These are created by the `setup_ontology_db()` MCP tool (idempotent — safe to call multiple times):

```cypher
CREATE CONSTRAINT ontology_name_unique IF NOT EXISTS
  FOR (o:Ontology) REQUIRE o.name IS UNIQUE;

CREATE CONSTRAINT node_type_name_unique IF NOT EXISTS
  FOR (nt:NodeType) REQUIRE nt.name IS UNIQUE;

CREATE CONSTRAINT relationship_type_name_unique IF NOT EXISTS
  FOR (rt:RelationshipType) REQUIRE rt.name IS UNIQUE;

CREATE CONSTRAINT alias_map_name_unique IF NOT EXISTS
  FOR (am:AliasMap) REQUIRE am.name IS UNIQUE;

CREATE CONSTRAINT blocklist_name_unique IF NOT EXISTS
  FOR (bl:Blocklist) REQUIRE bl.name IS UNIQUE;

CREATE INDEX property_def_name IF NOT EXISTS
  FOR (pd:PropertyDef) ON (pd.name);
```

Note: `:NodeType` uniqueness is global in v1 (one Ontology DB = one ontology focus). For shared multi-ontology DBs, this constraint should be scoped per-ontology.

---

## Complete example (excerpt from a legal ontology)

```cypher
// Create the ontology
MERGE (o:Ontology {name: "legal_contracts"})
  SET o.description = "Contract analysis ontology",
      o.version = "v1",
      o.created_at = datetime();

// Create an alias map (reusable across properties)
MERGE (am:AliasMap {name: "JURISDICTION_ALIASES"})
  SET am.description = "Jurisdiction canonicalization";
MERGE (o)-[:DEFINES]->(am);

UNWIND [
  {from: "NY", to: "New York"},
  {from: "N.Y.", to: "New York"},
  {from: "CA", to: "California"}
] AS pair
MERGE (a:Alias {from: pair.from, to: pair.to})
MERGE (am)-[:HAS_ALIAS]->(a);

// Create a NodeType with a key property + a normalized property
MERGE (nt:NodeType {name: "Contract"})
  SET nt.description = "A binding agreement between parties";
MERGE (o)-[:CONTAINS]->(nt);

MERGE (key:PropertyDef {name: "title"})
  SET key.type = "STRING",
      key.description = "Contract title or heading",
      key.required = true,
      key.is_key = true,
      key.normalizer = "whitespace";
MERGE (nt)-[:HAS_PROPERTY]->(key);

MERGE (jur:PropertyDef {name: "jurisdiction"})
  SET jur.type = "STRING",
      jur.description = "Governing jurisdiction",
      jur.normalizer = "alias_map";
MERGE (nt)-[:HAS_PROPERTY]->(jur);
MERGE (jur)-[:USES_ALIAS_MAP]->(am);

MERGE (sd:PropertyDef {name: "signedDate"})
  SET sd.type = "STRING",
      sd.description = "Date the contract was signed",
      sd.normalizer = "date";
MERGE (nt)-[:HAS_PROPERTY]->(sd);

// Create a RelationshipType
MERGE (party:NodeType {name: "Party"})
  SET party.description = "A natural or legal person who is a party to a contract";
MERGE (o)-[:CONTAINS]->(party);

MERGE (pkey:PropertyDef {name: "name"})
  SET pkey.type = "STRING",
      pkey.required = true,
      pkey.is_key = true,
      pkey.normalizer = "whitespace";
MERGE (party)-[:HAS_PROPERTY]->(pkey);

MERGE (rt:RelationshipType {name: "PARTY_TO"})
  SET rt.description = "Connects a Party to a Contract they are bound by";
MERGE (o)-[:CONTAINS]->(rt);
MERGE (rt)-[:FROM]->(party);
MERGE (rt)-[:TO]->(nt);
```

---

## How it's consumed

The `generate_schema_from_ontology(ontology_name)` MCP tool:
1. Queries the Ontology DB for the named `:Ontology` and walks its `CONTAINS` relationships.
2. Builds an in-memory `ExtractionSchema` (existing model from `models.py`).
3. Builds a parallel `dict` of normalizer configs keyed by `"<NodeType>.<PropertyDef>"`.
4. Calls `generate_extraction_models_code(schema, normalizers)` to produce the Pydantic `.py` source.
5. Writes the result to a platformdirs cache (one file per ontology, overwritten on each call).
6. Returns the file path + content inline.

The cached `.py` is then loaded by `extract_entities` via `importlib` (existing mechanism — no change).
