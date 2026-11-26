# Full synthetic smoke — 2026-11-24

Completed with findings. All **7/7 target answers passed**, the seven-record
CHATBOT report validator passed, and an independent audit passed 18 checks.

Evidence: `outputs/reports/synthetic_smoke_20261124_live_01/` contains
`chatbot_report.md`, `summary.json`, `answer_comparison.json`,
`independent_audit.json`, ordered public MCP calls, actual returned image,
reconstruction checks, sanitized logs and retained failed-attempt evidence.

Four public stdio MCP servers used fresh Neo4j 2026.09 Enterprise databases created
with neo4j-cli. Configured models were unchanged: extraction/vision `gpt-6-luna`,
embeddings `text-embedding-3-small` (1536d). Four CSVs produced 14 nodes / 20 relationships;
Docling parsed all 4 PDF pages into 50 elements / 11 sections and 8 chunks (4 text, 3 table, 1 image).
Ontology YAML imported into a separate DB generated 4 entity / 4 relationship types.
Eight sources were attempted: 7 nonempty successes, 1 successful empty, 0 failed.
Four visual descriptions and 8 embeddings succeeded; both search indexes reached ONLINE.

After extraction, domain counts/edges remained exactly 14 / 20. CSV action and Unicode
were preserved, conflicting proposals recorded, sensors retained case distinction,
and there were no duplicate keys/domain orphans. Verified 23 entity provenance links,
15 relationship claims and 8 durable successful source completions. Vector/fulltext
retrieval found relevant evidence, PageIndex tools were hidden→visible, PDF citations
were correct, full long-section pagination ended at REF-16, and the actual returned
image showed BYP-42. Expected values were compared after retrieved answers were saved.

## Findings

- Exact hierarchy remains **partial**: Docling added checklist/printed-contents
  headings at levels 5 / 4 versus the intended 3. Intended thermal-reset and repeated
  Details paths still work. SURF-004 must consider this before removing correction.
- The default neo4j-cli Docker instance omitted APOC; schema inspection failed.
  Enabled the bundled plugin in the disposable instance, restarted preserving
  data, and the same public schema tool then passed. Updated README/saved prompts
  to state the prerequisite before paid work; SETUP-005 tracks earlier checking
  or a native fallback. No product/server source code was changed in this run.
- Corrected a harness field/counter assertion after successful extraction and
  resumed without repeating provider work. Original failure retained. One initial
  harness parent lingered with zero children after saving results and was explicitly
  terminated; continuation helpers exited normally. This is not an uninterrupted
  first-try onboarding or a performance measurement.
- Manual Claude Code UX/QA-001, benchmark live execution and negative/lifecycle
  scenarios remain pending. Report completeness does not establish exact hierarchy
  correctness or universal extraction quality.

Container `synthetic-smoke-live-20261124` remains running for inspection at
`neo4j://localhost:17689`, HTTP 17489, graph `smoke-live`, ontology `smoke-ontology`.
Temporary credentials are in an owner-only file `/tmp/synthetic-smoke-live-20261124.env`;
no secret contents are in the reports. The user's configured database, .env and
MCP configs were untouched. See the chatbot report for a credential-free CLI example.
