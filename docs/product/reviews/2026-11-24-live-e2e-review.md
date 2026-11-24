# Claude Code live E2E review — 2026-11-24

Evidence: owner-supplied run summary and local ignored artifacts
`outputs/reports/golden_e2e_20260910_run_log.md` and validated chatbot report.
This review did not rerun database operations.

## Confirmed

- Two CSVs produced three domain nodes and two relationships with zero orphans.
- PyMuPDF produced one Document and one Chunk; reconstruction matched source text.
- Live gpt-6-luna extraction completed 1/1 chunk with zero failures, three entities,
  two extracted domain relationships, and three EXTRACTED_FROM links.
- text-embedding-3-small produced 1536-dimensional embeddings. Prefiltered vector
  index reached ONLINE; vector, filtered vector, and fulltext retrieval worked.
- Three-question chatbot report passed deterministic validation.

BUG-005 is complete for the tested live provider path. BUG-004 has current-server
live confirmation; actual affected Neo4j 2025.12.1 fallback verification remains.
TEST-003 remains open: this small smoke run is not the synthetic golden evaluator
candidate/baseline, and does not establish broader extraction quality.

## Findings and decisions

- BUG-006: explicitly configured bridge-key normalization must cover both entity
  keys and relationship endpoint keys. Do not lowercase all identifiers globally.
  The current skill already requires manual validator review, so strip-only
  generation is not established as a regression. The successful run used manual
  schema repairs and does not prove unattended schema generation is correct.
- BUG-007: extraction replaced the CSV Procedure.action with PDF wording via an
  unconditional property update. Prioritize an explicit conflict policy and
  structured-property protection; full property-level provenance can be designed
  alongside it. The observed wording was compatible, but conflicting facts would
  cause silent source-authority loss.
- Routing errors recovered on retry. Startup warm-up is a hypothesis, not a
  demonstrated cause. Capture server versions, lifecycle and driver logs before
  assigning root cause; bounded retry work relates to WRITE-002.
- pageNodeCount=0 and sourcePageCount=1 are correct for PyMuPDF. Retain LEX-001
  as done; improve presentation only if users cannot see the source-page count.
- POPULATING followed by ONLINE is expected and was honestly reported.

The run log says the database started empty. It does not independently establish
preservation of the prior fixture graph. Future runs should identify an isolated
database explicitly and write distinct report filenames to retain comparisons.
