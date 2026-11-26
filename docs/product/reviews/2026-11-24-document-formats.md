# Local document formats — 2026-11-24

## Implementation

`StructuredDocumentParser.parse(path, source_id, version=1, metadata=None, **options)`
adds local Markdown (`.md`, `.markdown`), literal TXT (`.txt`, `.text`), HTML
(`.html`, `.htm`, `.xhtml`) and DOCX (`.docx`). The server routes these extensions
to `parse_mode="document"` independently of the default PDF parse mode.

- TXT remains literal: Markdown-looking characters do not become headings,
  links, lists or tables. Stored paragraph strings reconstruct the input text;
  anchors identify actual source line spans.
- Markdown, HTML and DOCX use Docling's declarative backends, not PDF layout
  models. Native heading levels, lists, table text/HTML and native caption
  references are retained. Embedded DOCX images are stored as PNG when available.
- Markdown/HTML source h1 maps to Docling TitleItem and h2 maps to native
  SectionHeaderItem level1; the adapter restores source heading depth rather
  than collapsing both to level1. DOCX retains its native style levels.
- `sourceFormat` identifies `markdown`, `text`, `html` or `docx`; the source URI
  is the actual absolute local file. Pageless elements have null page numbers
  and explicit `sourceAnchor` values (`element:N` or `lines:A-B`), not invented
  PDF page coordinates. No Page nodes are fabricated.
- External image references remain text references. Remote/local resource
  fetching, browser rendering and chart rendering are disabled. HTML scripts
  are not executed. Header-free HTML prefaces are retained even when Docling
  classifies them as furniture.
- Metadata uses the shared lexical validation boundary. Image/table/section
  extraction flags are honored. TXT/Markdown/HTML require valid UTF-8; invalid
  or mixed encoding produces an actionable error instead of guessing.

## Focused parser verification

Six deterministic tests run actual lightweight conversions, including generated
DOCX with native headings, a list, table and embedded PNG. They verify extension
aliases, literal TXT preservation, hierarchy, tables, pageless anchors, metadata,
extraction flags, malformed encoding and explicit zero remote-fetch calls.

`tests/unit/test_structured_document_parser.py`: **6 passed**.

The tracked fixtures are in `tests/fixtures/documents/`; DOCX is generated in a
temporary directory by the test. No dependency upgrade was required beyond the
already installed Docling 2.152.0/core 2.108.0 baseline.

## Actual-provider acceptance

**Clean acceptance passed: 31/31 checks**, using actual configured providers.
The successful run is
`outputs/reports/format_acceptance_20261124/run_20261124T203216Z/summary.json`.
The earlier failing run remains preserved at `run_20261124T202942Z/` in the same
artifact directory; its concrete TXT metadata bug and fix are described below.
The harness is `outputs/reports/format_acceptance_20261124/live_formats.py`.
It uses four real local stdio MCP servers with their installed executables and empty CLI argument lists. Both
Neo4j connection aliases and all ontology connection settings are overridden to
the disposable `formats-live` / `formats-ontology` databases for the first run
and fresh `formats-live-rerun` / `formats-ontology-rerun` databases for the clean
rerun. Workspace graph credentials and generated MCP configuration are not modified.

The authorized workload copies the original synthetic maintenance PDF's facts
into all four new formats, ingests the original two CSV files, then exercises
parsing, chunking, actual configured embeddings/extraction, bridge-node merging,
provenance, source citations and vector/fulltext retrieval. Models remain
`gpt-6-luna` and `text-embedding-3-small` (1536 dimensions), with normal configured
LiteLLM runtime metadata. No model/provider substitution is permitted.

### First-run evidence and bug found

- Four actual default-routed parses completed, with four active pageless chunks,
  source formats and truthful anchors. No Page nodes were created.
- The original two CSVs produced three normalized bridge nodes. Four actual
  `text-embedding-3-small` vectors were 1536-dimensional.
- Actual `gpt-6-luna` extraction completed for all four sources, with zero failed
  sources: three merged domain entities, four domain relationship types and
  twelve `EXTRACTED_FROM` records (three per format). Existing CSV procedure
  action survived; each format recorded its proposed action and conflict.
- Markdown content/outline/vector retrieval passed. TXT content citations and
  heading-free outline passed, but its vector document-name filter returned no
  hit. Inspection confirmed the TXT Chunk had `documentName=""` while its owning
  Document had the correct name. Other formats' chunks had correct names.
- The failed assertion and exact returned records remain in `summary.json`,
  `061_graphrag_vector_search.json`, and
  `query_chunk_names_failure_inspection.json`. Verification stopped before
  remaining HTML/DOCX vector and combined fulltext checks. No model/provider
  fallback was attempted; all provider operations had succeeded.

### Clean rerun after the observed bug fix

The shared chunk writer now derives `Chunk.documentName` and `sourceFormat` from
the actual owning Document for every chunking strategy. A fresh database rerun
was used; provenance-bearing failed-run records were not patched or replaced to
manufacture a passing result.

| Format | Actual parse/chunk/verify | Actual embedding/extraction | Source retrieval | Vector/fulltext |
| --- | --- | --- | --- | --- |
| Markdown | pass | pass | native outline, element anchors, null pages | pass |
| Literal TXT | pass | pass | no invented outline, line anchors, null pages | pass |
| Local HTML | pass | pass | native outline, element anchors, null pages | pass |
| DOCX | pass | pass | native outline, element anchors, null pages | pass |

The clean run contains four Documents, four active Chunks and zero Page nodes.
All four actual vectors have 1536 dimensions and configured embedding identity.
The extraction job completed all four sources with zero failed sources. Domain
state remains three normalized CSV bridge nodes and four expected domain
relationships, with twelve source-specific `EXTRACTED_FROM` links. CSV procedure
action is unchanged and each format records its proposed action/conflict.

Each document's content returned its actual source format and anchors with null
page citations. TXT reported no section structure; the other formats exposed
their native two-level outline. Each of four actual vector calls, filtered by
its own document name, returned that format's chunk. One actual fulltext query
returned all four formats.

Exact tool arguments/results, schema snapshot, original copied maintenance facts,
input files, topology, vectors, domain/provenance records and all 31 checks remain
in the successful run directory. This uses the existing file-based extraction
schema; the separate ontology import/export path was not retested here. The
provider workload is tiny synthetic text; embedded DOCX image and table handling
were verified in the focused real parser tests rather than additional VLM calls.

## Boundaries

This is a small synthetic functional check, not a throughput or general document
accuracy claim. DOCX has no stable physical pagination in this path; original
element anchors are used. External resources are not expanded. Literal text
formats currently require UTF-8. Historical ownership/provenance migrations and
production-scale processing remain outside this feature.

## Public API and graph integration

Extension routing covers Markdown/TXT/HTML/DOCX aliases and mixed PDF/document
folders, without changing PDF parser defaults. Same-stem source IDs stay distinct;
ambiguous legacy-PDF collisions are rejected before processing. Version remapping
updates structural IDs/references only, preserving literal text, metadata and file
paths. TXT verification reconstructs original text without inserted blank lines.

Validation includes 6 routing/remap unit checks, 6 actual parser checks (including
real XHTML with Unicode), 5 pageless graph/chunker unit checks and 5 isolated graph
integrations. Two additional public MCP integrations use actual spawned workers,
cover every new format and all four chunking strategies, preserve PDF ingestion,
and verify documentName/sourceFormat/sourceAnchors persistence.

The GraphRAG citation update is committed to its existing draft PR; the workspace
shared revision resource pins that change. Full package tests: 25 unit checks and
11 database checks. Hosted unit, integration and CodeQL checks passed on commit `eaab5bc`. Manual Claude
Code acceptance and final release packaging remain separate release tasks.

Final combined regression: 52 lexical unit/contract tests and 21 setup/workflow contracts passed.

Cleanup: the dedicated `formats-acceptance-check-20261124` container was removed after verification. Saved reports and fixtures remain available; the configured user database was not modified.
