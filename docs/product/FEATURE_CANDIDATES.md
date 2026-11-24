# Feature candidate register

This is the post-stabilization inbox derived from the external
`IDEAS_HARVEST.md`. It preserves source identifiers without treating the harvest's
draft ordering as an approved roadmap. `IDEAS_HARVEST.md` remains unchanged.

Disposition meanings:

- `stabilization` — represented by a P0 item in `BACKLOG.md`.
- `future-review` — retain for prioritization after stabilization.
- `scope-decision` — decide template, shared-library, or Trellis ownership first.
- `superseded/remove` — do not build as proposed; retain only reusable lessons.
- `verified-done/partial` — current code differs from the harvest status.

## Current-code corrections to the harvest

| Harvest refs | Disposition | Current finding |
|---|---|---|
| A2 | verified-done | Ingest already creates one module-level `AsyncDriver`; the observed performance risk is whole-file/whole-request behavior, not per-call driver creation. |
| F3, F4 | verified-done/partial | The coding-agent skill already selects CHATBOT vs ANALYTICAL and uses confirmed questions/use cases; cross-client consistency still needs contract tests. |
| F5 | verified-done/partial | `metadata_json` exists and is passed into lexical graph creation; reserved-property overwrite safety remains P0. |
| F10 | verified-done | `setup.sh` currently generates `.vibe/config.toml`; `AGENTS.md` is stale. |
| H3 | verified-done/partial | Lexical/entity packages have the intended FastMCP/LiteLLM bounds, but other packages and Desktop-pinned artifacts still require release-wide alignment. |

## Stabilization traceability

| Candidate | Harvest refs | Backlog coverage |
|---|---|---|
| Ingest profiling, bounded batching, retry, failed-item handling, checkpoints, and metrics | A1, A3–A7, C3, P-C15 | PERF-001, PERF-004, PERF-005, WRITE-002 |
| Current parser/chunker/embedder correctness | B5, B6, B13–B15 | TEST-002, BUG-001, EMB-001, WRITE-002 |
| Current extraction normalization, validation, and known regressions | D6, D7, D9–D12 | EXT-001–EXT-004, BUG-002, BUG-003, TEST-003 |
| Current retrieval compatibility and workflow correctness | E2, E5 | REL-002, WF-001–WF-005 |
| Safe large-run and setup behavior | F2, F6, F8–F10, P-C19 | PERF-001–PERF-005, DESK-001, SETUP-001, SETUP-002, REL-001 |
| Demonstration, golden data, independent evaluation, and automated tests | G1, G2, G4, G5 | TEST-001–TEST-003, PERF-004 |
| Remove the experimental parser surface | S2, B10, B11 | SURF-003; `vlm_blocks`-specific work is superseded/remove |
| Dependency/security alignment | H3 | REL-001 |

## Future document, parsing, and chunking candidates

| Candidate | Harvest refs | Initial disposition |
|---|---|---|
| Docling reading order, headings, hierarchy, and regulatory section inference | B1–B4, B8, B9, P-C11, P-C13 | future-review |
| OCR and scanned-document support | B7 | future-review; implement through the three-parser architecture decision |
| Parser-agnostic TOC reconciliation, cross-page merges, figure/caption/reference links, and section-aware chunking | B12, P-C12, P-C14 | future-review; exclude `vlm_blocks`-only implementation |
| Structured table representation | C1 | future-review |
| JSON and semi-structured ingestion | C2 | future-review |
| Images, audio, video, and multilingual sources | C4, C5 | future-review; split by modality before prioritization |
| Page-index-style retrieval enabled by structural hierarchy | E1 | future-review; depends on heading/hierarchy quality |
| Description-enriched embeddings and controlled parallel processing | P-C16 | future-review; benchmark quality and cost separately from P0 bounding work |

## Future extraction and entity-quality candidates

| Candidate | Harvest refs | Initial disposition |
|---|---|---|
| Multi-pass and corrective extraction | D1, D2 | scope-decision; avoid duplicating Trellis pipeline architecture |
| Entity resolution, canonical mentions, aliases, catalogues, fuzzy review bands, and human review | D3, D15, D16, P-C4, P-C8–P-C10, S3 | scope-decision; likely entity-graph stage/shared library rather than another MCP server |
| Confidence, context expansion, and extraction-policy improvements | D4, D5, D8, P-C5–P-C7 | future-review |
| Extraction dry-run | D13 | future-review |
| Ontology import, routing, and richer alias/blocklist configuration | D14 | scope-decision with S4 |
| Variance control, canonicalization before relationships, and semantic-section context | P-C6 | future-review; evaluate before adopting majority voting |
| Deterministic classifiers combined with LLM extraction | P-C24 | future-review |
| Tiered extraction evaluation | P-C25 | future-review; a small golden regression subset is already stabilization |

## Future retrieval, provenance, and GraphRAG candidates

| Candidate | Harvest refs | Initial disposition |
|---|---|---|
| Openable citations and answer-level provenance | P-C1 | future-review; customer-validated and distinct from P0 run provenance |
| Fact/Evidence/Mention provenance, contradictions, deterministic IDs, and document-scoped lifecycle | P-C2 | scope-decision; split small reusable provenance improvements from Trellis's deterministic spine |
| Incremental post-processing and database-layer RBAC | P-C3 | scope-decision; RBAC is Trellis/platform scope |
| Native vector prefiltering | E3 | future-review |
| Cypher templates and sub-schema retrieval for text-to-Cypher scale | E4, P-C17, P-C18 | future-review |
| Current-date context, Cypher readability, and aggregation result shaping | P-C21, P-C22 | future-review; consider small independent fixes during stabilization only if low risk |
| Ingestion into existing populated databases | P-C23 | future-review; define compatibility and ownership rules first |

## Future skills, onboarding, and modeling candidates

| Candidate | Harvest refs | Initial disposition |
|---|---|---|
| Feedback/pipeline-evaluation skill | F1 | future-review |
| Use-case and questions-first UX refinements | F3, F4 | verified-done/partial; review only after current skills are contract-tested |
| Tool approval ergonomics | F7 | future-review; security review required |
| Metadata propagation into downstream prompts | F5 | future-review beyond the P0 reserved-property safety fix |
| Reusable schema templates, seed data, and faster ontology onboarding | P-C20 | future-review |
| Modeling-server replacement | S1 | scope-decision; first identify the minimal useful tools and Trellis overlap |
| Versioned ontology builder and ontology collaboration | S4, S5 | scope-decision; registry infrastructure belongs primarily in Trellis |
| Agent ergonomics conventions | H2 | future-review; evaluate per client rather than imposing one output format |

## Explicit Trellis or successor scope

| Candidate | Harvest refs | Disposition |
|---|---|---|
| Replace setup with neo4j-cli provisioning/catalog/credentials | H1 | scope-decision; current template retains and hardens `setup.sh` |
| Full eval-as-steering-wheel architecture | G3 | scope-decision; template gets regression tests, Trellis owns the pipeline-wide eval loop |
| Cross-server declarative manifest, durable run ledger, deterministic-ID spine, registry infrastructure, schema routing, UI/platform/ACLs | H1, G3, P-C2, P-C3, S4, S5 | Trellis; do not add to the stabilization release |

## Later prioritization method

After the stabilization exit criteria pass, review candidates using customer impact,
frequency across deployments, template-vs-Trellis fit, implementation risk,
vendorability, measurable acceptance criteria, and ongoing maintenance cost. Promote
only selected candidates into `BACKLOG.md`; then schedule them in `ROADMAP.md`.
