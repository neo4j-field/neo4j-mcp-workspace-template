# Project Tasks & Session State

> At the start of a new session, read this file to resume where we left off.

---

## Current Status (as of 2026-03-11)

We are in the **testing and refinement phase**. Two full `page_image` test runs have been completed and evaluated. The third test (pymupdf mode) is next.

---

## In Progress

_(nothing — ready for next test run)_

---

## Todo

### Testing
- [x] **Second evaluation** — `/dev:evaluate-pipeline` completed for 5-company run
  - Report: `outputs/reports/pharma_pipeline_5company_evaluation.md`
- [ ] PDF `pymupdf` mode — text-heavy PDF (annual report / 10-K pipeline section), clean run + evaluate
  - Goal: verify TARGETS and HAS_MOA work in prose mode
- [ ] PDF `docling` mode — tabular PDF (pipeline detail table), clean run + evaluate
- [ ] PDF `vlm_blocks` mode — mixed content, clean run + evaluate
- [ ] CSV — test `develop-neo4j-graph` skill end-to-end
- [ ] PDF + CSV combined — entity graph linking both data types

### Skill / server improvements identified (from run 1 evaluation)
- [ ] Add `relationships_only` pass trigger to Step 7 of `build-pdf-chatbot` skill
  - Currently blocked: `pass_type="relationships_only"` not implemented in entity-graph v1
- [ ] Update skill Step 8 to pre-fetch vector index name via `get_neo4j_schema_and_indexes`
- [ ] Remove `check_processing_status` after `embed_chunks` from skill (synchronous tool)
- [ ] Add `.strip().lower()` validator to `DrugCandidate.name` in schema (soft duplicate fix)

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
