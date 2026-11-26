# Live release acceptance — 2026-11-24

**Outcome: passed after correcting the test harness.** Actual CSV + PDF ingestion,
configured extraction/embeddings, provenance, native Docling hierarchy, ontology
interchange/retrieval and PageIndex passed. The final three-question CHATBOT report
validated **true, records_found 3, exit 0**. There are **27 passing recorded checks**.
Hosted CI and release packaging remain separate gates.

## Execution and artifacts

Four actual local MCP servers ran as stdio subprocesses: ingest, lexical graph,
entity graph and GraphRAG. All graph traffic was explicitly isolated to disposable
Neo4j 2025.12.1 Enterprise at localhost:17689, databases `release-e2e` and
`release-ontology`; URI/URL variants and ontology connection variables were overridden.
Workspace `.env` provider settings stayed in memory. No model responses, embedding
vectors or servers were mocked. Configured models remained **`gpt-6-luna`** and
**`text-embedding-3-small`**, unchanged throughout.

Run namespace: `release-20261124t195832z`. Original 2 CSV files and 1 maintenance PDF
were copied into a unique run folder; a supplemental 2-page nested PDF exercises
native Docling and page citations. Original files and prior reports were preserved.

Generated evidence:
[run folder](../../../outputs/reports/release_acceptance_20261124/run_20261124T195832Z/),
[final CHATBOT report](../../../outputs/reports/release_acceptance_20261124/run_20261124T195832Z/chatbot_report.md),
[summary](../../../outputs/reports/release_acceptance_20261124/run_20261124T195832Z/summary.json).
The folder retains copied inputs, generated schema/spec, per-tool arguments/results,
status polls, timings, original-content citations, sanitized logs and both failed and
successful extraction-attempt evidence. Credential-value scanning found no configured
secret values in generated text artifacts.

Reproducible harness scripts are in the generated acceptance folder: `live_acceptance.py`,
`continue_acceptance.py`, `verify_remaining_evidence.py`,
`rerun_extraction_configured_runtime.py` and `write_final_report.py`. Active live
harnesses now use normal configured metadata fetching. `check_model_routing.py`
retains an explicit diagnostic bundled-map mode solely to reproduce the discrepancy;
it makes no completion request.

## Actual results

| Check | Observed evidence |
| --- | --- |
| Original 2 CSVs | 1 row each → exactly 1 Product, 1 Facility, 1 Procedure, 2 CSV relationships |
| Original PDF | PyMuPDF → 1 active chunk; lexical verification passed |
| Native Docling | Actual 2-page parse → 6 sections and 1 structured chunk; 3-level native hierarchy |
| N4 ontology | Spec import → generation → export preserved extraction semantics; no adapter mocks |
| Configured extraction | Job `0a5315762e7d`, `gpt-6-luna`, complete in 5.1s; 1 source succeeded, 0 failed, 1 persisted |
| Bridge merge | 3 entity assertions merged onto the 3 CSV nodes; zero normalized-key duplicates |
| Domain relationships | 2 CSV + 2 PDF = exactly 4 expected relationships |
| Property policy | CSV action preserved; full PDF action proposal and `["action"]` conflict retained |
| Entity provenance | 3 EXTRACTED_FROM records reference the active source and carry model/run/fingerprint/time/full-pass metadata |
| Relationship ownership | 2 EntityExtractionClaim records match the successful run id/fingerprint; that run records `gpt-6-luna` |
| Durable completion | Successful PROCESSED_SOURCE has a 64-character source fingerprint and is not invalidated |
| Real embeddings | 2 chunks, configured model, 1536 dimensions and input/model identity metadata |
| Actual retrieval | Vector and fulltext indexes ONLINE; original chunk top vector score 0.787940979; quoted coolant-valve fulltext hits |
| Filtered vector retrieval | documentName filter returned the 1 intended original-document hit |
| Ontology retrieval | Existing Ontology DB and configured-file mode passed; file alias `thermal maintenance` resolves Procedure |
| PageIndex | Tools appeared after parse; outline → section drilldown returned CV-7, ancestor path and correct page-1 citation |
| Target Q&A | All 3 actual graph queries returned exactly 1 record; final report validator passed |

Native section path is `1 Maintenance > 1.1 Overheating response > 1.1.1 Valve inspection`.
The second branch is `2 Authority > 2.1 Documentation`. Heading chains are stored on the
chunk. CV-7 content is cited as **page_number 1 / page_index 0**, agreeing with the
rendered supplemental fixture.

The final cross-layer query actually returns **golden-e2e-20260910 northstar works**
as both manufacturer and PDF-extracted procedure owner. Report answers derive from
actual returned records and retrieval results, rather than assuming fixture expectations.
The tested 2025.12.1 server uses the supported plain-vector-index fallback for additional
prefilters; indexes are ONLINE.

## Harness discrepancy and correction

The initial live harness incorrectly borrowed `LITELLM_LOCAL_MODEL_COST_MAP=True`
from offline unit-test settings. Its bundled metadata did not recognize the configured
new model, producing `litellm.BadRequestError: LLM Provider NOT provided ... You passed
model=gpt-6-luna`. The extraction path stopped without fallback.

Read-only provider-resolution comparison then established:

- Bundled offline map: unchanged `gpt-6-luna` → provider inference error.
- Normal configured metadata fetching: unchanged `gpt-6-luna` → provider `openai`.
- The user had not configured the offline-map flag.

Only that harness-introduced override was removed. No `.env` edit, model prefix/rename,
explicit provider override or replacement model was used. A fresh subprocess then
completed the originally authorized extraction and all previously blocked checks.
This was a test-harness configuration error, not a user model configuration defect.

The original failed job `a3913beda798`, failure transcripts/logs, historical partial
report, provider-resolution diagnostic and one-line correction diff remain preserved.
The failed attempt published no extraction data; the successful attempt has its own
run id, durable completion and provenance. No further model work was needed for the
already passing embedding/retrieval evidence.

## Cold Docling first-use measurement

The first actual conversion used new absolute `HF_HOME`, `DOCLING_CACHE_DIR`,
`TORCH_HOME` and `XDG_CACHE_HOME` directories, CPU execution and 4 threads. Initial
tracked caches were empty. First two-page conversion, including process startup,
model initialization/downloads and graph writing, took **45.305 seconds**.

Tracked footprint: **530,000,774 regular-file bytes** (17 files), **530,034,688 allocated
bytes**, plus 14 Hugging Face snapshot symlinks. The logical path-size sum including
symlink targets is 1,060,001,468 bytes and double-counts model blobs; it is not disk
footprint. These figures do not measure network transfer. Dependency clean-setup
measurement and the deferred 10k-row/50-page workload are separate.

## Limits

This acceptance covers a small synthetic fixture and the combined current code state.
It does not establish large-corpus extraction accuracy, throughput, arbitrary provider
aliases or Aura role policy. The validator checks report structure/evidence fields;
the independent actual graph/provider checks establish this live workflow's pass.

## Cleanup

After saving the final reports and tool evidence, the parent removed only the
disposable `workspace-release-check-20261124` container. User databases, input
files, existing reports and configuration were untouched. Generated acceptance
artifacts and isolated model-cache evidence remain available.
