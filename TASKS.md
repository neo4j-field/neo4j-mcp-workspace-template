# Project Tasks & Session State

> At the start of a new session, read this file to resume where we left off.

---

## Current Status (as of 2026-03-06)

We are in the **testing and refinement phase**. The workspace structure and PDF chatbot skill are built and committed. We have run one partial test with Bayer pharmaceutical pipeline PDFs (page_image mode) and used the results to fix several skill bugs. The skill is now ready for a clean full run.

---

## In Progress

- [ ] **PDF page_image — clean full run** using `build-pdf-chatbot` skill
  - PDFs are in `data/pdf/`: Bayer pharmaceutical pipeline slides (2 files)
  - Previous run exposed bugs, all fixed — needs fresh session to validate
  - After run: execute `/dev/evaluate-pipeline` to produce improvement report

---

## Todo

### Testing
- [ ] PDF `pymupdf` mode — text-heavy PDF, clean run + evaluate
- [ ] PDF `docling` mode — structured/tabular PDF, clean run + evaluate
- [ ] PDF `vlm_blocks` mode — mixed content, clean run + evaluate
- [ ] CSV — test `develop-neo4j-graph` skill end-to-end
- [ ] PDF + CSV combined — entity graph linking both data types

### Quick fixes (do before next test session)
- [ ] Fix stale tool names in `CLAUDE.md` MCP server reference section
  - `create_lexical_graph_from_pdf` → `create_lexical_graph`
  - `create_chunk_embeddings` → `embed_chunks`
  - `create_fulltext_index` → covered by `embed_chunks` default
  - `extract_entities_from_chunks` → `extract_entities`
  - `get_entity_extraction_status` → `check_extraction_status`
- [ ] Update `README.md` for new `outputs/` structure and new skills

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
- [x] Updated `CLAUDE.md` — new structure and workflow sections
- [x] Fixed skill bugs from first test run:
  - Read tool (not MCP) for PDF discovery
  - `generate_chunk_descriptions` mandatory before `embed_chunks` for `page_image` mode
  - Removed redundant manual `CREATE FULLTEXT INDEX` step
  - `MENTIONED_IN` → `EXTRACTED_FROM`
  - `verify_lexical_graph` not useful for `page_image` mode (5.8MB base64) — use `list_documents` + `read_node_image` instead
- [x] Confirmed `read_node_image` available in graphrag server + code up to date
- [x] Committed and pushed all changes to GitHub

---

## Key Files

| File | Purpose |
|------|---------|
| `.claude/commands/build-pdf-chatbot.md` | Main PDF chatbot skill |
| `.claude/commands/develop-neo4j-graph.md` | General CSV+PDF skill |
| `.claude/commands/dev/evaluate-pipeline.md` | Post-run evaluation tool |
| `outputs/data_models/` | Generated graph data model JSON |
| `outputs/queries/` | Generated Cypher YAML |
| `outputs/reports/` | Generated markdown reports |
| `outputs/schemas/` | Pydantic extraction schemas |
| `data/pdf/` | Input PDFs (gitignored) |
| `data/csv/` | Input CSVs (gitignored) |
| `demo/` | Demo data scripts and reference outputs |
