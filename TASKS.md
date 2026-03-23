# Project Tasks & Session State

> At the start of a new session, read this file to resume where we left off.

---

## Current Status (as of 2026-03-23)

**Session 2026-03-23** — Completed lexical-graph improvements: `assign_section_hierarchy` all-docs parallel mode, `generate_chunk_descriptions` prompt overhaul (non-informative image guard, domain-neutral language, caption + section context wired in), `max_parallel=0` auto-detect for `create_lexical_graph`, docling moved to main dependency, `vlm_blocks` flagged as experimental. All READMEs and skill references updated. Redesigned `dev/evaluate-pipeline` as `/send-feedback` skill (GitHub issue submission). Committed to PR #6.

**Previous (2026-03-20)** — Docling reading order bug scoped: right-column sidebar elements only, upstream in docling, not a production blocker. `chunk_lexical_graph(clear_existing_chunks=True, document_id=None)` bug found — workaround: pass explicit `document_id`.

---

## In Progress

_(nothing — ready for next test run)_

---

## Todo

### `/send-feedback` skill (replaces `dev/evaluate-pipeline`)
Rename and redesign `dev/evaluate-pipeline` as a proper `/send-feedback` skill that submits a structured GitHub issue to the repo with full context. Natural home for pipeline quality feedback, bug reports, and feature requests from real runs.

- [ ] **Rename + re-register** — move `dev/evaluate-pipeline` → `skills/send-feedback/`, update skill descriptor and registration
- [ ] **GitHub issue submission** — use `gh issue create` (already available via Bash tool) to post directly to `neo4j-field/neo4j-mcp-workspace-template`:
  - Issue title: auto-generated from use case + date
  - Issue body: structured Markdown with sections below
  - Issue labels: `feedback`, `pipeline-run`, and auto-detected labels (e.g. `docling`, `entity-graph`, `bug`)
- [ ] **Issue body content:**
  - Use case description (inferred from graph + session context)
  - Parse mode, skill used, custom steps taken
  - Repo branch + commit hash, MCP server versions
  - Pipeline quality summary (retrieval hit rate, entity counts, known gaps)
  - Up to 10 graph data samples — nodes/chunks as Markdown table, labeled "sample data"
- [ ] **Explicit consent flow** — before posting:
  - Show user the full issue body for review
  - Warn that samples may contain content from their documents
  - Let user edit or remove any section before confirming
  - Only post after explicit user approval ("yes, send it")
  - Always save report locally to `outputs/reports/` regardless of whether user sends
- [ ] **Large dataset warning** — at skill start, count input files:
  - PDFs > 100: warn, show count, propose random sample (e.g. 20) before ingestion
  - CSV rows > 10,000: warn, show row count, propose sampling
  - Never silently drop data — sampling must be explicit and reversible

### `develop-neo4j-graph` skill UX improvements (from 2026-03-23 test run)

- [ ] **Step 2 — use case framing question** — current question lists example queries which steers users toward chatbot mode. Replace with a cleaner binary first question: "Do you want to build a chatbot / GraphRAG Q&A application, or build a graph for another purpose (analytics, data pipeline, integration)?" Then drill into details based on the answer.

- [ ] **Step 2 — questions-first approach** — after mode is confirmed, before jumping to data modeling, the skill should ask: "Do you already have a set of questions your users will ask?" If yes: use them to drive schema design. If no: propose a set of representative questions based on the sampled data and ask the user to validate/amend them before proceeding to modeling.

- [ ] **Step 1 — document metadata via `metadata_json`** — `create_lexical_graph` has a `metadata_json` parameter that loads extra properties onto Document nodes. When sampling PDFs the agent already extracts useful metadata (company, date, content summary) into a table — this should be passed as `metadata_json` per document. Steps:
  - Confirm what `metadata_json` accepts (per-file JSON? global JSON?) by reading the server code
  - Check whether `documentName` + any metadata properties set on Document nodes are passed as context to `generate_chunk_descriptions` (VLM prompt), `embed_chunks`, and `extract_entities` — if not, investigate adding them
  - If metadata does reach downstream tools: add an optional step to the skill where the agent generates the metadata JSON from the sampling table, shows it to the user for confirmation, and passes it to `create_lexical_graph`

- [ ] **API concurrency not set by default** — user had to explicitly say "use concurrency 50" to get acceptable speed. This refers to concurrent API calls for `generate_chunk_descriptions(parallel=...)`, `embed_chunks`, and `extract_entities`. The skill should set a sensible high default (e.g. `parallel=20` or higher) rather than leaving it at the conservative default. Options: (a) hardcode a recommended value in the skill, or (b) ask the user upfront "Do you want to maximize speed? I'll use high API concurrency (50 parallel calls) — reduce this if you hit rate limits." Check the default values for `parallel` in each relevant tool and update the skill to use aggressive-but-safe defaults.

- [ ] **MCP server not loaded — skill should handle gracefully** — during test, `neo4j-lexical-graph` tools were missing at session start. Agent correctly diagnosed and told user to restart. Two things to fix:
  - Investigate root cause: why does the lexical-graph server sometimes fail to load on session start
  - Check what `/setup-workspace` does and whether it should be called automatically at the start of `develop-neo4j-graph` (as a pre-flight check) rather than requiring the user to know about it

- [ ] **`/dev:evaluate-pipeline` not available in new workspace** — slash command not found after fresh setup. Investigate: check skill registration path, whether the `dev/` subfolder is recognized, and whether this is related to the broader skill availability issue. This is also the trigger for the `/send-feedback` rename work.

- [x] **Skill/tool parameter accuracy audit** — audited all tool parameters referenced in skill docs against server implementations. Only `pass_type` variants were unimplemented. Fixed: `extract_entities` Field description now only advertises `"full"`; unimplemented variants (`entities_only`, `relationships_only`, `corrective`) removed from tool description. Implementation of those variants remains future work.

- [ ] **Tool confirmation prompts** — in a freshly set up workspace, Claude Code asks the user to confirm each tool call individually, which is very disruptive during a long pipeline run. Investigate whether this can be pre-configured: check if `settings.json` or `.claude/settings.json` supports auto-approving specific tools or MCP servers by default, and if so add this to `setup.sh` or document it clearly in the onboarding flow.

- [ ] **Chatbot report completeness** — the auto-generated report is too thin. Improve it to include:
  - Graph schema overview: node labels with counts, relationship types with counts
  - For each test question: the exact tools called (vector_search, fulltext_search, read_neo4j_cypher, etc.) and the queries/parameters used — not just the answer
  - A final section with improvement ideas: gaps in the graph, schema changes that would improve retrieval, suggested additional data sources

- [ ] **Entity extraction regression on AbbVie pipeline page 4** — not all molecules were extracted from the AbbVie pipeline document (page 4 lists many molecules, previous runs had better coverage). Investigate:
  - Check that all molecules appear in `Chunk.text` for the relevant chunks (verify with `read_neo4j_cypher`)
  - Check chunk boundaries — is page 4 content split across multiple chunks, and if so are all chunks being sent to extraction?
  - Check if the extraction model is truncating context or hitting token limits
  - Compare chunk content vs previous run to see if something changed in chunking strategy or chunk size
  - This may be a regression from recent changes — bisect if needed


### Testing
- [x] **Second evaluation** — `/dev:evaluate-pipeline` completed for 5-company run
  - Report: `outputs/reports/pharma_pipeline_5company_evaluation.md`
- [x] **Third evaluation** — Italian Tax Law KG, pymupdf mode, 70 PDFs, 100% retrieval hit rate
  - Chatbot report: `outputs/reports/tax_docs_chatbot_report.md`
  - Agent eval report: `outputs/reports/eval_agent_report.md` (45 Q&A)
  - Pipeline eval: `outputs/reports/tax_docs_pipeline_evaluation.md`
- [x] **Run 4: Healthcare Patient Journey** — `develop-neo4j-graph`, CSV + PDF, docling mode
  - Graph: 50 patients, 936 events, 112 medications, 133 conditions, 5 PDFs, 244 chunks
  - Parse mode comparison: pymupdf vs vlm_blocks vs docling → docling selected
  - Entity extraction: Medication + Condition from research PDFs, auto-merged via shared name key
  - Chatbot report: `outputs/reports/healthcare_patient_journey_report.md`
  - Pipeline eval: `outputs/reports/healthcare_pipeline_evaluation.md`
- [ ] PDF `pymupdf` mode + `assign_section_hierarchy` — structured legal/regulatory text
  - Goal: verify section hierarchy improves retrieval precision for nested article references (art. X, comma Y)
  - Also: reproduce and confirm entity relationship creation failure (Issue T-2: CITES/MENTIONS/DISCUSSES = 0)
- [ ] PDF `docling` mode — tabular PDF (pipeline detail table), clean run + evaluate
- [ ] PDF `vlm_blocks` mode — run full pipeline, audit skill steps, fix any gaps, evaluate quality
- [ ] PDF `page_image` mode — run full pipeline, audit skill steps, fix any gaps, evaluate quality
- [ ] **Entity graph MCP end-to-end test** — run entity extraction on docling-ingested docs, audit skill steps, fix gaps (tool names, convert_schema flow, relationship creation)
- [x] **Validate reading order correctness** — docling mode, 5 PDFs (2026-03-20)
  - **Result:** Pages always in correct order. Bug is isolated to right-column sidebar elements leaking into next page's element chain (multi-column journal articles only)
  - Single-column docs (jciinsight, nihms, fendo) are fully clean
  - Root cause: upstream in docling's multi-column layout detection — not in MCP server ingestion
  - `assign_section_hierarchy` confirmed not to affect element order (only level/HAS_SUBSECTION/sectionContext)
  - Remaining fix: post-processing reorder step in MCP server, or wait for docling upstream fix
  - **Not a blocker for production RAG** — affected content (sidebars) is low-information

### Setup / onboarding improvements (from local LLM evaluation)
- [ ] **Add extraction model pre-flight check to `setup-workspace` skill and/or `setup.sh`**
  - After credentials are set, call the configured `EXTRACTION_MODEL` with a minimal structured output prompt (e.g. extract one entity from a one-sentence text)
  - If it fails: surface a clear error — model not found, API key missing, Ollama not running, model doesn't support structured output, etc.
  - If it succeeds: confirm with ✓ and show the model name + response time
  - Rationale: currently a misconfigured extraction model fails silently mid-run after minutes of lexical graph processing
- [ ] Add unicode normalization (`unicodedata.normalize('NFKD', v)`) to generated Pydantic validator template in `schema_generator.py` — prevents `dpp-4` vs `dpp‐4` (unicode dash) duplicates
- [ ] Add embedding dimension mismatch warning to `embed_chunks` — detect if existing vector index has different dimensions than the current `EMBEDDING_MODEL` and warn before overwriting
- [ ] Add negative prompt guidance to `build_system_prompt()` in `base_extractor.py` — instruct model not to extract drug class names as drug entities, and not to extract table headers / statistical notation as trial names

### Skill / server improvements identified (from runs 1–4)
- [ ] Add `relationships_only` pass trigger to Step 7 of `build-pdf-chatbot` skill
  - Blocked: `pass_type="relationships_only"` not yet implemented in entity-graph (future work); unimplemented variants removed from tool description so agents won't suggest them
- [ ] Update skill Step 8 to pre-fetch vector index name via `get_neo4j_schema_and_indexes` *(flagged runs 1+3)*
- [ ] Remove `check_processing_status` after `embed_chunks` from skill (synchronous tool) *(flagged runs 1+3)*
- [ ] Add `.strip().lower()` validator to key properties in schemas (soft duplicate fix) *(flagged runs 1+3)*
- [ ] Add `assign_section_hierarchy` guidance to skill Step 4 for legal/regulatory docs *(new — run 3)*
- [ ] Add optional post-extraction enrichment section to skill (metadata + citation resolution Cypher) *(new — run 3)*
- [ ] Add large-scale parallel subagent evaluation pattern to skill Step 8 *(new — run 3)*
- [ ] Fix or document entity relationship creation failure (CITES/MENTIONS/DISCUSSES = 0) in entity-graph *(new — run 3, Issue T-2)*
- [ ] Document LiteLLM model name format in entity-graph `extract_entities` tool *(new — run 3, Issue T-1)*
- [x] Fix outdated tool names in `develop-neo4j-graph` skill *(run 4)*
- [x] Add `chunk_lexical_graph` step to PDF pipeline in skill *(run 4)*
- [x] Add `convert_schema` as Step 1 of entity extraction in skill *(run 4)*
- [ ] Add pre-extraction constraint compatibility check to skill (key property vs. graph constraints) *(run 4)*
- [ ] Fix `embed_chunks` output — make skipped chunk count + reason explicit *(run 4)*
- [ ] Add `stalled` detection to `check_processing_status` (stuck on last chunk for 5+ min) *(run 4)*
- [ ] Add `extract_entities` pre-flight constraint check in entity-graph server *(run 4)*
- [x] Add docling install note to skill — now moot: docling is a main dependency, no extra needed *(run 4)*
- [ ] Fix `chunk_lexical_graph(clear_existing_chunks=True, document_id=None)` — returns "No documents need chunking" after clearing instead of re-chunking; workaround is explicit `document_id` per doc *(2026-03-20)*

### Completed (2026-03-21 session)
- [x] Reorder tools in `server.py` to match correct workflow sequence
- [x] Revise tool ordering and dependencies in `HANDLE_UNSTRUCTURED_DATA.md` and all mode reference files
- [x] `assign_section_hierarchy` all-docs parallel mode (omit `document_id` → runs all active docs via `asyncio.gather`)
- [x] `generate_chunk_descriptions` prompt improvements: caption + section context wired in, non-informative image guard, domain-neutral language, pymupdf markdown table fallback
- [x] `max_parallel=0` auto-detect for `create_lexical_graph` (RAM/CPU-based worker count)
- [x] Docling moved to main dependency — `uv sync --extra docling` no longer needed
- [x] `vlm_blocks` flagged as experimental in README, skill, server tool description
- [x] README + all skills audited and updated for today's changes

### Demo data + automated testing
- [ ] Choose best validated dataset from testing as the demo example
- [ ] Host demo data on GitHub Releases (PDFs and/or CSVs)
- [ ] Write `demo/download.sh` — fetches demo data into `data/`
- [ ] Populate `demo/expected/` — reference outputs (data model JSON, queries YAML, report MD)
- [ ] Write `demo/run-test.sh` — smoke test: download → run workflow → validate graph (node counts, indexes)

---

## Completed

- [x] Redesigned workspace folder structure (`outputs/`, `data/csv/`, `data/pdf/`, `demo/`)
- [x] Updated `.gitignore` — input data and generated outputs excluded, folder structure tracked
- [x] Created `build-pdf-chatbot` Claude command (`.claude/commands/build-pdf-chatbot.md`)
- [x] Created `dev/evaluate-pipeline` Claude command (`.claude/commands/dev/evaluate-pipeline.md`)
- [x] Updated `develop-neo4j-graph` command — output paths updated to `outputs/`
- [x] Updated `CLAUDE.md` — fixed stale tool names, new structure and workflow sections
- [x] Updated `README.md` — new `outputs/` structure, fixed vlm_blocks description
- [x] Deleted legacy `data_models/` folder
- [x] **Run 1: 2-company page_image test** (Pfizer + Bayer)
  - 601 unique entities, 842 relationships
  - Gap: TARGETS=0, HAS_MOA=9
  - Report: `outputs/reports/pharma_pipeline_chatbot_report.md`
  - Evaluation: `outputs/reports/pharma_pipeline_evaluation.md`
- [x] **Run 4: Healthcare Patient Journey** — `develop-neo4j-graph`, CSV + PDF, docling
  - Reports: `outputs/reports/healthcare_patient_journey_report.md`, `healthcare_pipeline_evaluation.md`
- [x] **Run 2: 5-company page_image test** (Pfizer, Bayer, AbbVie, BMS, J&J)
  - 1596 unique entities, 1807 relationships from 102 chunks
  - Gap: TARGETS=3, HAS_MOA=13, J&J IN_PHASE=0
  - `pass_type="relationships_only"` not yet implemented in entity-graph (unimplemented variants removed from tool description — future work)
  - Report: `outputs/reports/pharma_pipeline_5company_chatbot_report.md`
- [x] Committed and pushed all changes to GitHub

---

## Key Findings Across Runs

| Issue | Run 1 | Run 2 | Root cause |
|-------|-------|-------|------------|
| TARGETS | 0 | 3 | Pipeline tables encode drug→indication spatially, not in prose |
| HAS_MOA | 9 | 13 | Same — MOA in table column, not sentence structure |
| Bayer Registration | 0 in graph | 0 in graph | Misattribution from Pfizer-first slide context |
| J&J IN_PHASE | N/A | 0 | J&J slide layout not captured as explicit phase relationships |
| Soft duplicates | None | Camzyos/CAMZYOS etc. | DrugCandidate.name lacks .lower() normalizer |
| COMBINED_WITH | N/A (new) | 33 (BMS only) | BMS appendix has explicit combination columns; others don't |

## Key Files

| File | Purpose |
|------|---------|
| `.claude/commands/build-pdf-chatbot.md` | Main PDF chatbot skill |
| `.claude/commands/develop-neo4j-graph.md` | General CSV+PDF skill |
| `.claude/commands/dev/evaluate-pipeline.md` | Post-run evaluation tool |
| `outputs/data_models/pharma_pipeline_data_model.json` | 5-company graph model with COMBINED_WITH |
| `outputs/schemas/pharma_pipeline_schema.py` | Pydantic schema with 5-company Literals |
| `outputs/reports/pharma_pipeline_chatbot_report.md` | Run 1 (2-company) chatbot report |
| `outputs/reports/pharma_pipeline_evaluation.md` | Run 1 evaluation report |
| `outputs/reports/pharma_pipeline_5company_chatbot_report.md` | Run 2 (5-company) chatbot report |
| `outputs/reports/local_llm_evaluation_report.md` | Local LLM evaluation (qwen3:8b, qwen3.5:9b, phi4-mini vs gpt-5-mini) |
| `mcp-neo4j-entity-graph/test_local_llm.py` | Text extraction benchmark script (multi-model) |
| `mcp-neo4j-entity-graph/test_vlm_extraction.py` | Vision extraction test on single PDF page |
