# Stabilization release scope audit

Date: 2026-11-26  
Baseline: `9ed5a3be1ba946bf4f9f1a0adb26d99c78e6016f`  
Audited state: root HEAD `5ab2613` plus working tree; GraphRAG `0867f08`  
Inputs: Codex implementation report/inventory, independent code/diff review by four audit agents

## Owner decisions — 2026-11-26

- **Exclude C05+C06:** safe source-scoped re-extraction and its run/claim/ownership schema are not release goals.
- **Exclude C13:** safe embedding-cache reuse and its identity/lock schema are not release goals.
- **Exclude C17+C18:** PageIndex was an unvalidated test and is not part of this release.
- **GraphRAG remains a distinct repository.** Produce a separate patch release containing only the retained search/index fixes; do not integrate its source into the workspace repository.
- **Include N1 (C15), N4 (C19+C21), and C16 document formats**, with proper testing as a release gate. N1 behavior must be verified across the newly supported document types where applicable.
- **C20 remains under design review with N4:** decide the ontology source-of-truth, file-versus-DB behavior, and GraphRAG boundary before approving implementation/release.
- **Include Claude Desktop:** complete package/version/DXT alignment and exact-artifact testing rather than releasing source-only.
- **Remove `assign_section_hierarchy`** as previously decided; update implementation, skills, docs, and tests together.

Unless explicitly changed later, the previous extraction model default should remain: changing it to `gpt-6-luna` is not required by stabilization, N1, or N4.

## Executive recommendation

**Do not publish the current tree as-is.** The working scope is stabilization plus explicitly promoted N1/N4/C16 features, with Desktop included. C20 requires a design decision with N4 before inclusion. The current tree also contains excluded persistence architectures and unvalidated feature experiments, and it is not yet a reproducible release candidate: runtime files and tests are untracked, package versions are unchanged, and Desktop still launches old published components.

For the release:

1. First inventory, isolate, and test the correctness/stabilization fixes on a clean release branch.
2. Remove/defer the extraction ownership/run ledger (C05+C06) and embedding identity/publication architecture (C13); recover the smaller correctness fixes without their persisted schema.
3. Review, correct, or reimplement N1 (C15), N4 (C19+C21), and C16 on that stable base, with dedicated feature and cross-feature acceptance tests.
4. Discuss C20 jointly with N4 before approving its design or release inclusion. Exclude PageIndex retrieval/refresh (C17+C18).
5. Publish a separate GraphRAG patch containing only retained search/index fixes, then consume that released version from the workspace. If approved, C20 is a separate GraphRAG feature change, not part of that patch.
6. Remove `assign_section_hierarchy`, resolve the release blockers below, and run hosted CI plus exact-artifact Desktop smoke tests on a committed release candidate.

The excluded implementation should be preserved on a separate feature/experiment branch. **Do not partially strip schema fields or checks while retaining C05/C06 or C13 behavior**: remove each architecture as a coherent unit and restore a deliberately simpler extraction/embedding contract.

## What was verified

- Codex's inventory matches the actual root and GraphRAG change sets. All 250 non-deleted root files and 26 GraphRAG files matched their recorded hashes during this audit.
- No C01-C28 implementation group was wholly absent from the report.
- The schema ledger is substantially accurate, with corrections noted below.
- No code or database was modified by this audit. No Neo4j, provider, network, or integration tests were run.
- 159 local unit/contract tests passed across five fully runnable groups. A sixth synthetic group had 6 passes and 5 errors because local `reportlab` is missing; CI installs that dependency explicitly. These results do not verify hosted CI, live extraction quality, clean-clone setup, or packaged Desktop behavior.

## Recommended C01-C28 disposition

| ID | Recommended disposition | Reason and boundary |
|---|---|---|
| C01 | **Keep, simplify** | Correct workflow/Desktop examples and structural report validation are stabilization. Relax brittle Markdown conventions and remove the inactive future `graph_quality_report` contract. Validation does not prove answer correctness. |
| C02 | **Keep core; ownership markers follow C06** | CSV mapping, relationship binding, and null conversion fix real ingestion defects. `__structuredSource`/`__structuredProperties` are needed only by C06. |
| C03 | **Keep** | Explicit empty/failed outcomes and endpoint-before-relationship persistence are core correctness. If C06 is deferred, recover/reapply these fixes without the ownership publisher. |
| C04 | **Keep normalization; split ownership coupling** | Key normalization and conservative property precedence prevent bad merges and overwrites. Proposal/conflict persistence is embedded in C06 and must follow that decision. |
| C05 | **Defer with C06** | Exact restart-safe completion is useful, but the current run ledger is committed through C06. A one-shot POC can always extract or use fresh sources instead. |
| C06 | **Defer from stabilization** | This is source-scoped contribution architecture, not a small merge fix. It is valuable for repeatable re-extraction but excessive as an always-on default for a one-shot demo. Cannot be hidden by a tool flag. |
| C07 | **Keep** | Early schema validation and typed endpoints prevent provider spend and malformed writes. Trim C06/C13-only reserved names if those architectures are removed. |
| C08 | **Keep** | Explicit rebuild selection and truthful page accounting fix existing behavior. Ship response renames with matching skills/contracts. |
| C09 | **Keep fixes; retain previous model default** | Docling completion gating and request compatibility are stabilization. The `gpt-6-luna` default change is excluded unless separately approved. |
| C10 | **Keep** | Atomic one-document lexical publication fixes partial replacements without introducing new graph concepts. |
| C11 | **Keep** | Exact deletion and reserved-metadata validation are narrow safety fixes. Cross-server claim cleanup remains out of scope. |
| C12 | **Keep after correction** | Index readiness/error handling is stabilization. The claimed unsupported-only vector fallback is not implemented: the first attempt catches every `Exception`. Narrow it or correct the documented behavior. |
| C13 | **Defer from stabilization** | Exact embedding identity and atomic publication solve real stale-vector/concurrency problems, but add five properties, a lock label/constraint, privileges, and regeneration costs. Prefer a simpler explicit refresh/overwrite contract for the POC release if cache guarantees are not required. |
| C14 | **Keep ordering; defer ranges** | `Element.order` and `Section.order` fix deterministic navigation. `Section.pageStart/pageEnd` primarily optimize PageIndex and can be deferred or computed at read time. |
| C15 | **Include as approved N1 feature; test gate** | Native Docling hierarchy is explicitly promoted. Validate real-PDF hierarchy/chunking, ambiguous-heading limitations, all affected chunkers, and packaged/Desktop behavior. It does not require PageIndex. |
| C16 | **Include after review/rework; cross-feature test gate** | Include Markdown/TXT/HTML/DOCX support on the stabilized base. Verify N1 hierarchy/chunking and retrieval behavior across applicable formats. Remove/defer stored `Chunk.sourceFormat` and `Chunk.sourceAnchors` unless a production consumer is added. |
| C17 | **Defer as feature** | Four new read-only retrieval tools, pagination, and citation semantics are not stabilization. Native hierarchy and lexical ingestion do not depend on them. |
| C18 | **Defer with C17** | Conditional visibility is useful; the two-second observer adds continuous reads and depends on client notification support. If C17 is promoted, consider gating without the observer first. |
| C19 | **Include as approved N4 feature; test gate** | Include bounded, validated ontology import/export using the existing ontology graph. Verify normative/semantic roundtrips, unsupported-case rejection, rollback, real MCP calls, and packaged/Desktop behavior. |
| C20 | **Design review with N4 before inclusion** | Discuss ontology source-of-truth, file-versus-DB precedence, relationship to C19/C21, optional configuration, and the separate GraphRAG repository boundary. Do not expose an unconfigured tool that errors by default. |
| C21 | **Include with approved N4; test gate** | Include supported Python-schema-to-ontology export with C19. Add its omitted unit suite to CI and perform fresh packaged-client acceptance; retain bounded-support/trusted-Python caveats. |
| C22 | **Use separate GraphRAG patch release** | Keep GraphRAG source and delivery in its own repository. Publish only retained search/index fixes there, then consume the released version; do not pin the current experimental feature commit. |
| C23 | **Keep safety; split dependency policy** | Keep literal dotenv parsing, 0600 permissions, timing, and optional model preflight. If C15/C16 are deferred, restore an optional Docling path rather than making the heavy install mandatory. |
| C24 | **Keep scope reduction; remove hierarchy tool** | Remove `vlm_blocks`, the no-op TOC argument, and `assign_section_hierarchy`. Update runtime, skills, docs, and tests together; N1 does not preserve the manual-correction tool. |
| C25 | **Keep, align to retained scope** | Publish gates and deterministic regressions are stabilization infrastructure. Add omitted intended suites and remove/adjust tests for deferred features. |
| C26 | **Keep as optional developer tooling** | Synthetic fixtures and benchmarks do not expand runtime scope. Keep generated data/reports out of the product payload and do not present saved live evidence as final-release verification. |
| C27 | **Keep, simplify** | Documentation should describe the approved release only. Move ownership/fingerprint/lock mechanics and historical reviews out of the happy path. |
| C28 | **Mandatory release work** | Desktop is included. Complete coordinated version bumps, proxy child pins, locks, wheels, DXT rebuild, and exact-artifact installation/smoke before release. |

## Why the larger database changes were made

### C05+C06: extraction completion and source-scoped ownership

**Problem addressed.** The released behavior treated any provenance as completion, could skip partial results, reprocessed valid-empty results, left stale properties/labels/relationships after re-extraction, and risked deleting shared CSV/user data during cleanup.

**What the new design enables.**

- Exact reuse of a completed source/schema/model/configuration fingerprint, including valid-empty results.
- Atomic replacement of one source/scope's contribution while preserving other sources and external edits.
- Relationship-level provenance through claim nodes, since Neo4j relationships cannot themselves have provenance relationships.
- Inspection of rejected property proposals/conflicts instead of silently overwriting authoritative values.
- Conservative withdrawal and garbage collection after removed or empty extraction output.

**Schema cost.**

- New `EntityExtractionRun` and `EntityExtractionClaim` labels.
- New `PROCESSED_SOURCE` and `CLAIM_SOURCE` relationship types.
- Additional `EXTRACTED_FROM` identity/properties.
- Customer-visible `__extraction*` properties on domain nodes/relationships and source nodes.
- `__structuredSource`/`__structuredProperties` on compiled CSV output.

**Why this exceeds stabilization.** These guarantees matter for repeatable, long-lived, multi-source graphs. They are not necessary for a fresh-database, one-shot POC. Costs include legacy refusal without migration, accumulated run/claim records, element-ID coupling across export/reimport, persistent lock counters, and overlapping-job operational constraints. Missing claim/run indexes are not demo-scale blockers, but claim lookup and retention need attention before broader use.

**Release choice.** Ship C02 markers, C04 proposal handling, C05, and C06 as one architecture if scoped re-extraction is a release promise. Otherwise defer the cluster and use a documented fresh-source/fresh-DB or append-only workflow. Hiding MCP tools does not disable this design.

### C13: embedding identity and atomic publication

**Problem addressed.** Existing non-null vectors could be reused after source text, context, provider, model, or dimensions changed. Partial writes and overlapping model spaces could corrupt retrieval.

**What the new design enables.**

- Cache reuse only when exact composed input and embedding space match.
- Validation of vector cardinality/dimensions and mixed-space/index conflicts.
- Atomic publication and serialization of same-index writes.
- Controlled whole-label refresh, including inactive records.

**Schema/operating cost.** Five properties on every embedded node; temporary `EmbeddingPublicationLock` nodes; a persistent uniqueness constraint/backing index; `SHOW CONSTRAINT` plus creation rights or admin precreation; provider cost when legacy vectors regenerate.

**Release choice.** Keep the whole design if safe cache reuse and concurrent publication are release promises. For a simple POC, explicit whole-label overwrite/refresh is a reasonable weaker contract. Do not remove only the lock or identity checks while retaining the same safety claims.

### C14-C16: lexical navigation and pageless documents

- `Element.order` and `Section.order` fix lexicographic/ID-dependent ordering and are useful without PageIndex.
- `Section.pageStart/pageEnd` are derived outline optimizations, primarily consumed by C17.
- `Document.sourceFormat` and `Element.sourceAnchor` support truthful pageless discovery/citations and belong with C16.
- Stored `Chunk.sourceFormat` and `Chunk.sourceAnchors` have writers but no production reader found; PageIndex reads Document/Element metadata instead. They are speculative duplication.
- Direct Document→Element membership was already used by PyMuPDF at baseline; C16 reuses it for pageless formats rather than introducing an entirely new pattern.

### C19-C21: ontology interchange

These changes reuse the pre-existing ontology topology and constraints. They add portable validated YAML/JSON interchange, file/DB-backed ontology retrieval context, and supported Python-schema export. They do **not** introduce a new ontology label/relationship architecture or deploy domain constraints. Their scope issue is feature surface, not database-schema expansion.

## Material corrections to Codex's report

1. **C12 fallback is catch-all on the first create attempt.** `mcp-neo4j-lexical-graph/src/mcp_neo4j_lexical_graph/server.py:136-153` catches every `Exception`, contrary to the report's unsupported-syntax-only claim.
2. **C12/C13 boundary is stronger than reported.** Vector definition compatibility checks live in C13; only the fulltext error fix is cleanly independent without extracting helpers.
3. **C16 does not depend on C17.** PageIndex consumes lexical metadata; lexical ingestion has no GraphRAG dependency.
4. **Direct Document→Element is not wholly new.** The endpoint pattern existed for PyMuPDF at baseline.
5. **Two Chunk fields are write-only in production.** No production reader was found for stored `Chunk.sourceFormat` or `Chunk.sourceAnchors`.
6. **Hiding tools requires source edits.** There are no configuration toggles for C17-C21; imports/registrations/lifespan are unconditional. Removing modules requires matching caller changes.
7. **`assign_section_hierarchy` is not merely an open historical question.** Active docs/code retain it while product records state an owner retirement decision. This needs an explicit owner resolution.

## Release blockers and readiness findings

### High

- **Not a coherent committed candidate.** The working-tree workflow references 60 test modules/scripts; all exist locally, but 33 are untracked at HEAD. A tracked-only commit would leave hard imports pointing at untracked runtime modules/resources.
- **Desktop smoke tests old code.** The DXT launches published proxy `0.2.1`; proxy source mounts ingest `0.1.0`, lexical `0.2.0`, and entity `0.4.0`. It does not exercise the modified source or new GraphRAG pin.
- **Version reuse.** Proxy, lexical, entity, and DXT versions remain unchanged despite substantial changes. Existing local wheels predate the new resources/tools. New behavior must not be published under already-used immutable versions.

### Medium-high

- CI omits `test_schema_ontology_export`, `test_docling_quality`, and `test_procedure_contract` despite those being real intended suites.
- `test_ci_release_gates.py` inspects workflow text; it does not prove all referenced files exist, all intended suites run, hosted CI passed, or packaged tools work.
- Report-validation contracts do not prove registration/execution in a packaged proxy.

### Medium / first-run UX

- Git is a setup prerequisite but is not listed with the initial Python/uv requirements.
- Docling is always installed even though PyMuPDF remains the default PDF parser.
- APOC is not checked before the optional paid model probe.
- DXT marks `openai_api_key` required despite documented non-OpenAI providers.
- Automatic long-lived Claude Code tool refresh remains unverified.

### Low / cleanup candidates

- `.claude/skills/dev/evaluate-pipeline/SKILL.md` still references `vlm_blocks` and `assign_section_hierarchy`.
- `TextOnlyParser` and legacy `text_only` branches appear to be dead routing surface; confirm whether any legacy compatibility requires them.
- `mcp-neo4j-proxy/manifest.json` appears to be an orphaned old duplicate manifest.
- Old root `test-prompt*.txt` files overlap newer maintained smoke/follow-up/benchmark prompts.
- Several cited live evidence files are gitignored, so clean-clone reviewers cannot inspect them.

## Approved release assembly

1. Preserve the full current state on a feature/experiment branch, including excluded C05/C06, C13, C17+C18, and the current C20 experiment.
2. Create a clean release-integration branch from the agreed published baseline, reconciling component-specific released tags. Port and understand stabilization fixes in small reviewed commits; do not begin by reverting intertwined code in the mixed tree.
3. Exclude C05/C06 and C13 as coherent architectures. Retain C02 compiler/null correctness, C03 honest outcomes/relationship ordering, C04 key normalization and a deliberately smaller property-preservation path, and C07 validation without excluded internal reservations.
4. Stabilize the base first, then review/correct/reimplement C15 (N1), C19+C21 (N4), and C16 in separate feature branches/PRs. Merge N1 before or jointly with C16 so cross-format hierarchy behavior is tested explicitly.
5. Discuss C20 with N4 before implementation. If approved, develop it in the separate GraphRAG repository against the agreed ontology contract.
6. In the separate GraphRAG repository, branch from its released baseline and publish a patch containing only approved C12 search/index fixes. Exclude PageIndex, refresh middleware, and ontology context from that patch. Consume the patch release without vendoring GraphRAG source.
7. Remove `assign_section_hierarchy` everywhere and correct the C12 catch-all fallback.
8. Commit a coherent candidate with every required runtime/test resource; align package versions, proxy pins, locks, wheels, and DXT.
9. Run the release gates below on the exact candidate and artifacts.

## Required test gates

### N1 — native hierarchy

- Real-PDF conversion through the actual MCP path, including clear and ambiguous heading fixtures.
- Semantic parentage and full heading paths through every affected chunker.
- Explicit expected behavior for false headings; no claim of exact author hierarchy.
- Regression coverage showing `assign_section_hierarchy` is absent from runtime schemas, skills, docs, and tests.
- Clean setup with the required Docling dependencies and packaged/Desktop execution.

### N4 — ontology interchange/export

- Normative JSON-schema validation plus semantic YAML/JSON roundtrips.
- Unsupported/lossy mappings reject with useful paths; collisions and failed imports roll back.
- Real MCP import → scoped extraction → export acceptance.
- Python-schema export tests included in CI, including exact `strip`/`strip_lower` identity behavior and unsupported validators.
- Fresh packaged-client/Desktop acceptance after loading the new entity server.

### C16 — document formats and interactions

- Real Markdown, TXT, local HTML/XHTML, and DOCX fixtures through the public MCP path, separately and as mixed folders.
- N1 semantic hierarchy, heading paths, chunking, citations, deletion, and rebuild behavior across every applicable format; document explicit format-specific limitations such as unstyled DOCX.
- Atomic publication, pageless behavior, null-page handling, source-anchor correctness, and no fabricated Page nodes.
- No production writer for speculative Chunk metadata without a reader; verify excluded fields are absent if removed.
- Packaged/Desktop execution and clean setup with all required parser dependencies.

### C20 — design gate before tests

- Joint N4/C20 decision covering the ontology contract, supported spec subset, source-of-truth, file-versus-DB precedence, reload behavior, and optional/unconfigured UX.
- If approved, implement and test in GraphRAG's own repository with real N4-produced artifacts and realized-versus-declared schema checks.

### Overall release

- Hosted CI green on the exact committed root revision and separate GraphRAG patch revision.
- All intended suites present, including previously omitted tests; no tracked-only/untracked split.
- Clean-clone setup and one live CSV+PDF end-to-end run on the final revision.
- Built wheels inspected for required resources and installed in an isolated environment.
- Rebuilt DXT installed through the real Desktop path; exact child package versions and new tools verified.
- No PageIndex, new-format, ontology-context, extraction run/claim, or embedding-lock surface exposed in the release.

C20 remains the only open feature-scope/design decision. The previous model default is retained unless the owner separately requests the `gpt-6-luna` change.
