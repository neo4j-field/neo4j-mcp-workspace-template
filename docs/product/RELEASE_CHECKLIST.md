# Pre-release checklist

Release purpose: a reliable, understandable SE graph POC tool, including **N1 and
N4** by owner request. Check these finite outcomes; do not turn deferred architecture
into additional release gates. Preserve existing commits and use reviewable slices.

| Check | Current evidence / remaining action |
|---|---|
| N1 native Docling hierarchy | Real two-page Docling conversion passed: native three-level nesting, stored heading paths and PageIndex page citations verified. [Live evidence](reviews/2026-11-24-live-release-acceptance.md). Manual Claude Code Docling/PageIndex follow-up passed intended hierarchy, PDF citations and full pagination; two extra headings keep exact hierarchy acceptance partial (LEX-004). [Evidence](../../outputs/reports/claude_followup_20261126-113305/run_summary.md). |
| N4 Ontology Graph Spec | Automated and manual Claude Code import/generation/extraction, supported DB export roundtrip and file-backed retrieval context passed. [Manual evidence](../../outputs/reports/claude_followup_20261126-115402/run_summary.md). Bounded direct Python export is now implemented: supported scalar generated contracts preserve key/type/endpoint/normalization semantics; unsupported arbitrary Python behavior is rejected. 38 focused tests and real maintenance schema export passed. [Export evidence](reviews/2026-11-26-python-schema-ontology-export.md). Alias/blocklist execution was not separately exercised manually. |
| Claude Code tool refresh — E1-REFRESH | Manual run missed PageIndex tools after ingest; user confirmed direct PageIndex listing/outline/section retrieval works in Claude Code after reconnect, with correct Markdown source anchors and null pages. Fix implemented and isolated public-MCP external-write acceptance passed both directions; 33 unit tests plus four subtests passed. Claude Code notification handling still needs acceptance after loading updated code. [Fix](reviews/2026-11-26-pageindex-refresh.md). [Review](reviews/2026-11-26-claude-smoke-review.md). |
| GraphRAG retrieval delivery | PageIndex-style navigation and `get_ontology` implemented/tested locally in the separate GraphRAG repository. [Validation](reviews/2026-11-24-graphrag-retrieval.md). [Draft PR #2](https://github.com/neo4j-field/mcp-neo4j-graphrag/pull/2) is open; setup and proxy source share its immutable commit pin. GraphRAG unit and Neo4j5.26/2026.09 integration CI pass at updated shared pin 0867f08 (including automatic discovery notifications), and fresh clone/proxy transport checks passed. Publish/rebuild Desktop artifacts before release. |
| Additional document formats | Markdown, TXT, local HTML/XHTML and DOCX implemented. 31 actual-provider checks passed across all four formats, including extraction/CSV merges/provenance/vector/fulltext/PageIndex and truthful pageless anchors. PDF regressions retained. [Evidence](reviews/2026-11-24-document-formats.md). |
| Remaining concrete bugs | WRITE-001 atomic publication and WRITE-003 fulltext error/repair fixes passed focused failure-path checks. SETUP-001/002 and experimental parser removal implemented. [Index evidence](reviews/2026-11-24-search-indexes.md). SEC-001 and WRITE-004 fixed: 35 lexical fast checks + 6 isolated DB checks. EXT-003 closed by live source/run/model/fingerprint and relationship-claim verification. [Bug evidence](reviews/2026-11-24-lexical-boundaries.md), [live evidence](reviews/2026-11-24-live-release-acceptance.md). Full history is deferred. |
| Final regression and hosted CI | Existing local evidence: [81 fast tests, 56 isolated DB checks](reviews/2026-11-24-parallel-hardening.md). N1/N4 relevant local checks now pass (98 fast, 43 database checks). Pending: hosted CI green on the exact final release revision. |
| Real clean-clone setup | Passed: empty-cache source-export setup 27.1s; actual clean Git clone of the current source snapshot with fresh environments/reused dependency cache 7.0s. All 7 configs validated. First actual cold Docling conversion 45.3s. [Evidence](reviews/2026-11-24-cold-setup.md). Final committed release revision still needs its delivery check; cache footprints are not network bytes. |
| Combined live CSV + PDF | Latest synthetic smoke: all seven answers and report validation passed, actual ontology extraction/vision/embeddings/vector/fulltext/PageIndex complete. APOC required explicit enablement; exact hierarchy remains partial. [Latest evidence](reviews/2026-11-24-synthetic-smoke-live.md). Passed on current combined source: both CSVs, original PDF, actual extraction/normalized bridge merging/CSV preservation/conflicts/provenance, real embeddings/vector/fulltext, native Docling hierarchy, ontology context and PageIndex. Initial failure was a harness-only offline-metadata override; normal unchanged runtime passed. Original failed evidence retained; final three-question report validated. [Evidence](reviews/2026-11-24-live-release-acceptance.md). |
| Desktop/version alignment | Pending DESK-001/REL-001. Current manifest 0.1.1 → proxy 0.2.1 → lexical 0.2.0/entity 0.4.0 trails source lexical 0.2.1/entity 0.4.1. Bump affected versions, align pins/locks/artifact and smoke the actual release package. Existing hosted smoke skips embeddings. |
| Restricted-user onboarding | Passed 4 real Enterprise authorization cases: missing privileges fail before provider work; full privileges work; an exact admin-precreated constraint permits runtime roles without CREATE CONSTRAINT. SHOW CONSTRAINT remains required. Error/docs now explain both paths. [Evidence](reviews/2026-11-24-restricted-onboarding.md). |
| SE workflow documentation | README now includes the scoped rebuild/start-fresh recipe and compact parser-selection table; final workflow review pending. Confirm the recipe with target/effects/verification; surface the existing [parser selection table](../../.agents/skills/develop-neo4j-graph/references/HANDLE_UNSTRUCTURED_DATA.md#parse-mode-guide) rather than invent a second guide. |
| Benchmark failure investigation — EXT-005 | Investigation complete: clarified assigned-procedure descriptions passed a separate full workload with exact counts, 7/7 answers, and all original CSV values/edges preserved. Original failed run and inputs retained; decide whether to adopt the clearer contract. [Controlled evidence](reviews/2026-11-26-procedure-contract.md). Original discrepancy: additional restart-verification procedure and two assignments (81/80 procedures, 10,002/10,000 USES_PROCEDURE edges). Trace source/schema semantics, distinguish allowed enrichment from corruption and retain the failed original run. Resolve the assigned-procedure/substep contract with a narrow fix/configuration or explicit acceptance decision; verify the intended graph and rerun after substantive changes. Seven correct answers alone do not close this item. [Evidence](reviews/2026-11-24-synthetic-benchmark-live.md). |
| Docling section-extraction quality — LEX-004 | Controlled investigation completed: native Docling misclassifies bold labels/printed contents; clear labels preserve exact intended hierarchy. Adapter preserves native classifications/levels. [Decision/evidence](reviews/2026-11-26-docling-quality.md). Exact author hierarchy remains a documented limitation. Review extra/missing headings, levels and parents using the reproducible controls as needed. Preserve existing smoke/benchmark baselines. Compare native Docling output, adapter output and graph/chunk paths; record root cause, retrieval impact and a fix/configuration/limitation decision. Feed results into N1 acceptance and SURF-004 before retiring correction capabilities. |
| Section hierarchy tool retirement — SURF-004 | Required before release. Validate whether N1 covers `assign_section_hierarchy`, including inference, manual correction, legacy graphs and heading-path propagation. Owner preference: remove the old tool and exclusively used implementation if redundant. Record any remaining capability gap and decision; preserve section-based PageIndex retrieval and test the resulting surface. |
| Physical graph model review — GRAPH-001 | Required before release: detailed owner walkthrough of added labels/types/properties, list-valued metadata, customer/agent schema clarity, cardinality and potential supernode/hotspot growth. Explain capability, necessity in stabilization, simpler alternatives and keep/simplify/remove/defer choices. Include ONT-003 single-spec-node proposal. No data/model migration while concurrent user tests run. |
| Repository tidy-up and human/agent usability — SE-003 | Required before release. Review files, public tools and implementation code for obsolete, redundant or superseded behavior; remove confirmed unnecessary surfaces after checking runtime/dynamic dependencies, setup, CI, packaging and agent/reference usage; preserve user data and useful historical evidence. Propose concrete improvements to repository navigation and onboarding. Audit documentation for freshness, accuracy and the right level: a clear human happy path and code map, deeper linked internals, and consistent current AGENTS.md/skills/tool examples for agents. Validate links/examples and a fresh SE/agent walkthrough; retain a record of changes and unresolved gaps. |
| Reference workload | Warm full synthetic benchmark executed: 10,000 product rows + 102 auxiliary rows, 50 pages, 75 sources; 61.866s to first validated answer, 7/7 target answers passed. Strict graph oracle failed on one additional procedure / two links (EXT-005); do not call this an overall quality pass. Host/runtime/cache/resource context retained. [Evidence](reviews/2026-11-24-synthetic-benchmark-live.md). Cold setup/workflow timing remains separate. |
| Release notes | Pending minimal version/changelog update: concise breaking behavior, legacy rebuild expectations and embedding constraint privileges. Verify affected package/lock/proxy/Desktop consistency. No general migration guide required. |

## Working order for 25 November 2026

This is the order of work, not a promise that release gates will fit in one day.
The entries above and the backlog remain the source of truth for completion.

1. **User — Claude Code acceptance:** run `SMOKE_TEST_PROMPT.md` from the repository
   root. Then complete the five QA-001 checks below: ontology-file extraction,
   schema-to-ontology export, ontology-file retrieval context, native hierarchy and
   PageIndex use/visibility. Direct arbitrary Pydantic-to-ontology export is still
   unproven; record the supported route or gap explicitly.
2. **Agent — investigate benchmark and hierarchy findings in parallel:** EXT-005
   covers the extra procedure/two links and extraction granularity; LEX-004 covers
   controlled PDF layout variants and native Docling versus adapter output. Retain
   current fixtures/results. Fix narrowly or document an explicit acceptance
   decision, then assess SURF-004 removal of the old hierarchy tool.
3. **Agent — SE-003 repository/usability cleanup:** review files, tools and code;
   remove confirmed obsolete material, improve navigation/code-entry-point maps,
   and bring human documentation and agent skills/contracts up to date. Verify
   the APOC prerequisite is discovered before paid work (SETUP-005).
4. **Agent — final verification:** rerun checks affected by fixes/removals; repeat
   smoke/benchmark after substantive extraction/parser changes. Validate setup
   from a clean clone of the final revision and finish the required cold-setup
   evidence without deleting shared caches. Keep the warm benchmark labelled warm.
5. **Release preparation:** create reviewable commits/PRs, settle GraphRAG delivery
   and the final source pin, align versions/locks/changelog/Desktop artifacts
   (DESK-001/REL-001), smoke the actual release package, and require hosted CI green
   on the exact release revision. Review remaining findings before publication.

## Manual Claude Code acceptance — QA-001

**Owner: user. Status: in progress — core smoke, supported ontology workflows and functional Markdown/Docling PageIndex passed; explicit gaps below remain open.** Requested 2026-11-24. These are manual
acceptance tests, separate from automated test results. Load the pinned server
revision in Claude Code and retain prompts, generated artifacts and outcomes.

- [x] **Use an ontology file as the extraction schema (via import/generation).** Give Claude Code an
  Ontology Graph Spec YAML/JSON file and ask it to extract entities/relationships
  from a PDF using that ontology. Verify the resulting labels, keys, property
  types and relationship endpoints. Record the actual import/generation steps.
- [ ] **Export an arbitrary Python extraction schema as a graph ontology — UNSUPPORTED/OPEN.** Starting with an
  extraction schema used in the POC, ask Claude Code to export a Neo4j Ontology
  Graph Spec YAML/JSON file. Validate the file and check that keys, properties,
  endpoints and supported normalization rules survive a roundtrip.
- [x] **Use an ontology file instead of routine get_schema calls.** Configure
  the file, ask domain questions and verify Claude Code uses `get_ontology` for
  text-to-Cypher context, including aliases and relationship paths. Physical
  schema/index inspection remains available when the ontology cannot answer it.
- [ ] **Build section hierarchy from titles/subtitles — PARTIAL.** Parse a PDF with nested
  headings using Docling. Manually compare the source with stored section levels,
  `HAS_SUBSECTION` links and full heading paths in section-aware chunks.
- [x] **Use that hierarchy for PageIndex retrieval.** Ask questions that require
  browsing an outline and reading a section/subsection. Verify the agent uses the
  PageIndex tools, returns the right source text/page citations and can continue
  through long content. Manually passed on the new Docling PDF on 26 November:
  correct Thermal reset citation on page 1, four continuation calls through REF-16
  on page 3, no Markdown fallback. [Evidence](../../outputs/reports/claude_followup_20261126-113305/run_summary.md).
- [ ] **Automatic navigation-tool visibility in Claude Code — E1-REFRESH.**
  Verify tools are hidden on an unsupported graph and become visible after ingest
  without manual reconnect. The follow-up began with tools available and does not
  prove this transition.

**Manual ontology result — 26 November 2026, run 20261126-115402:** initialized
and freshly imported into the existing user-created ontology database; no new
database. Generated 4 entity / 4 relationship types; extracted only the nine new
Docling chunks (7 nonempty persisted, 2 empty, 0 failed), preserving CSV values,
case-sensitive sensors and domain counts/edges. YAML/JSON exports are equivalent
and normative-valid; supported semantic roundtrip passed. Direct arbitrary Python behavior remains unsupported; the new bounded generated-schema exporter has passed automated acceptance. [Export evidence](reviews/2026-11-26-python-schema-ontology-export.md). File-backed get_ontology returned source=file
and guided the correct read-only pump/procedure query. ONTOLOGY_FILE was restored
to unset; the owner subsequently confirmed the final GraphRAG reconnect. Dedicated manual
alias/blocklist runtime scenarios were not run. [Evidence](../../outputs/reports/claude_followup_20261126-115402/run_summary.md).

**Manual PageIndex result — 26 November 2026:** Markdown navigation passed after
reconnecting neo4j-graphrag: list_retrieval_documents → get_document_outline →
get_section_content, with no fallback. Operations → Details → Thermal reset
(sec_3, level3) returned 423 characters /4elements, has_more=false,
fallback_used=false. Correct answer:12minutes/CV-7. Citation anchors element:21
and element:23, null page_number/page_index. No graph modifications. This closes
the basic Markdown/client retrieval check only; Docling PDF hierarchy/citations,
long-content pagination in Claude Code and visibility refresh without reconnect
remain open (E1-REFRESH).

**Docling follow-up — 26 November 2026, run 20261126-113305:** all four PDF
pages parsed; 50 elements, 11 Sections and nine chunks at chunk_size=400. All nine
native-outline headings and intended parent links are present and correct.
Two extra headings remain and propagate into chunk paths: Operator checklist
(level 5) and printed contents (level 4). Exact hierarchy remains partial under
LEX-004; no correction tool was used. Existing documents, CSV data, authoritative
values and 48 extraction links were preserved. No ontology or new extraction tests
were performed. JSON evidence files were read and parsed during review.

For each item, record pass/fail, the prompt, source files, actual tool calls and
artifact/report paths. An unsupported route is a gap to record and resolve, not a
pass. In particular, the current extraction route imports the ontology file into
the Ontology DB and generates Pydantic models; `schema=` still expects Python.
Current ontology export starts from the Ontology DB: direct export from an
arbitrary Pydantic schema is not established and must be checked explicitly.

Existing local regression evidence uses stubbed provider paths and disposable
Neo4j databases. Earlier live extraction runs precede the latest combined changes.
Neither establishes final release readiness. Record actual revision, commands and
outcomes when completing the pending checks.

MCPB migration is deferred for scope; existing DXT artifacts remain supported.
[Roadmap](ROADMAP.md) · [Backlog](BACKLOG.md) · [Simplification decisions](reviews/2026-11-24-se-simplification.md)
