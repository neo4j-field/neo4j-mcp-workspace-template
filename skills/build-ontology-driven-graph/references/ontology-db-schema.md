# Ontology DB — Cypher contract

This is the schema you write to via `ontology_write_neo4j_cypher`. The `mcp-neo4j-entity-graph` server reads from this graph to compile a Pydantic extraction schema; if you don't follow the contract here, `generate_schema_from_ontology` will fail or extraction will produce garbage.

The full reference lives at `mcp-neo4j-entity-graph/docs/ONTOLOGY_DB_SCHEMA.md`. This file is the operational summary — copy these Cypher patterns directly.

## Node labels at a glance

| Label | Purpose |
|---|---|
| `:Ontology` | Top-level container. One per extraction task. |
| `:NodeType` | An entity type to extract (e.g. `Contract`, `Person`). PascalCase names. |
| `:PropertyDef` | A property on a NodeType or RelationshipType. camelCase names. |
| `:RelationshipType` | A relationship type. SCREAMING_SNAKE_CASE names. |
| `:AliasMap` | Named collection of aliases (for `alias_map` normalizer). |
| `:Alias` | One mapping `from` → `to`. |
| `:Blocklist` | Named set of terms to skip (for `blocklist` normalizer). |
| `:BlockedTerm` | One blocked value. |

## Relationships

```
(:Ontology)        -[:CONTAINS]->          (:NodeType | :RelationshipType)
(:Ontology)        -[:DEFINES]->           (:AliasMap | :Blocklist)
(:NodeType)        -[:HAS_PROPERTY]->      (:PropertyDef)
(:RelationshipType)-[:HAS_PROPERTY]->      (:PropertyDef)
(:RelationshipType)-[:FROM]->              (:NodeType)
(:RelationshipType)-[:TO]->                (:NodeType)
(:PropertyDef)     -[:USES_ALIAS_MAP]->    (:AliasMap)
(:PropertyDef)     -[:USES_BLOCKLIST]->    (:Blocklist)
(:AliasMap)        -[:HAS_ALIAS]->         (:Alias)
(:Blocklist)       -[:HAS_TERM]->          (:BlockedTerm)
```

## Hard rules (validator enforces)

- Every `:NodeType` has **exactly one** `:PropertyDef` with `is_key=true`.
- Every `:RelationshipType` has **exactly one** `:FROM` and **exactly one** `:TO`, both pointing to NodeTypes that are also `:CONTAINS`-linked from the same `:Ontology`.
- `:PropertyDef.type` is one of `STRING`, `INTEGER`, `FLOAT`, `BOOLEAN`.
- `:PropertyDef.normalizer` (if set) is one of the registry tags below.
- Parameterized normalizers must have their config: `alias_map` → `:USES_ALIAS_MAP` link; `blocklist` → `:USES_BLOCKLIST` link; `regex_normalize` → `regex_pattern` + `regex_replacement` properties; `regex_skip` → `regex_pattern`; `enum_validate` → non-empty `enum_values`; `compose_name_from_fields` → `name_template`.

## Normalizer registry

### Generic (no extra config)
| Tag | What it does |
|---|---|
| `whitespace` | Collapse internal whitespace + strip ends |
| `strip_the` | Remove leading "the " / "The " |
| `strip_acronym_suffix` | Remove trailing `(ABC)` parentheticals |
| `lowercase` / `uppercase` / `titlecase` | Case normalization |
| `email` | Lowercase + strip |
| `phone` | E.164 format |
| `url` | Lowercase domain, strip trailing slash |
| `date` | Multiple formats → ISO `YYYY-MM-DD` |
| `monetary_amount` | `"€1.3 billion"`, ranges → float |
| `percentage` | `"15%"` → float |
| `integer` | Parse int, handle commas |

### Parameterized (need extra config)
| Tag | Required config |
|---|---|
| `alias_map` | `:USES_ALIAS_MAP` link to a `:AliasMap` (which has `:HAS_ALIAS` to `:Alias` nodes) |
| `blocklist` | `:USES_BLOCKLIST` link to a `:Blocklist` (which has `:HAS_TERM` to `:BlockedTerm` nodes) |
| `regex_normalize` | `pd.regex_pattern` + `pd.regex_replacement` |
| `regex_skip` | `pd.regex_pattern` (match → skip the entity) |
| `enum_validate` | `pd.enum_values` (a non-empty list of allowed strings) |
| `compose_name_from_fields` | `pd.name_template` like `"{currency} {amount} fine"` (synthesizes the key value from other fields) |

### `__SKIP__` sentinel

Any normalizer can return the literal string `"__SKIP__"` to drop the whole entity from the extraction output. `blocklist`, `regex_skip`, and `enum_validate` use this to filter out unwanted matches.

### Chaining normalizers

A single `:PropertyDef` can have multiple normalizers run in order via the `normalizers` array (instead of the singular `normalizer` string):

```cypher
SET pd.normalizers = ['whitespace', 'titlecase', 'alias_map']
```

Order matters — the output of one feeds the next. Common chains: `whitespace → alias_map`, `titlecase → blocklist`.

## Cypher templates

Run these via `ontology_write_neo4j_cypher`. All use `MERGE` so they're idempotent — re-running won't duplicate.

### Create the ontology root

```cypher
MERGE (o:Ontology {name: $ontology_name})
  SET o.description = $description,
      o.version = "v1",
      o.created_at = datetime();
```

### Add a NodeType with a key property

```cypher
MATCH (o:Ontology {name: $ontology_name})
MERGE (nt:NodeType {name: $node_type_name})
  SET nt.description = $node_type_description
MERGE (o)-[:CONTAINS]->(nt)
MERGE (key:PropertyDef {name: $key_property_name})
  SET key.type = "STRING",
      key.description = $key_property_description,
      key.required = true,
      key.is_key = true,
      key.normalizer = "whitespace"
MERGE (nt)-[:HAS_PROPERTY]->(key);
```

### Add a regular property to an existing NodeType

```cypher
MATCH (nt:NodeType {name: $node_type_name})
MERGE (pd:PropertyDef {name: $property_name})
  SET pd.type = $property_type,
      pd.description = $property_description,
      pd.required = false,
      pd.normalizer = $normalizer_tag
MERGE (nt)-[:HAS_PROPERTY]->(pd);
```

(Replace `$normalizer_tag` with one of the registry values, or omit the `pd.normalizer` line entirely if no normalization is needed.)

### Add a RelationshipType

```cypher
MATCH (o:Ontology {name: $ontology_name})
MATCH (src:NodeType {name: $from_node_type})
MATCH (tgt:NodeType {name: $to_node_type})
MERGE (rt:RelationshipType {name: $rel_type_name})
  SET rt.description = $rel_description
MERGE (o)-[:CONTAINS]->(rt)
MERGE (rt)-[:FROM]->(src)
MERGE (rt)-[:TO]->(tgt);
```

### Add an alias map and link it to a property

```cypher
MATCH (o:Ontology {name: $ontology_name})
MATCH (pd:PropertyDef {name: $property_name})  // make sure this PropertyDef is HAS_PROPERTY-linked from a NodeType
MERGE (am:AliasMap {name: $alias_map_name})
  SET am.description = $alias_map_description
MERGE (o)-[:DEFINES]->(am)
MERGE (pd)-[:USES_ALIAS_MAP]->(am)
SET pd.normalizer = "alias_map";

// Then add the actual aliases
UNWIND $aliases AS pair
MATCH (am:AliasMap {name: $alias_map_name})
MERGE (a:Alias {from: pair.from, to: pair.to})
MERGE (am)-[:HAS_ALIAS]->(a);
```

Where `$aliases` is `[{from: "NY", to: "New York"}, {from: "N.Y.", to: "New York"}]`.

### Add a blocklist and link it to a property

```cypher
MATCH (o:Ontology {name: $ontology_name})
MATCH (pd:PropertyDef {name: $property_name})
MERGE (bl:Blocklist {name: $blocklist_name})
  SET bl.description = $blocklist_description
MERGE (o)-[:DEFINES]->(bl)
MERGE (pd)-[:USES_BLOCKLIST]->(bl)
SET pd.normalizer = "blocklist";

// Add terms
UNWIND $terms AS term
MATCH (bl:Blocklist {name: $blocklist_name})
MERGE (t:BlockedTerm {value: term})
MERGE (bl)-[:HAS_TERM]->(t);
```

### Set an enum_validate constraint

```cypher
MATCH (pd:PropertyDef {name: $property_name})
SET pd.normalizer = "enum_validate",
    pd.enum_values = $values;  // e.g. ["NDA", "MSA", "SOW", "Amendment"]
```

### Set a regex_normalize constraint

```cypher
MATCH (pd:PropertyDef {name: $property_name})
SET pd.normalizer = "regex_normalize",
    pd.regex_pattern = $pattern,         // e.g. "^\\s*Case\\s+No\\.?\\s*"
    pd.regex_replacement = $replacement; // e.g. ""
```

### Chain multiple normalizers

```cypher
MATCH (pd:PropertyDef {name: $property_name})
SET pd.normalizers = $tag_list,  // e.g. ["whitespace", "titlecase", "alias_map"]
    pd.normalizer = null;        // clear the singular field
```

(For `alias_map` or `blocklist` in a chain, the `:USES_*` link is still required.)

## Read vs write — important gate

`ontology_read_neo4j_cypher` and `documents_read_neo4j_cypher` enforce a read-only gate. The gate uses a case-insensitive whole-word regex looking for any of these seven Cypher write keywords: `MERGE`, `CREATE`, `INSERT`, `SET`, `DELETE`, `REMOVE`, `ADD`. **The check looks at the raw query text** — including comments and string literals.

Practical consequence: if you compose a read query that includes a user-facing message string like `"Set is_key=false"` or `"Add at least one"`, the gate will reject the whole query. Use synonyms in messages embedded in read queries:

| Avoid in read queries | Use instead |
|---|---|
| set | mark, specify |
| add | include, attach |
| merge | combine, consolidate |
| create | provide, define |
| delete | erase (or skip the message) |
| remove | drop, omit |
| insert | place |

Write queries (run via `ontology_write_neo4j_cypher`) have no such restriction.

## Reading back the ontology

To inspect what's currently in the Ontology DB:

```cypher
// List all ontologies
MATCH (o:Ontology) RETURN o.name, o.description, o.version

// Full structure of one ontology
MATCH (o:Ontology {name: $name})-[:CONTAINS]->(nt:NodeType)
OPTIONAL MATCH (nt)-[:HAS_PROPERTY]->(pd:PropertyDef)
RETURN nt.name, collect({name: pd.name, type: pd.type, key: pd.is_key, normalizer: pd.normalizer}) AS properties

// Relationships in one ontology
MATCH (o:Ontology {name: $name})-[:CONTAINS]->(rt:RelationshipType)
MATCH (rt)-[:FROM]->(src:NodeType), (rt)-[:TO]->(tgt:NodeType)
RETURN rt.name, src.name AS from_type, tgt.name AS to_type
```

## Deleting an ontology to start fresh

This is destructive — confirm with the user first. Run via `ontology_write_neo4j_cypher`:

```cypher
MATCH (o:Ontology {name: $name})
OPTIONAL MATCH (o)-[:CONTAINS|DEFINES]->(child)
OPTIONAL MATCH (child)-[:HAS_PROPERTY|HAS_ALIAS|HAS_TERM|FROM|TO]->(grandchild)
DETACH DELETE o, child, grandchild;
```

This leaves alias/blocklist contents (`:Alias`, `:BlockedTerm`) potentially orphaned if shared with other ontologies — in v1 they are not shared, so this is safe.
