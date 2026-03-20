# Project Tasks & Session State

> At the start of a new session, read this file to resume where we left off.

---

## Current Status (as of 2026-03-20)

**Docling reading order bug investigated** — tested on 5 medical PDFs. Bug is isolated to right-column sidebar elements (KEYWORDS, KeyPoints, What's new? boxes) leaking into the next page's element chain. Pages are always in correct order. Single-column docs are clean. Root cause is upstream in docling's multi-column layout detection, not in the MCP server. Also confirmed: `assign_section_hierarchy` does not touch element order (only sets `level`, rebuilds `HAS_SUBSECTION`, updates `Chunk.sectionContext`). Additional bug found: `chunk_lexical_graph(clear_existing_chunks=True, document_id=None)` fails to re-chunk after clearing — workaround is to pass explicit `document_id`.

---

## In Progress

_(nothing — ready for next test run)_

---

## Todo

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
- [ ] PDF `vlm_blocks` mode — mixed content, clean run + evaluate
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

### In progress (2026-03-20 session)
- [ ] **Reorder tools in `server.py` (lexical graph MCP) to match correct workflow sequence**
  - Current order has `generate_chunk_descriptions` last (must be before `embed_chunks`), `list_documents` after `verify_lexical_graph` (needs to be before it), `delete_document` in the middle (destructive, should be last)
  - Correct order: create → check_processing_status → cancel_job → chunk_lexical_graph → list_documents → verify_lexical_graph → assign_section_hierarchy → generate_chunk_descriptions → embed_chunks → set_active_version → clean_inactive → delete_document
- [ ] **Revise lexical graph tool ordering and dependencies in `HANDLE_UNSTRUCTURED_DATA.md`**
  - Make all tool dependencies explicit (not just page_image special cases)
  - `generate_chunk_descriptions` dependency: currently documented for `page_image` only, but Image/Table nodes are silently skipped in ALL parse modes if they have no `textDescription` — generalize to "recommended for any doc with images/tables"
  - Reflect new generic `embed_chunks` parameters in skill guidance

### Skill / server improvements identified (from runs 1–4)
- [ ] Add `relationships_only` pass trigger to Step 7 of `build-pdf-chatbot` skill
  - Currently blocked: `pass_type="relationships_only"` not implemented in entity-graph v1
- [ ] Update skill Step 8 to pre-fetch vector index name via `get_neo4j_schema_and_indexes` *(flagged runs 1+3)*
- [ ] Remove `check_processing_status` after `embed_chunks` from skill (synchronous tool) *(flagged runs 1+3)*
- [ ] Add `.strip().lower()` validator to key properties in schemas (soft duplicate fix) *(flagged runs 1+3)*
- [ ] Add `assign_section_hierarchy` guidance to skill Step 4 for legal/regulatory docs *(new — run 3)*
- [ ] Add optional post-extraction enrichment section to skill (metadata + citation resolution Cypher) *(new — run 3)*
- [ ] Add large-scale parallel subagent evaluation pattern to skill Step 8 *(new — run 3)*
- [ ] Fix or document entity relationship creation failure (CITES/MENTIONS/DISCUSSES = 0) in entity-graph *(new — run 3, Issue T-2)*
- [ ] Document LiteLLM model name format in entity-graph `extract_entities` tool *(new — run 3, Issue T-1)*
- [ ] Fix outdated tool names in `develop-neo4j-graph` skill (`create_lexical_graph_from_pdf`, `create_chunk_embeddings`, `extract_entities_from_chunks`, `get_entity_extraction_status`) *(run 4)*
- [ ] Add `chunk_lexical_graph` step to PDF pipeline in skill — critical missing step for docling/vlm_blocks/page_image modes *(run 4)*
- [ ] Add `convert_schema` as Step 1 of entity extraction in skill *(run 4)*
- [ ] Add pre-extraction constraint compatibility check to skill (key property vs. graph constraints) *(run 4)*
- [ ] Fix `embed_chunks` output — make skipped chunk count + reason explicit *(run 4)*
- [ ] Add `stalled` detection to `check_processing_status` (stuck on last chunk for 5+ min) *(run 4)*
- [ ] Add `extract_entities` pre-flight constraint check in entity-graph server *(run 4)*
- [ ] Add docling install note to skill: `uv sync --extra docling` required *(run 4)*
- [ ] Fix `chunk_lexical_graph(clear_existing_chunks=True, document_id=None)` — returns "No documents need chunking" after clearing instead of re-chunking; workaround is explicit `document_id` per doc *(2026-03-20)*

### Demo data + automated testing
- [ ] Choose best validated dataset from testing as the demo example
- [ ] Host demo data on GitHub Releases (PDFs and/or CSVs)
- [ ] Write `demo/download.sh` — fetches demo data into `data/`
- [ ] Populate `demo/expected/` — reference outputs (data model JSON, queries YAML, report MD)
- [ ] Write `demo/run-test.sh` — smoke test: download → run workflow → validate graph (node counts, indexes)

### Cursor skills (do last, after all Claude Code testing is done)
- [ ] Sync `.cursor/skills/develop-neo4j-graph/` with updated Claude command
- [ ] Create `.cursor/skills/build-pdf-chatbot/` mirroring the Claude command
- [ ] Test both skills in Cursor

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
  - `pass_type="relationships_only"` not yet implemented in entity-graph v1
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
