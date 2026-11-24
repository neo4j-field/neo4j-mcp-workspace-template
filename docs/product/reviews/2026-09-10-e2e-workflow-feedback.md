# End-to-End Golden Workflow Feedback - 2026-09-10

## Outcome

A minimal real CHATBOT workflow completed end to end against the configured Neo4j MCP servers using both CSV and PDF. The successful final graph remains in place under the unique namespace `golden-e2e-20260910` for inspection. All three target questions returned complete answers.

## Workflow and fixtures

1. Pre-flight: verified `.env` exists without printing credentials and called `list_example_data_models` successfully.
2. Discovery: inspected two CSV fixtures and one generated, visually verified one-page PDF. Cross-file `product_name` overlap was exactly one.
3. Use case: fixed MODE to CHATBOT with three explicit questions covering structured lookup, semantic retrieval, and cross-layer traversal.
4. Modeling: consulted the supply-chain example; validated and visualized structured, extraction, lexical, and unified submodels. Persisted all four JSON models. After live schema inspection, corrected the provisional lexical relationship from `FROM_DOCUMENT` to actual `PART_OF`, then revalidated/revisualized the affected models.
5. CSV ingest: used generated node/relationship drafts as input, corrected snake-case source mappings and integer casts, and bound relationship variables before calling `ingest_csv_into_neo4j` five times.
6. PDF lexical graph: used `pymupdf` text-only mode, job `bd61481f40aa`; parsed one file/one page to one 134-token chunk. Structural verification passed with no issues.
7. Embedding: called `embed_chunks` with no parameters as required. It used configured `text-embedding-3-small`, embedded one chunk at 1,536 dimensions, and created `chunk_text_embedding` plus `chunk_text_fulltext`.
8. Schema/extraction: converted the extraction model to Pydantic, strengthened name and relationship-endpoint validators to `strip().lower()`, and smoke-tested them. Job `5c014e0265da` used configured `gpt-5.4-mini`; 1/1 chunk succeeded with 3 entities, 2 domain relationships, and 3 source links.
9. Verification/retrieval: verified counts, orphans, duplicates, bridge reconciliation, source links, vector retrieval, full-text retrieval, and three executed Cypher answers.
10. Reporting: generated the chatbot report and ran the deterministic CLI validator with three expected records and PDF presence.

Fixtures:

- `data/csv/golden_e2e_20260910_products.csv` - 1 product/facility row.
- `data/csv/golden_e2e_20260910_procedures.csv` - 1 procedure/product row.
- `data/pdf/golden_e2e_20260910_maintenance_note.pdf` - 1 text-heavy page.

## Tools and skills used

- Skills: `develop-neo4j-graph` plus its structured, unstructured, data-modeling, PyMuPDF, and CHATBOT references; `pdf` for fixture creation and render QA.
- MCP servers: `neo4j-data-modeling`, `neo4j-ingest`, `neo4j-lexical-graph`, `neo4j-entity-graph`, and `neo4j-graphrag`.
- Local verification: bundled ReportLab/Poppler/pdfplumber runtime, Pydantic schema smoke test, report-validator unit/contract tests, and `neo4j-validate-report`.

## Results and graph counts

| Graph item | Count |
|---|---:|
| `GoldenE2EProduct` | 1 |
| `GoldenE2EFacility` | 1 |
| `GoldenE2EProcedure` | 1 |
| fixture `Document` | 1 |
| fixture `Chunk` | 1 |
| `GOLDEN_MADE_AT` | 1 |
| `GOLDEN_HAS_PROCEDURE` | 1 |
| `GOLDEN_PRODUCT_USES_PROCEDURE` | 1 |
| `GOLDEN_PROCEDURE_OWNED_BY_FACILITY` | 1 |
| fixture `EXTRACTED_FROM` | 3 |
| fixture `PART_OF` | 1 |

The document and chunk are active; the chunk is embedded and has no orphan condition. Each structured label has exactly one normalized fixture key, so extraction merged with the CSV bridge nodes rather than duplicating them. Extraction provenance records only `gpt-5.4-mini` and pass type `full`.

## Target-question answers

1. Aurora filament is basalt composite, lists 2,400 annual units, and is made at northstar works.
2. At 72 degrees Celsius, technicians perform thermal reset: pause 12 minutes, inspect CV-7, then resume. Vector retrieval found the source chunk at 0.8061 and Cypher confirmed the extracted properties.
3. Northstar works is both the product's manufacturing facility and the owner of its PDF-extracted thermal-reset procedure.

## Validator and tests

The mandatory command `uv run --project mcp-neo4j-proxy neo4j-validate-report outputs/reports/golden_e2e_20260910_chatbot_report.md --type chatbot_report --expected-records 3 --pdf-data-present` exited 0 with `valid: true`, 3 expected records, 3 records found, and no errors. The six report-validator unit tests and eight workflow-contract tests also passed. The schema compiles and normalization behavior passed under the bundled Python runtime.

## Failures and retries

- A combined verification Cypher omitted aliases in later `UNION` branches. Neo4j rejected it before writes; the corrected query returned all expected counts and zero structured orphans.
- The first local schema-instantiation check used system Python, which lacks Pydantic. `py_compile` succeeded; rerunning with the bundled runtime passed. The extraction MCP independently imported the schema and completed.
- Poppler rendered the PDF successfully but emitted noisy Fontconfig cache/config warnings in the sandbox. The resulting PNG was inspected at original resolution and had no clipping, overlap, or broken glyphs.
- A redundant final validator rerun could not open uv's global cache inside the filesystem sandbox. The identical command was rerun with the already approved `uv run` scope and passed unchanged.
- The provisional lexical model used `FROM_DOCUMENT`; live schema showed the writer uses `PART_OF`. Saved lexical/unified models were corrected, revalidated, and re-visualized before reporting.
- No graph cleanup/retry was required; no unrelated graph data was deleted.

## Usability feedback and prioritized improvements

1. **P0 - proposed `INGEST-001`: generate executable safe ingest Cypher from source metadata.** The data-modeling drafts ignored declared CSV column mappings (`record.name` rather than `record.product_name`) and did not bind relationship variables. The current skill warning prevented a bad write, but every workflow should not require manual query surgery.
2. **P0 - `LEX-001`: make document/page accounting consistent.** The lexical job and PDF both report one page, while `list_documents` and lexical verification report zero graph pages in PyMuPDF text mode. If zero is intentionally the count of `Page` nodes, rename the field or expose both source page count and graph page-node count.
3. **P0 - `EMB-001`: persist inspectable embedding identity.** The tool response proves `text-embedding-3-small`, but the live `Chunk` schema exposes only the vector, not provider/model/dimensions/input hash. The stated stabilization acceptance assumption has not yet held at graph-inspection level.
4. **P0 - `WF-005`: keep the deterministic validator in every current skill.** The contract is fast, actionable, and catches missing per-question details. This live mixed-source run is acceptance evidence in addition to unit/contract tests.
5. **P1 - proposed `DEVX-001`: make bundled PDF rendering suppress or redirect Fontconfig caches.** The warnings generated hundreds of thousands of output tokens despite a valid one-page render, obscuring useful diagnostics.

## Stabilization assumptions

- Held: all five MCP server surfaces loaded; file-based Pydantic schema conversion agreed with extraction input; lowercase validators reconciled CSV/PDF bridge nodes; asynchronous jobs exposed usable IDs/progress; exact configured models worked; full-text/vector/Cypher retrieval worked; the deterministic report contract was runnable.
- Did not fully hold: page accounting is semantically inconsistent; generated ingest queries are not safe/executable without manual edits; embedding identity is not inspectable from stored chunk properties; PDF rendering diagnostics are excessively noisy in the managed sandbox.
- Not exercised: image/table description, VLM visual extraction, retries after provider failure, re-extraction, parser alternatives, and volume/scaling behavior.
