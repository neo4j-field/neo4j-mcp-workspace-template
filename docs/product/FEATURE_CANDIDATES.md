# Feature candidate register

This is the candidate inbox derived from the external
`IDEAS_HARVEST.md`. It preserves source identifiers without treating the harvest's
draft ordering as an approved roadmap. `IDEAS_HARVEST.md` remains unchanged.

Disposition meanings:

- `stabilization` — traceability to existing work in `BACKLOG.md`; the current four groups determine release commitments.
- `pre-release` — explicitly selected by the owner for this release (N1/N4).
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
| Docling reading order, headings, hierarchy, and regulatory section inference | B1–B4, B8, B9, P-C11, P-C13, N1 | pre-release; owner-specified approach in N1 (use Docling's native hierarchy, retire LLM level re-inference) |
| OCR and scanned-document support | B7 | future-review; implement through the three-parser architecture decision |
| Parser-agnostic TOC reconciliation, cross-page merges, figure/caption/reference links, and section-aware chunking | B12, P-C12, P-C14 | future-review; exclude `vlm_blocks`-only implementation |
| Structured table representation | C1 | future-review |
| JSON and semi-structured ingestion | C2 | future-review |
| Images, audio, video, and multilingual sources | C4, C5 | future-review; split by modality before prioritization; multimodal embeddings split out as N3 |
| Page-index-style retrieval enabled by structural hierarchy | E1 | implemented locally in GraphRAG; separate-package delivery and final live smoke pending. [Validation](reviews/2026-11-24-graphrag-retrieval.md). |
| Description-enriched embeddings and controlled parallel processing | P-C16 | future-review; benchmark quality and cost separately from P0 bounding work |

## Future extraction and entity-quality candidates

| Candidate | Harvest refs | Initial disposition |
|---|---|---|
| Multi-pass and corrective extraction | D1, D2 | scope-decision; avoid duplicating Trellis pipeline architecture |
| Entity resolution, canonical mentions, aliases, catalogues, fuzzy review bands, and human review | D3, D15, D16, P-C4, P-C8–P-C10, S3 | scope-decision; likely entity-graph stage/shared library rather than another MCP server |
| Confidence, context expansion, and extraction-policy improvements | D4, D5, D8, P-C5–P-C7 | future-review |
| Extraction dry-run | D13 | future-review |
| Ontology import, routing, and richer alias/blocklist configuration | D14, N4 | N4 pre-release for spec interchange; broader routing/registry scope remains separate |
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

## Owner additions — 2026-11-24

Added directly by the owner after the harvest; not present in `IDEAS_HARVEST.md`.
`N` identifiers are register-local.

| ID | Candidate | Current state | Initial disposition |
|---|---|---|---|
| N1 | **Native Docling section hierarchy.** Upgrade Docling and use its native heading hierarchy instead of re-inferring levels. | `docling_parser.py` reads Docling headings, but `postprocessing/section_hierarchy.py` re-assigns levels with an LLM because Docling previously returned flat level-1 sections. | pre-release, implemented with Docling 2.152.0 and full heading paths in section-aware chunks; the `assign_section_hierarchy` LLM tool is being retired (decision 2026-11-24) since native hierarchy replaces it. Final live PDF smoke pending. [Validation](reviews/2026-11-24-n1-n4.md). Unlocks E1 page-index retrieval. |
| N2 | **Cross-document links.** Extract references between documents (citations, "see document X", amendments/supersedes, regulatory cross-references) as document-to-document relationships. | Not implemented. B12 covers intra-document figure/caption/reference links; P-C1/P-C2 cover answer-level provenance. | future-review; new gap. Define the relationship vocabulary and the target-resolution rule (document ID, title, or external identifier) before implementation. |
| N3 | **Multimodal embeddings.** Embed images, tables, and page images directly in a multimodal vector space. | `embed_chunks` embeds text only; image/table chunks are embedded from their generated `textDescription`, not their pixels. | future-review; split from C4. Benchmark retrieval quality and cost against description-based embeddings; depends on the PERF-003 image-storage policy. |
| N4 | **Neo4j Ontology Graph Spec support — owner-flagged priority.** Accept and emit ontologies in the [Neo4j Ontology Graph Spec](https://neo4j.com/docs/ontology-graph-spec/) (YAML/JSON validated by its normative JSON Schema, with `schema`, `version`, `id`, `nodes`, `relationships`, and `extensions`; SDKs for JVM, JS/TS, and Go). | The workspace has its own Ontology DB model (`:Ontology`/`:NodeType`/`:PropertyDef`, `:CONTAINS`) compiled by `generate_schema_from_ontology`; there is no spec import/export or validation. | pre-release, implemented as a bounded import/export adapter preserving the Ontology DB. The unchanged normative 1.1.0 JSON Schema is bundled for offline validation; no registry redesign. Unsupported semantics/collisions are rejected. Final combined live smoke pending. [Validation](reviews/2026-11-24-n1-n4.md). |
| N5 | **Fireworks API key for the extraction LLM.** | Not supported as a documented path. LiteLLM can route `fireworks_ai/...` models using `FIREWORKS_AI_API_KEY` from `.env` (loaded by `load_dotenv`) or Desktop `EXTRA_ENV`, but this is untested. `setup.sh` prompts only for `OPENAI_API_KEY`, and `build_llm_params()` chooses parameters by model-name substring, so reasoning models served by Fireworks may need the same handling as Ollama thinking models. | future-review; small. Promote with DESK-002 (conditional provider credentials) and SETUP-002 (structured-output preflight). Acceptance: setup/docs/Desktop accept a Fireworks key, a named Fireworks model passes the structured-output preflight and an extraction fixture, and embeddings remain configurable independently. |
| N6 | **Evaluate where TypeSafe Jev fits in the workflow.** Jev is a "System One" model returning calibrated typed answers (`Noul`/`Choice`/`Score`) rather than generated text. | Not integrated. Prior art: `neo4j-field/jev-graphrag` (entity-resolution judge with a confidence-gated review queue) and a Neo4j entity-resolution comparison where Jev routing plus an LLM fallback matched a frontier LLM at about 17% of its cost. | future-review; investigation first. Map candidate decision points — chunk/parser routing, extraction-triple grounding checks, per-field error scoring with LLM escalation, entity-resolution judging (S3/D3), and graph-quality checks (QL-002) — then measure against the golden set. Not a replacement for generative extraction; text input only, 64k request limit. |
| N7 | **POC-to-production handoff to `ps-genai-starterkit`.** Internal Neo4j PS "starter kit for delivering genAI projects" ([repo](https://github.com/neo-technology-field/ps-genai-starterkit)), Apache-2.0, v1.0; owner states it is going to be a Neo4j Labs project. **Product positioning (owner, 2026-11-25): the MCP workspace is for demos, POCs, workshops and quick iteration; when the customer is ready for production, the customer or Neo4j PS builds the production pipeline with the starter kit.** The goal is that a completed workspace POC seeds that production build so the team does not start from scratch. | Reviewed 2026-11-25. Four packages: **ingestion** (PyMuPDF/DOCX/PPTX/XLSX/images → `Document-[:HAS_CHUNK]->Chunk` with `Chunk.embedding`; FREE or STRICT Pydantic extraction; string-similarity entity resolution; optional `chunk_from_nodes` to re-chunk existing labelled nodes); **retrieval** (FastAPI + React/Vite UI with NVL graph visualization and reasoning trace; VectorCypher + Text2Cypher; optional `/mcp` or stdio MCP server); **eval** (DeepEval correctness/relevancy/faithfulness/tool correctness on a JSON question set, results as `TestRun→TestCase→MetricResult`); **config** (cascading dotenv). Key seams for a handoff: its STRICT mode consumes a Pydantic schema file, its eval consumes `questions.json`, and `chunk_from_nodes` can consume existing graph nodes. Hard mismatch to handle: its retrieval assumes `(:Document)-[:HAS_CHUNK]->(:Chunk)` and a `Chunk.embedding` vector index, while the template lexical graph uses `Chunk-[:PART_OF]->Document` plus Page/Element/Image/Table nodes. | future-review / scope-decision; owner-added 2026-11-24, repositioned 2026-11-25. **Direction: artifact portability, not graph portability.** Define a documented "POC handoff package" the workspace can emit for a starter-kit production build: (a) the Pydantic extraction schema (`convert_schema` / ontology export) → starter-kit `config/ingestion/schema.py` STRICT mode; (b) the confirmed use cases and questions, plus any expected answers/eval notes → `config/eval/questions.json`; (c) the data model, ontology, entity/relationship vocabulary, normalizers, aliases, blocklists and key-property decisions; (d) parse/chunking choices, model choices and extraction-prompt/config decisions; (e) optionally the demo graph for reference only. Production should normally **re-ingest** with the starter kit for lineage and lifecycle reasons; do not promise that the POC graph is production-ready. Experiment: take one completed POC, rebuild it in starter-kit STRICT mode using only the emitted package, then run its DeepEval suite on the POC questions and record which artifacts transferred cleanly, what had to be rewritten, and the time saved vs starting from scratch. If graph reuse is requested, add a thin compatibility step (materialize `HAS_CHUNK`, align `chunkId`/`embedding`/index) rather than changing the template's model. Do not adopt the starter-kit ingestion pipeline into the template and do not fork it; prefer upstream contributions; record the Trellis boundary before promoting to `BACKLOG.md`. |

## Next-release candidates — SE feedback (2026-11-24)

Sourced from André Normann (Slack DM, 2026-10-09) and follow-up review. These are
**next release / fast-follow** items, not part of the current release. `SE` identifiers
are register-local.

| ID | Candidate | Current state | Next-release scope and acceptance |
|---|---|---|---|
| SE1 | **Model and graph visualization.** Show the model and the resulting graph in a viewable, zoomable form; support detailed inspection. | Four sub-model Mermaid diagrams are required in the skill via `get_mermaid_config_str`; there is no post-build view of the actual graph and no editable visual model. | Produce (a) a post-build snapshot in reports — live counts by label and relationship type, a sample subgraph and a schema diagram; (b) a self-contained static HTML view (zoom/pan, read-only) generated from the data model. Acceptance: a CSV+PDF run yields a report with the diagram and live counts, and an offline HTML artifact matching the graph; no new required runtime dependency. |
| SE2 | **Readable progress for long-running stages.** Report how much is done and how much remains instead of appearing stuck. | `check_extraction_status` already returns selected/attempted/succeeded/empty/failed sources, chunks completed/remaining, entity and relationship counts, elapsed time and `estimated_remaining_seconds`; the skill already tells the agent to poll. Agents may still dump raw JSON. | Define a compact progress line for the skill (e.g. `412/1200 chunks · 3140 entities · ~4 min left`) and require interval reporting; apply the same format to lexical `check_processing_status`. Acceptance: a representative run reports progress at least every few polls, no raw JSON dumps, and failures surface attempted/failed counts. Effort: small, skill/doc-only. |
| SE3 | **Per-step model selection and measured recommendations.** Avoid using one expensive/slow model for every stage. | A single `EXTRACTION_MODEL` default also drives optional lexical VLM steps; `generate_chunk_descriptions` accepts a per-call `model`; setup prompts only for embedding and extraction models. The hierarchy step is being removed, eliminating one row. | Publish a task×model matrix measured on the synthetic golden set: chunk description, table/image description, entity extraction, relationship extraction, answer synthesis. Report quality, latency and cost; recommend capability classes (not fixed model names); decide whether a separate lexical/description model setting is warranted. Keep the no-silent-substitution rule. Acceptance: measured matrix and documented defaults; no default change without evidence. Coordinate with N6 (Jev as cheap router/judge); AIP is a workflow-adherence axis, not the model benchmark. |
| SE4 | **Arrows.app optional integration evaluation.** Determine whether André's `arrows-mcp` should be an optional plugin for visual model editing. | Fork branch `feature/arrows-mcp-server/apps/arrows-mcp` in `AndreAtNeo4j/arrows.app`: tools `arrows_build/edit/validate/layout/render/export`; canonical `.arrows` JSON, inline PNG/SVG, optional share URL, `.mcpb` packaging; Node + prebuilt canvas; unpublished. | Evaluate as an optional, pinned plugin — never in the default setup (no Node toolchain for SEs). Test build → agent edit → render → export share URL → manual edit in arrows.app → re-import `.arrows` JSON; document that manual edits do not sync back automatically and that the tool models schemas, not populated graph data. Acceptance: documented optional install path, round-trip verified, explicit no-default-dependency statement; request upstream publication/pinning before adoption. |

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
