# ONT-002: Python extraction schema → ontology export

Added `export_extraction_schema_ontology(schema_path, format="yaml")` to the entity
MCP server. The path is absolute; the returned YAML/JSON is validated with the
bundled normative Ontology Graph Spec 1.1.0 schema and the existing bounded
extraction adapter. No database or model call is required. The tool neither
creates an ontology database nor stores ontology metadata in the customer graph.

Supported contracts are generated scalar Pydantic extraction schemas: node labels,
scalar keys and property types, descriptions, requiredness, optional `None`
defaults, relationship endpoints and scalar relationship properties. Explicit
endpoint fields and the existing first-two-fields legacy contract both work.
`strip()` and `strip().lower()` key and endpoint validators are recognized by
whole-function AST matching, including generated before-mode string guards.

Exact key identity required two small normalizers, `strip` and `strip_lower`, in
the existing custom extension registry. The existing `whitespace` **and**
`lowercase` normalizers collapse internal whitespace; substituting those would
silently change identities such as `"A  B"`. Their behavior was retained. Exported
normalizers preserve internal whitespace, Unicode trimming, casing and endpoint
agreement. These normalizers add no node labels, relationships or graph properties.

This deliberately does not claim lossless conversion of arbitrary Python:
custom validators/model hooks, serializers, configuration, inheritance,
constrained or Literal/Enum values, field aliases, meaningful defaults and required
nullable fields fail with actionable class/field errors. Unknown validators are
never discarded. Rich ontology-generated helper pipelines (aliases, blocklists,
composed keys, etc.) should be exported from their source ontology using the
existing `export_ontology_spec` tool. The interchange represents JSON extraction
and graph semantics, not Python-only inputs, wrapper collection names or arbitrary
Python behavior. Loading the supplied trusted Python file executes it, matching
the existing extraction path; this is not a Python sandbox.

## Verification

Command:

```sh
LITELLM_LOCAL_MODEL_COST_MAP=True mcp-neo4j-entity-graph/.venv/bin/python -m unittest \
  tests.unit.test_schema_ontology_export tests.unit.test_ontology_spec \
  tests.unit.test_schema_preflight tests.unit.test_bridge_normalization \
  tests.synthetic.test_schemas -q
```

38 tests passed. Seven new tests cover normative YAML/JSON equality, executable
schema → ontology → regenerated-schema identity behavior, typed keys, requiredness,
relationship metadata, generated guarded validators, unsupported semantics,
endpoint-policy mismatch, absolute paths and the public MCP tool with a driver
that raises on any database access. Existing negative-path tests intentionally
emit error logs while asserting rejection.

Also exported the actual `outputs/schemas/aster_maintenance_schema.py`: four node
types, four relationship types; both outputs passed normative validation. Evidence:
`outputs/reports/python_schema_ontology_20261126/aster_maintenance_ontology.yaml`
and `.json`. These are local generated artifacts. No customer database was read
or modified and no LLM/paid call was made.

Manual Claude acceptance after loading the updated entity server: export the
existing Python schema, save the result, use it as file-backed `get_ontology`
context, and compare the maintenance question. This is an explicit supported
route; arbitrary custom Python schemas remain outside the bounded exporter.
