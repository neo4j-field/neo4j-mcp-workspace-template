# SE POC simplification decisions — 2026-11-24

Timeboxed planning review, not a rewrite of tested behavior. The template helps SEs
quickly create a graph and offers readable code to reuse in customer POCs. Keep the
correctness fixes already paid for; simplify what a new user must understand.

| Decision | What it means |
|---|---|
| **Keep** tested bug fixes | Preserve normalization, structured-value precedence, visible extraction failures, successful-run checks, scoped owned replacement, embedding identity, schema validation and regression tests. No speculative removal of working safeguards. |
| **Keep** a short common path | Setup → select use case/questions → model → CSV/PDF ingestion → extraction → verify/report. Expose parser choice, conflict policy, rebuild scope and privilege errors when they affect the SE's decision. |
| **Keep** N1 and N4 before release | Owner-selected features. Native Docling hierarchy and validated Ontology Graph Spec interchange must fit existing parsing/extraction paths; no new registry/orchestrator. |
| **Move to Internals** | Contribution claims, ownership reconciliation, publication locks, exact embedding fingerprints, cache invalidation and detailed concurrency mechanics. Keep actionable user-facing consequences in the common path. Documentation movement is a separate small edit; this review changes no behavior. |
| **Keep visible** reset and parser guidance | Provide an explicit start-fresh/rebuild recipe, effects and verification. Link the [existing parser table](../../../.agents/skills/develop-neo4j-graph/references/HANDLE_UNSTRUCTURED_DATA.md#parse-mode-guide); include cost/structure/visual tradeoffs instead of duplicate instructions. |
| **Narrow** unfinished bug IDs | EXT-003 verifies implemented minimum provenance. SEC-001 targets lexical deletion prefix collisions; WRITE-004 targets lexical reserved metadata. Existing entity/ingest protections are not tasks to rebuild. |
| **Defer** production architecture | Full historical property provenance, universal resumability/checkpoints, cross-server ledgers, queues/backpressure redesign, external image storage and large-scale streaming. Reopen only for a measured POC blocker. |
| **Defer** broad rewrites/distribution migration | Do not refactor shared infrastructure or rewrite commit history for appearance. Keep future slices reviewable. Align the shipped DXT now; MCPB migration waits for scope, not supposed upstream instability. |

Release evidence is finite: final-revision hosted CI, real clean setup with mandatory
Docling costs, combined live CSV+PDF after N1/N4, aligned Desktop package smoke,
real restricted-user onboarding and a synthetic 10k-row CSV + 50-page PDF baseline.
Existing local [81 fast / 56 DB checks](2026-11-24-parallel-hardening.md) are retained,
with their limitations explicit in the [release checklist](../RELEASE_CHECKLIST.md).

Four planning groups replace the former production-heavy P0 list: release commitments,
next SE experience improvements, feature pipeline and deferred architecture.
N2/N3/N5/N6 remain preserved candidates rather than implicit release scope.
