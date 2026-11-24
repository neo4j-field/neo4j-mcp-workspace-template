# Product backlog

Statuses: `proposed`, `accepted`, `deferred`, `in-progress`, `done`, `declined`.
Priorities express sequencing: P0 is required for the stabilization release; P1 is
post-stabilization hardening; P2 is a future feature; P3 is experimental. Ordering
inside P0 is defined in `ROADMAP.md`.

This file contains accepted or explicitly deferred work. The complete unprioritized
harvest is preserved in `FEATURE_CANDIDATES.md`; inclusion there does not imply a
commitment or priority.

## Current focus

- **Current:** finish live-model evaluation for `TEST-003`, and verify `BUG-004`/`BUG-005` against the release server and provider paths.
- **Latest evidence:** [2026-09-10 TEST-002 deterministic regression fixtures](reviews/2026-09-10-test-002-regression-fixtures.md).
- **Completed from the current stabilization pass:** `WF-001`, `WF-002`, `WF-003`, `WF-004`, `WF-005`, `BUG-001`, `BUG-002`, `BUG-003`, `LEX-001`, `INGEST-001`, `TEST-001`, `TEST-002`.
- **In progress:** `TEST-003`, `BUG-004`, `BUG-005`.

## P0 — Automated safety net and current workflow contracts

| ID | Status | Problem and evidence | Scope | Acceptance criteria |
|---|---|---|---|---|
| WF-001 | done | Claude Desktop lexical calls previously drifted from the MCP tool contract. Runtime-schema CI coverage now checks every call-shaped Desktop lexical example, and an exact-DXT headless smoke reaches lexical ingestion. [Fix evidence](reviews/2026-09-10-wf-001-wf-003-fix.md). | Template | Every documented skill call validates against the live MCP tool schema; a Desktop smoke scenario reaches lexical ingestion. |
| WF-002 | done | The coding-agent workflow mixes JSON and Python extraction-schema contracts. | Template | Generated schema type, file extension, and extraction input agree end to end and are contract-tested. |
| WF-003 | done | Desktop verification previously checked `embedding` while the graph writer stores `text_embedding`. The skill and live DXT smoke now verify the canonical property; an immediate second embedding call reports zero work. [Fix evidence](reviews/2026-09-10-wf-001-wf-003-fix.md). | Template | Verification uses the canonical property contract and does not trigger false retries. |
| WF-004 | done | Desktop ontology membership queries previously used ownership relationship names that the implementation never read. The Desktop skill now uses `:CONTAINS` for both node and relationship types, and an executable fixture covers every canonical ontology relationship through setup, read-back, validation, and schema generation. [Fix evidence](reviews/2026-09-10-wf-004-fix.md). | Template | Ontology examples and verification queries run against a fixture ontology graph. |
| WF-005 | done | Completion currently depends on an agent remembering every required report detail. | Template | A deterministic validator checks required report sections and per-question/per-use-case records; current skills run it before claiming completion. A portable workflow controller is not required for stabilization. |
| TEST-001 | done | A reusable CI suite now runs unit, contract, report-validation, representative Neo4j integration, and exact-DXT headless Desktop smoke tests. Every package publication job depends on the suite. [Fix evidence](reviews/2026-09-10-test-001-ci-release-gate.md). | Repository | CI runs unit tests, contract tests, representative integration tests, and Desktop smoke tests; failures block publication. |
| TEST-002 | done | Deterministic fixtures now cover the retained PyMuPDF, Docling, and page-image adapters, structured ingest, text/visual extraction, partial failure, forced re-extraction, and graph-safe retry after a server restart. The restart fixture also exposed and fixed a Cypher-precedence bug that made `force=false` reprocess text sources. [Fix evidence](reviews/2026-09-10-test-002-regression-fixtures.md). | MCP servers | Small deterministic fixtures cover each current parser mode, structured ingest, extraction, re-extraction, restart, and partial failure. |
| TEST-003 | in-progress | Existing customer-derived golden extraction assets are not wired into regression testing. | Entity graph | A small, legally usable golden set runs independently of the extractor model used to judge it and reports stable quality deltas. |
| BUG-001 | done | Clearing chunks for all documents can incorrectly report that no documents need chunking (harvest B14). | Lexical graph | `clear_existing_chunks=true` with no document ID rebuilds eligible documents and has a regression test. |
| BUG-002 | done | Known relationship types could be silently dropped when one endpoint entity arrived in a later asynchronous write batch (harvest D10). Deterministic unit and live fixtures cover file-based and ontology-generated schemas. | Entity graph | The root cause is fixed and a fixture verifies expected relationship creation. |
| BUG-003 | done | Blank/invalid structured responses and exhausted retries were returned as ordinary empty results, so failed source units incremented completion and could produce a false `complete` job. Deterministic Chunk/Page and live Neo4j fixtures now distinguish eligible, selected, attempted, successful, empty, failed, and persisted sources. [Fix evidence](reviews/2026-09-10-bug-003-fix.md). | Entity graph | The minimal reproducible fixture passes and coverage/truncation failures are observable. |
| BUG-004 | in-progress | `embed_chunks` swallows prefiltered vector-index creation failures and unconditionally reports success. Reproduced on Neo4j 2025.12.1, where the Cypher 25 `WITH [...]` single-stage filtering syntax (also used by the default `index_prefilter_properties`) is unsupported: embeddings and the fulltext index are written, but `SHOW VECTOR INDEXES` returns no vector index and downstream GraphRAG vector search fails. Discovered in GraphRAG-Bench run `novel-44557-agentic-glm53flash` on 2026-09-18 (`runs/novel-44557-agentic-glm53flash/report.md`, “Issues hit during the run” §1). | Lexical graph | If prefiltered creation fails, retry a plain vector index without `WITH`; report whether the created index is `prefiltered` or `plain`; surface an error if both attempts fail; verify the named vector index exists and report its `ONLINE`/`POPULATING` state before claiming success; add regression coverage for supported and unsupported prefilter syntax, including the default call path. |
| BUG-005 | in-progress | **High:** `build_llm_params()` cannot run GPT-6-family extraction models. Unrecognized names such as `gpt-6-luna` fall into the generic branch and send `temperature=0.0`, which OpenAI rejects because the model supports only the default value. If `reasoning_effort` is supplied instead, the pinned LiteLLM 1.91.x registry predates GPT-6 and raises `UnsupportedParamsError` before the request, despite OpenAI accepting the parameter. Both paths hard-fail every entity/relationship extraction call. | Entity graph | GPT-6-family models omit unsupported `temperature` values and can pass `reasoning_effort` through LiteLLM 1.91.x using the narrowly scoped per-request `allowed_openai_params` escape hatch; behavior remains correct for GPT-5, o1/o3, Ollama, and ordinary temperature-capable models; focused parameter-construction and request-boundary regression tests cover both reported failures and at least one GPT-6 model alias. |
| LEX-001 | done | PyMuPDF jobs and source inspection reported source pages while `list_documents` and lexical verification reported zero pages because they counted only `Page` nodes. Public responses now distinguish `sourcePageCount` from `pageNodeCount`; deterministic and live fixtures cover PyMuPDF, Docling, and page-image. [Fix evidence](reviews/2026-09-10-lex-001-fix.md). | Lexical graph | APIs distinguish source-page count from graph `Page`-node count with unambiguous names, and a PyMuPDF fixture reports both consistently. |
| INGEST-001 | done | The pinned modeling server generates ingest drafts that ignore declared source-column mappings and can set relationship properties on the end node instead of a bound relationship; reproduced in the golden E2E run. [Fix evidence](reviews/2026-09-10-ingest-001-fix.md). | Modeling + ingest boundary | Workspace-generated executable queries honor `source.column_name`, bind relationship variables, set properties on the intended graph element, reject unsafe identifiers, and pass node/relationship integration tests without manual query surgery. |

## P0 — Correct extraction and embedding semantics

| ID | Status | Problem and evidence | Scope | Acceptance criteria |
|---|---|---|---|---|
| EXT-001 | accepted | Forced re-extraction may retain stale generated graph elements. | Entity graph | Re-extraction is idempotent for a run scope and has regression tests for removed labels, properties, and relationships. |
| EXT-002 | accepted | Extraction skip logic can treat partial or incompatible prior output as complete. | Entity graph | Completion is based on an explicit successful run with matching source, schema, extractor, and configuration identities. |
| EMB-001 | accepted | Embedding reuse does not record enough model and input identity to prove cache validity. | Lexical graph | Stored embeddings record provider/model/dimensions and input hash; incompatible embeddings are regenerated predictably. |
| EXT-003 | accepted | Schema/configuration changes are not represented consistently in extraction provenance. | Entity graph | Every generated entity and relationship is attributable to a source chunk, extraction run, and schema/configuration version. |

## P0 — Make writes safe and resumable

| ID | Status | Problem and evidence | Scope | Acceptance criteria |
|---|---|---|---|---|
| WRITE-001 | accepted | Document version deactivation and replacement are split across sessions and can expose partial state. | Lexical graph | A new version becomes active atomically only after its graph is complete; a failed run leaves the prior active version intact. |
| WRITE-002 | accepted | Individual long-running server stages cannot consistently recover from interruption. | MCP servers | Each server stage uses bounded idempotent batches and stage-local checkpoints; retry/restart resumes or safely repeats without duplicating graph data. A cross-server run ledger remains Trellis scope. |
| SEC-001 | accepted | Dynamic identifiers and broad prefix deletion can affect unintended graph data. | MCP servers | Identifiers are validated/quoted safely and deletion targets explicit ownership relationships rather than ID prefixes. |
| WRITE-003 | accepted | Index-creation errors can be swallowed while an operation appears successful. | MCP servers | Required index failures are surfaced, recorded in run status, and covered by failure-path tests. |
| WRITE-004 | accepted | User metadata can overwrite reserved identity and lifecycle properties. | MCP servers | Reserved properties are isolated or rejected and tested across every write entry point. |
| EXT-004 | accepted | Schema compatibility and key-property constraints are not fully validated before extraction (harvest D9/D12). | Entity graph | Extraction fails before writes with actionable errors for duplicate types, invalid relationship references, bad property types, and incompatible key constraints. |

## P0 — Fix scaling architecture inside the servers

| ID | Status | Problem and evidence | Scope | Acceptance criteria |
|---|---|---|---|---|
| PERF-001 | accepted | CSV ingestion materializes full inputs and can submit an entire dataset in one Neo4j request. | Ingest | CSV is streamed or chunked and written in bounded transactions with measured batch defaults. |
| PERF-002 | accepted | Embedding and extraction pipelines can accumulate unbounded tasks and results in memory. | Lexical + entity graph | Concurrency, queues, and retained results are bounded and configurable; backpressure is exercised by tests. |
| PERF-003 | accepted | Inline base64 images can dominate graph storage and transfer cost. | Lexical graph | Image storage has a documented policy and configurable external/reference option; size behavior is benchmarked before changing defaults. |
| PERF-004 | accepted | There is no representative performance baseline for server changes. | MCP servers | CI or a reproducible benchmark records throughput, peak memory, write batch behavior, and retry behavior for small and larger fixtures. |
| PERF-005 | accepted | Provider rate limits and failed work do not have one consistent bounded retry/dead-letter policy (harvest A4/A5). | MCP servers | Transient failures use bounded exponential backoff; exhausted items are recorded for explicit retry without blocking unrelated batches. |

## P0 — Reduce product surface and stabilize distribution

| ID | Status | Problem and evidence | Scope | Acceptance criteria |
|---|---|---|---|---|
| SURF-001 | accepted | Duplicate paths, overlapping responsibilities, and multiple client-specific artifacts increase drift. | Repository | Inventory every server, skill, proxy, and distribution artifact; assign keep/merge/deprecate decisions and remove only approved duplication with migration notes. |
| SURF-002 | accepted | The template can accumulate capabilities that belong in reusable libraries or Trellis. | Product | Record a maintained product boundary before adding features: prototyping template, shared library, and Trellis responsibilities are explicit. |
| SURF-003 | accepted | `vlm_blocks` is an experimental fourth parser surface that the owner has decided not to maintain. | Lexical graph | Remove `vlm_blocks` code, options, documentation, dependencies used only by it, and tests; retain generally useful lessons separately. PyMuPDF, Docling, and page-image remain. |
| DESK-001 | accepted | Desktop proxy pins older server versions than the source tree; the exact DXT smoke also observed the published lexical worker writing a PyMuPDF deprecation warning onto stdio. [Evidence](reviews/2026-09-10-wf-001-wf-003-fix.md). | Desktop | Desktop artifacts are built from one version source and compatibility-tested against the release. |
| DESK-002 | accepted | Desktop packaging requires an OpenAI key even when supported alternatives are selected. | Desktop | Provider credentials are conditionally required and each advertised provider configuration has a smoke test. |
| DESK-003 | accepted | The Claude Desktop packaging workflow and documentation still target DXT (`dxt` CLI, `.dxt`, and `@anthropic-ai/dxt`), while the upstream project is being renamed to MCPB (`mcpb` CLI, `.mcpb`, and `@anthropic-ai/mcpb`). The workspace has not established the required migration, compatibility, or release changes. | Desktop | Review the current MCPB specification and Claude Desktop support; document whether legacy DXT artifacts remain supported; migrate or compatibility-wrap the manifest, build scripts, package dependencies, artifact names, release automation, install guide, and exact-bundle smoke tests; validate installation, configuration, startup, and representative tool calls from the produced `.mcpb` on supported macOS and Windows environments. |
| SETUP-001 | accepted | Setup does not explicitly restrict `.env` permissions and sources it through the shell. | Setup | Credentials are written with mode `600`, parsed without shell execution, and setup is tested on supported shells/platforms. |
| SETUP-002 | accepted | Unsupported extraction-model configuration can fail only after a long run has started (harvest F9). | Setup | Setup offers a small structured-output preflight and reports an actionable failure before ingestion/extraction work begins. |
| SETUP-003 | accepted | Setup presents Docling as optional even though it is one of the three supported parser strategies and part of the intended workspace baseline. | Setup + lexical graph | Remove the Docling installation question and install the Docling extra consistently; update setup output and documentation to state its download/time cost. |
| SETUP-004 | accepted | A cold ingest-server installation appears slow without timing or dependency visibility. Its isolated environment currently resolves 103 packages and includes the broad FastMCP/Cypher MCP stack plus pandas/numpy. | Setup + ingest | Measure cold/warm sync time and downloaded/installed size; print per-server elapsed time; remove avoidable dependencies without duplicating Cypher safety behavior. |
| REL-001 | accepted | Package versions, locks, licenses, source servers, and published artifacts can drift. | Release | A release check verifies aligned versions, reproducible locks, consistent license metadata, generated artifacts, changelog, and passing CI before publish. |
| REL-002 | accepted | A Neo4j vector-query procedure used by retrieval is deprecated in the target server generation (harvest E2). | GraphRAG integration | Replace or compatibility-wrap the deprecated call and test supported Neo4j versions. |

## P1 — Post-stabilization hardening

| ID | Status | Problem and evidence | Scope | Acceptance criteria |
|---|---|---|---|---|
| DEVX-001 | accepted | Poppler/Fontconfig emitted extremely noisy cache/config warnings while rendering a valid one-page PDF during the golden E2E run. | Test infrastructure | Bundled PDF rendering uses a writable/configured Fontconfig cache or suppresses non-actionable warnings, while preserving real render failures and concise diagnostics. |

## P2 — Future capabilities after stabilization

| ID | Status | Problem and evidence | Scope | Acceptance criteria |
|---|---|---|---|---|
| DOC-001 | deferred | PyMuPDF, Docling, and page-image parsing have different strengths but need one downstream contract before adding formats. | Lexical graph | All three implement a parser adapter that emits the same canonical `ParsedDocument`; one graph writer handles all outputs. |
| DOC-002 | deferred | Automatic parser choice can hide quality/cost tradeoffs. | Lexical graph | Users can select `auto`, `pymupdf`, `docling`, or `page_image`; auto-selection records its reason and chosen parser in run provenance. |
| DOC-003 | deferred | Page-image is particularly useful for visual PDFs such as exported presentations. | Lexical graph | Page-image remains a first-class mode and preserves page image, page number, derived text, and extraction provenance. |
| DOC-004 | deferred | Non-PDF formats need structural locations beyond page numbers. | Lexical graph | Canonical locations support page/bounding box, slide, section path, and other format-appropriate anchors without fabricating pages. |
| DOC-005 | deferred | Spreadsheet files can be degraded by flattening them into lexical text. | Lexical + ingest boundary | CSV/XLSX routing is explicit: structured ingest is the default; lexical conversion requires an explicit use case. |
| QL-001 | deferred | There is no supported loop for assessing an existing graph, proposing schema/extraction changes, re-extracting, and comparing quality. | Template first; reusable in Trellis | Add an `assess-and-improve-neo4j-graph` workflow with baseline, diagnosis, proposal, approval, targeted rebuild, and before/after report phases. |
| QL-002 | deferred | Quality checks are ad hoc across duplicates, wrong labels, malformed properties, orphan nodes, missing relationships, provenance, and extraction coverage. | Shared | Define deterministic checks and thresholds, with sampled evidence for findings that need semantic judgment. |
| QL-003 | deferred | Schema changes can leave stale entities and relationships after re-extraction. | Entity graph | A rebuild scope is explicit; affected generated entities/relationships are replaced safely; source and run provenance remain queryable. |
| QL-004 | deferred | Repeated improvement rounds are hard to compare. | Shared | Persist run ID, schema version, parser/extractor configuration, metrics, decisions, and before/after deltas for every round. |

## P3 — Experiments

| ID | Status | Problem and evidence | Scope | Acceptance criteria |
|---|---|---|---|---|
| EXP-001 | deferred | AIP may make workflows easier to validate, but it does not by itself enforce runtime completion. | Side experiment | Encode one workflow in pinned AIP, add local semantic checks, and compare adherence/cost/latency against the current skill before adoption. |
| EXP-002 | deferred | Hook behavior is tool-specific and cannot be the only cross-agent guarantee. | Side experiment | Evaluate hooks for cheap preflight/postflight checks; keep workflow state and finalization portable when hooks are unavailable. |
