# Bridge key normalization and property conflicts — 2026-11-24

## Behavior

BUG-006: `convert_schema` accepts an optional per-entity-label `key_normalization`
map. `strip` is the default and preserves case; `strip_lower` is explicit. Both
entity keys and referencing relationship endpoints receive the same policy.
Unknown labels and invalid policies fail before writing a schema file. Ontology
normalizer behavior is unchanged. CSV writers must use matching key normalization.

BUG-007: `extract_entities` accepts `property_policy`, default `preserve_existing`.
Existing non-null entity properties survive extraction, while missing properties
are filled. Explicit `overwrite` replaces existing values. Null proposals never
delete stored properties. `force` controls source selection, not property policy.
The EXTRACTED_FROM link records proposed properties as JSON, conflicting property
names, and the policy applied. Non-JSON scalar proposals use their string form.

This is a conservative source-agnostic policy, not a CSV ownership registry.
It does not introduce property-level history, relationship property protection,
or change the separate CSV writer's behavior. Existing extracted values are also
preserved by default, so authoritative refreshes must opt into overwrite.
The dynamic property SET syntax requires Neo4j 5.24 or newer.

## Verification

- 48 fast tests passed: workflow/CI/scorer 13, lexical 15, ingest 4, entity and
  generated normalization/schema 10, report validation 6.
- 9 integration checks passed against a disposable Neo4j 5.26 Enterprise:
  bridge policy/schema tests (6, including inherited file/ontology relationship
  checks), coverage/restart tests (2), ontology workflow (1).
- Bridge tests exercise CSV-first retention, missing-value fill, null protection,
  explicit overwrite, and CSV-after-extraction followed by another extraction.
- A generated schema with mixed-case response keys passes through the real typed
  response parser and real Neo4j writes, merges onto two existing CSV fixture nodes
  with no duplicates, and persists the relationship with normalized endpoints.
- Case-sensitive key preservation and invalid-label rejection have tool-level tests.
- The existing generation-replacement fixture now requests overwrite explicitly.
- CI runs the new fast and integration tests; workflow and server docs are updated.
- `git diff --check` passed. Database teardown left zero nodes; disposable container
  was removed. No tests used the owner's configured database or made model calls.

## Next live confirmation

Restart Claude Code's local entity MCP server and repeat the small three-file
fixture in an isolated test scope. Supply strip_lower for its three entity labels,
keep preserve_existing, and verify CSV action retention plus the proposed PDF action
and conflict name on EXTRACTED_FROM. Save new report filenames to retain prior runs.

## Owner's live repeat — passed

The owner repeated the complete three-file workflow under lexical namespace
`golden-e2e-20260910-ns20261124b`, preserving prior documents and reports.
Evidence was read from
`outputs/reports/golden_e2e_20260910_run_log_ns20261124b.md`.
Generated lowercase entity and endpoint validators worked without manual repairs.
The procedure retained its CSV action; the new EXTRACTED_FROM link recorded the
PDF proposal, conflict name `action`, preserve_existing policy, and gpt-6-luna.
The three-question report passed validation. Two documents/chunks share three
canonical domain entities without duplicate keys; six source links retain evidence
from both runs. This is lexical source separation with shared domain entities,
not isolation between whole graphs.

Both source copies share documentName. Equal scores are consistent with identical
content, not caused by the shared name itself. documentName alone cannot select
one run: scope retrieval to a source/version identity or verify returned chunk IDs.

create_lexical_graph.document_id is documented as a custom sourceId, and the server
adds the version suffix. A sourceId ending in _v1 therefore produces _v1_v1.
Use a bare source ID on creation and the returned version ID on later calls.
This is an API naming/documentation issue, not evidence of broken versioning.

TEST-003's scored golden candidate/baseline and BUG-004 affected-version fallback
verification remain outstanding. No database operations were performed by this
review; the live evidence comes from the owner's run.
