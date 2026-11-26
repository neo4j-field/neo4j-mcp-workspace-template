# Synthetic acceptance dataset — coverage plan

Implemented and fixture-validated; see [delivery evidence](reviews/2026-11-24-synthetic-dataset.md). Full live acceptance remains separate. All facts, names and images
must be synthetic and redistributable. Generate deterministically from one domain
model with expected counts, answers and source locations; equivalent renderings
must not be treated as independent facts or accidental duplicates.

Provide a small smoke profile and the agreed benchmark profile (10k CSV rows and
50-page PDF). Pageless formats have equivalent content rather than fake pages.

| Surface | Dataset coverage and expected assertions |
|---|---|
| CSV ingest | Multiple files; nodes and relationship properties; declared column mappings; strings/numbers/booleans/dates/nulls; normalization-compatible bridge keys; case-sensitive keys; no orphans or duplicate merges. |
| Document formats | PDF, Markdown (.md/.markdown), TXT (.txt/.text), local HTML (.html/.htm/.xhtml), DOCX; mixed-folder routing and same-stem names. Alias extensions reuse canonical content. |
| PDF parser choices | PyMuPDF text/assets; Docling native hierarchy; page-image visual reasoning; text-only, layout/table-heavy and visual pages with known answers. |
| Native structure | Nested headings, repeated titles under different parents, TOC, paragraphs, lists, tables, images and captions where supported. Preserve source order, Unicode and logical anchors; no invented structure/pages in TXT. |
| HTML/linked assets | Static content and local source parsing; linked images stay references and no remote asset fetch occurs. Embedded DOCX images remain usable. |
| Chunking | Structured, token-window, by-section and by-page; boundary-spanning facts, long sections for pagination, exact Unicode reconstruction and truthful pageless fallback. |
| Extraction schemas | Data-model-to-Pydantic conversion and Ontology Graph Spec YAML/JSON import→DB→schema generation; validate keys/types/endpoints and supported roundtrip. Arbitrary Python→ontology export is an explicit unresolved acceptance case, never pre-labelled passed. |
| Ontology features | Descriptions, aliases, supported normalizers and blocklists; file/DB get_ontology; declared versus realized schema; bounded context and relationship paths. |
| CSV/document bridge | Shared entities, case normalization, conflicting PDF/document values, default preserve-existing plus explicit overwrite; proposed values/conflict metadata and entity/relationship source claims. |
| Lifecycle | Repeat ingest/extract/embed; schema/input/model identity changes; forced re-extraction; owned replacement; atomic document publication; version/chunk-set activation; scoped deletion/rebuild preserving unrelated data. |
| Search and navigation | Vector/fulltext, filtered queries, expected identifiers and paraphrases, node/relationship fulltext fixtures, index readiness/repair; document/outline/section browsing, long-result pagination, page/anchor citations; tools hidden on unsupported graphs and visible with usable content. |
| Visual features | Synthetic diagrams with facts absent from surrounding text, image descriptions/reading, table interpretation; explicit expected capability by parser instead of asserting every format supports every feature. |
| Failure cases | Separate clearly named invalid fixtures: reserved metadata, malformed schema, incompatible indexes, failed/cancelled write, provider failure, unsupported or invalid-encoding file. Expected errors and preserved graph state. |
| SE workflow | Start-fresh and scoped rebuild prompts; CHATBOT validated answers plus ANALYTICAL query outputs; manual Claude Code QA checklist with actual prompts/tool calls/results. |

Publish a manifest with a feature→fixture→assertion mapping and explicit unsupported
cells, a generator command, a short SE walkthrough and machine-checkable expected
answers/counts. Record hardware, versions, parser/model/provider, setup/cache state,
time to first validated answer and observed memory/storage for the benchmark.

Keep corrupt/negative files out of the default happy-path ingestion folder. Use a
disposable database and never include customer files or credentials.
