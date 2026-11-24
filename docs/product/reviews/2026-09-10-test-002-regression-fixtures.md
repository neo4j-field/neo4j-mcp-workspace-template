# TEST-002 deterministic regression fixture evidence

Date: 2026-09-10

## Outcome

The retained parser modes and existing ingestion/extraction paths now have small,
deterministic fixtures for their stabilization contracts. The suite covers
PyMuPDF, Docling, page-image, structured ingest, text and visual extraction,
partial failure, forced re-extraction, and restart/retry behavior.

The restart fixture found a real defect: the extraction selection predicate did
not group text/image eligibility before appending the `force=false` skip clause.
Because `AND` binds more tightly than `OR`, every text source was reprocessed.
The predicate is now parenthesized and both unit and live tests protect it.

## Coverage

- `tests/unit/test_lexical_parser_modes.py` runs the real PyMuPDF parser and real
  page-image renderer against the existing one-page PDF. It runs the production
  Docling adapter against a deterministic in-process converter result, exercising
  page, element, reading-order, and section normalization without downloading
  model artifacts in CI.
- A local full-Docling backend smoke also parsed that PDF successfully into one
  page, two elements, and one section. This is supporting environment evidence,
  not a network/model-dependent CI assertion.
- `tests/integration/test_structured_ingest_mcp.py` retains idempotent live CSV
  node/relationship ingestion with source-column mapping and relationship
  property checks.
- `tests/integration/test_entity_extraction_coverage_mcp.py` retains deterministic
  text/Chunk and visual/Page success, valid-empty, and exhausted-failure outcomes.
  Its new restart fixture creates a fresh server instance, proves the old
  in-memory job is absent, proves `force=false` skips graph-persisted success, and
  proves `force=true` updates the same entity/provenance pair rather than
  duplicating it.
- The reusable CI workflow explicitly runs the parser-mode fixture; the existing
  entity integration module automatically includes both partial-failure and
  restart/re-extraction cases.

No model or embedding provider request is made by these deterministic fixtures.
The configured models remained `text-embedding-3-small` and `gpt-5.4-mini`.

## Verification

- Unit, contract, and report-validation tests: 35 passed.
- Live Neo4j integrations: 8 passed.
- Exact-DXT headless Desktop ingestion smoke: 1 passed.
- Five GitHub Actions workflow files parsed successfully.
- `git diff --check` passed.
- All known temporary fixture namespaces after teardown: 0 nodes.
- Retained `golden-e2e-20260910` graph after teardown: 5 nodes and 8
  relationships, unchanged.

## Boundaries and improvement feedback

This closes regression-fixture coverage, not the later semantic/recovery work.
Forced extraction is idempotent when the schema emits the same entity keys, but
removal of stale labels, properties, and relationships remains `EXT-001`.
Completed extraction provenance is sufficient for a safe skip after restart, but
job status and failure details remain in memory; durable run identity and
stage-local checkpoints remain `EXT-002`, `EXT-003`, and `WRITE-002`.

The split between a deterministic Docling adapter fixture and an optional full
backend smoke is deliberate: the adapter contract should stay fast and stable in
CI, while dependency/model installation readiness belongs in setup and release
coverage (`SETUP-003` and `REL-001`).
