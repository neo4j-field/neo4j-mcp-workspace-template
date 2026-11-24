# Golden extraction and original-version fallback — 2026-11-24

## TEST-003

Added a real-extractor runner for the existing synthetic three-note reference.
It sends only source text and the extraction schema to the configured model;
expected entities/relationships are scored locally, with no model judge. It makes
no Neo4j writes. Failed source extraction aborts instead of producing a candidate.
Existing output filenames are protected; comparisons verify schema/reference hashes.

Two real runs using configured gpt-6-luna each returned four expected entities and
two expected relationships across the three notes, with no extra facts. Entity and
relationship precision, recall and F1 were each 1.0; all repeat deltas were 0.0.
The scheduled-but-not-completed inspection and empty-output cases also passed.

Observed candidates and scores are retained in
`tests/golden/baselines/20261124_gpt6_luna_{baseline,repeat,scores}.json`, including
model, UTC timestamp and schema/reference hashes. These are extraction outputs,
not the reference copied into a candidate. The reference predates these runs;
it was not changed to fit the results. It was prepared during agent-assisted
repository development; no independent human domain review is asserted here.
This is a small regression seed, not a representative quality benchmark.

Runner/scorer/schema tests (6) and workflow/release/scorer tests (13, with scorer
overlap) passed. CI tests the runner with stubs; live provider requests remain
explicit runs. New provider calls can incur normal charges.

## BUG-004

Started a disposable `neo4j:2025.12.1-enterprise` container and confirmed server
version 2025.12.1 via dbms.components (the procedure also reports Cypher versions).
A new integration regression exercised the real embed_chunks tool, embedding
persistence, index creation/verification, repair, and vector retrieval. Only the
provider embedding output was stubbed to a deterministic three-dimensional vector.

- Default prefilter properties documentName and type produced the original
  unsupported single-stage-filtering error (51N26).
- The tool successfully created a plain index and honestly reported plain mode
  and ONLINE/POPULATING state.
- After deliberately dropping that fixture index, a second embed_chunks call
  returned zero newly embedded nodes and repaired the index.
- The index reached ONLINE and real vector search returned the fixture at score 1.
- The new exact-version integration check passed and is now a separate job in the
  reusable CI release gate.

Fixture teardown left zero nodes; the disposable container was removed. No checks
used or modified the owner's configured graph. The existing unit tests cover both
creation paths failing and missing-index verification failures; current-server
prefiltered behavior also has the owner's live workflow evidence.

Next: review EXT-001 stale generated data and EXT-002 skip/run identity semantics.
