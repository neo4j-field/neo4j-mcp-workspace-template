# EXT-004 — extraction schema validation — 2026-11-24

## Result

Added a shared fail-fast extraction schema contract for modeling conversion,
file-based Pydantic schemas and ontology compilation. Unsupported schemas fail
before document DB selection/invalidation/writes or provider calls. Ontology
metadata is necessarily read first; invalid ontology compilation does not publish
an executable cache/schema or start source extraction.

Validation covers duplicate labels/types/properties, safe identifiers and reserved
metadata names, absent relationship references, unsupported scalar types and Python
annotations, output-wrapper completeness, exactly one ontology key, required/non-null
key definitions (with the existing composed-key convention), and matching endpoint
key names/types/Literal domains/Field metadata constraints. Generated required
properties are no longer accidentally made optional. Generated class/output/endpoint
name collisions fail before producing overwritten Python definitions.

The typed parser previously stringified endpoint keys while numeric entities kept
native values. It now preserves native scalar types, including integer zero and
boolean false; explicit generated endpoint bindings remove reliance on field order.
Validated older first-two-endpoint layouts remain supported. Required relationship
properties are no longer mistaken for endpoints. Missing entity/endpoint keys and
invalid scalar validator returns fail visibly rather than disappearing as empty
successful output. Explicit normalizer SKIP semantics remain intact.

Descriptions/docstrings and enum values are safely quoted during generation.
A bounded AST check rejects repeated top-level class names and repeated direct
annotated fields before execution, while allowing annotation-plus-default patterns
and inherited fields. Native Python serialization is used before runtime guards;
Enum values are deliberately unwrapped, while temporal validator returns and
non-finite floats cannot be JSON-coerced to strings/null and silently accepted.

## Verification

- `tests.unit.test_schema_preflight`: 16 tests passed, including table-driven invalid
  schemas; wrapper/binding errors; zero/false keys; required/reordered relationship
  properties; Literal compatibility; composed keys; exactly-one ontology key;
  source/model-call denial for invalid schemas; quoted data descriptions;
  duplicate-declaration AST guards; inheritance/default compatibility; Enum storage;
  and invalid native validator-return checks.
- Existing entity/identity/bridge/golden tests: 15 passed (31 combined fast tests).
- `tests.integration.test_schema_preflight_mcp`: 2 passed against the parent-provided
  disposable Neo4j 5.26 service. Real Cypher matched native integer-zero and
  boolean-false keys; a bad validator return failed without replacing the prior
  owned graph. Fixture teardown removes only Ext004 labels/records.
- No real model/provider calls or operations on the configured user graph.

## Deliberate boundary

"Key constraints" here means the static extraction contract: a single key field,
its required/nullability/type/domain constraints, and compatible relationship
endpoints. This does not inspect or create existing Neo4j DDL uniqueness, existence,
type, or composite constraints; it does not prove arbitrary Python validator logic
or solve concurrent MERGE uniqueness. Those database/write concerns remain separate
hardening work. Unsupported native temporal/array/map annotations are refused rather
than guessed as STRING. Custom schemas using those old silent fallbacks must choose
supported scalar representations or wait for explicit support.

## Integration

New CI modules: `tests.unit.test_schema_preflight` and
`tests.integration.test_schema_preflight_mcp` (parent owns workflow registration).
