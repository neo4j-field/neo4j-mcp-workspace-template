# Implementation report since the last released commit

Snapshot: **26 November 2026**. Purpose: owner review of release scope, physical
graph complexity and separability. This is an implementation inventory, not a
release approval. No code, database, credentials, generated MCP configuration or
running server was modified to prepare it. The only new files are this report and
its [file inventory](2026-11-26-implementation-inventory.json).

## 1. Baseline, scope and evidence rules

The primary baseline is **`9ed5a3be1ba946bf4f9f1a0adb26d99c78e6016f`**,
17 July 2026. Both entity-graph **0.4.1** and lexical-graph **0.2.1** were published
successfully from it; this was confirmed from publishing workflow history, not
inferred merely from tags. Root source HEAD is
**`5ab261337624a0c90f1de67af6f9c15ca2a29871`**, branch `stabilization`.
The delta includes committed checkpoints `20c54e8`, `5ab2613`, all subsequent
tracked working-tree edits and new untracked implementation/tests/docs.

There is no single version covering every delivery channel:

| Component/channel | Released baseline | Current source delivery |
|---|---|---|
| Entity | 0.4.1, `9ed5a3b` | Same version string, substantially changed source; not a newly published package |
| Lexical | 0.2.1, `9ed5a3b` | Same version string, substantially changed source; not a newly published package |
| Ingest | 0.1.1, `51476ff` | Changes audited primarily against the common `9ed5a3b` snapshot; ingest-specific post-0.1.1 changes included |
| Proxy | 0.2.1, `c76ae8a` | Source validator and immutable GraphRAG pin added; package release pending |
| Desktop | Published workspace 0.2.1 | Existing published proxy resolves older child packages; source manifest edits do not rebuild the shipped artifact |
| GraphRAG, separate Git repository | Local release tag `v0.4.2`, commit `19ed03d` (tag/source baseline; package publication not re-audited here) | `0867f08b8eba58c328e4699b1323fa9661aa6b10`, branch `codex/graphrag-tree-ontology`, [draft PR #2](https://github.com/neo4j-field/mcp-neo4j-graphrag/pull/2) |

The manifest inventories **252 changed/new/deleted root files** and **26 GraphRAG
files**, with current file hashes. It excludes credentials, environments, generated
client configuration, ignored customer documents and outputs. Generated synthetic
data, saved live reports and the legal-run generated schema are discussed as
evidence/artifacts, not silently counted as product implementation. The manifest
also excludes itself and this report to avoid recursive hashing.

Tests below were inspected, together with saved execution evidence. They were
**not rerun for this report**. Historic counts refer to their recorded source
snapshots and overlap: do not add them into a purported final-release test total.
Mocked-provider tests establish control flow/data integrity, not model accuracy.
Local tests, real-provider runs, hosted CI and manual-client acceptance are
identified separately.

Categories are retrospective assessments: **stabilization** repairs existing
behavior; **UX** improves setup/discoverability/understanding; **capability** adds a
user workflow; **architecture** adds persistence, identity or publication machinery.
Several changes span categories even if originally tracked as bugs.

## 2. Coherent implementation changes

### C01 — Executable workflow/report contracts and Desktop instruction repair

- **What/files:** `mcp-neo4j-proxy/src/mcp_neo4j_proxy/report_validator.py`,
  `report_contracts.yaml`, proxy `server.py`, `__init__.py`, `pyproject.toml`;
  `.agents/skills/develop-neo4j-graph/`, Desktop skill and `docs/CLAUDE_DESKTOP.md`.
  Adds CLI `neo4j-validate-report` and proxy `validate_workflow_report`.
- **Intent/category:** stabilization + UX. Completion previously depended on
  narrative claims; Desktop examples disagreed with real argument/property names.
- **Before → after:** agents could omit questions/required sections and inspect
  `embedding` instead of `text_embedding`; now reports require the expected number
  of records/fields, and maintained examples use runtime-compatible calls.
- **Database/necessity:** **none**. Existing ontology examples now consistently
  use `CONTAINS`; this corrects documentation, not a new ontology topology.
- **Dependencies:** proxy library import is lazy so validation does not start MCP
  children. Report/skill/contract changes should ship together; independent of
  ownership, PageIndex and ontology interchange.
- **Tests:** `tests/report_validation/test_report_validator.py`, workflow and
  Desktop runtime-schema contracts; ontology workflow and headless Desktop smoke
  integrations verify calls against actual tools and executable ontology fixtures.
  Validation checks structure, not execution truth or factual answer correctness.
- **Docs/setup:** mandatory validation step; document flags apply to all document
  formats despite legacy name `--pdf-data-present`; CLI exit meanings documented.
- **Compatibility:** existing incomplete/nonconforming reports now fail. No data
  migration. Desktop runtime source and published package are still distinct.
- **Smallest ship/disable/revert:** ship validator + schema + examples as one slice;
  omit the final validation requirement/tool to disable enforcement, without DB work.
- **Open:** exact heading and bullet-count rules are brittle; no complete
  per-question retrieval trace enforcement. Recent proposed fixes are not implemented.
  `report_contracts.yaml` also contains a future `graph_quality_report` definition;
  the active validator accepts chatbot/analytical reports only. Its presence does
  not implement the deferred quality-improvement workflow.

### C02 — Owned CSV query compilation and null handling

- **What/files:** ingest `query_compiler.py`, `csv_records.py`, `server.py`,
  `__init__.py`, README and structured-data skill reference. Adds
  `compile_node_ingest_query` and `compile_relationship_ingest_query`.
- **Intent/category:** stabilization, with a small new tool surface. Upstream
  modeling drafts ignored source column mappings and could assign relationship
  properties to endpoint nodes; pandas missing values could become invalid `NaN`.
- **Before → after:** generated drafts could write the wrong shape; now identifiers,
  types, columns and endpoint mappings are checked, relationships are bound, and
  missing CSV values become native null parameters.
- **Database/necessity:** no fixed domain labels/types/indexes. Generated nodes and
  edges additionally receive `__structuredSource: BOOLEAN` and
  `__structuredProperties: LIST<STRING>` for C06's deletion protection. These are
  architectural ownership metadata, not necessary for the compiler/null fixes alone.
- **Dependencies:** compiler correctness and null conversion stand alone; emitting
  ownership metadata is coupled to C06. Arbitrary Cypher ingestion remains available.
- **Tests:** compiler unit tests verify mappings, conversions, safe names and
  correct assignment targets; null tests verify pandas sentinel conversion; actual
  structured-ingest integration verifies idempotent nodes/edges and no misplaced
  endpoint properties. Ownership tests cover CSV before/after extraction.
- **Docs/setup:** skills require local compilation before ingestion; package import
  is made safe for library-only compiler use.
- **Compatibility:** stricter model identifiers/types reject formerly accepted
  unsafe drafts. Normal CSV APIs remain. Existing rows are not automatically marked.
- **Smallest:** ship compiler + null fix without ownership SET clauses if C06 is
  removed too; otherwise retain markers. Hide compiler tools only if skills stop
  depending on them. Reverting code does not remove persisted metadata.
- **Open:** still reads entire CSV via pandas; no streaming/declarative-only writer.

### C03 — Honest extraction outcomes and relationship persistence

- **What/files:** entity `models.py`, `base_extractor.py`, `text_extractor.py`,
  `vlm_extractor.py`, `job_manager.py`, `server.py`.
- **Intent/category:** stabilization. Invalid/blank/retry-exhausted model responses
  looked like legitimate empty success; edges could be attempted before endpoints
  from later batches existed.
- **Before → after:** success-shaped omissions become explicit `success`, `empty`,
  `failed` outcomes, bounded retries, attempted/persisted/failed coverage and error
  details; entities are available before edge publication, with missing endpoint
  mismatches surfaced. Final C06 behavior publishes no partial replacement on failure.
- **Database/necessity:** domain relationships and existing `EXTRACTED_FROM` become
  reliably written; no fixed new label/type is required for these fixes themselves.
  Durable status schema belongs to C05, claim schema to C06.
- **Dependencies:** tightly shares parser/status/publisher with C05–C07; extracting
  a smaller fix requires preserving explicit failure outcomes through those paths.
- **Tests:** entity coverage and relationship-persistence unit/integration suites
  exercise text/Page routing, valid empty, invalid/truncated content, exhausted
  retries, later-batch endpoints, restart/force selection and failed persistence.
- **Docs/setup:** status counters, failure inspection and polling instructions updated.
- **Compatibility:** jobs previously called complete may now fail; status fields
  added. No source-data migration; failure semantics deliberately change.
- **Smallest:** retain outcomes + endpoint ordering/count checks. Do not revert only
  status assertions while leaving failed sources silently empty.
- **Open:** API completion is not semantic accuracy. Creation counters can count
  touched entities per batch, not distinct new nodes across the entire job.

### C04 — Bridge normalization and conservative property conflicts

- **What/files:** entity `schema_generator.py`, `server.py`, later `ownership.py`;
  schema/bridge tests and shared skill.
- **Intent/category:** stabilization + UX. Strip-only generated keys failed merges
  onto lowercase CSV keys; extraction silently overwrote authoritative CSV values.
- **Before → after:** per-label `key_normalization` explicitly chooses `strip` or
  `strip_lower` for both entities and endpoints. `property_policy` defaults to
  `preserve_existing`; missing values can be filled, non-null values retained.
  `overwrite` remains explicit. Force controls selection, not precedence.
- **Database/necessity:** adds `proposedPropertiesJson` (scalar JSON string),
  `conflictingProperties` (string list), `propertyPolicy` to provenance; final edge
  conflicts live on C06 claims. Enables inspection of rejected proposals without
  overwriting customer facts. No fixed constraints/indexes.
- **Dependencies:** key policy can ship separately. Conflict preservation is now
  implemented inside the ownership writer; separating it needs a smaller writer.
- **Tests:** bridge-normalization and property-policy suites verify matching entity/
  endpoint identity, case-sensitive preservation, invalid policy rejection,
  missing-value fill, overwrite, CSV-before/after behavior and retained conflicts.
  Owner's golden CSV/PDF repeat passed actual configured extraction.
- **Docs/setup:** confirmed key policy is reused; no unconditional lowercasing.
- **Compatibility:** default extraction precedence changes; existing extracted
  non-null values are also preserved. No automatic canonicalization/migration.
- **Smallest:** keep normalization and preserve/proposal recording even if C06 is
  deferred. Never simply remove preservation while keeping current docs.
- **Open:** policies do not resolve aliases or determine which factual proposal is true.

### C05 — Durable extraction completion and exact retry identity

- **What/files:** new entity `extraction_identity.py`; loader, server/status changes.
- **Intent/category:** stabilization implemented through architecture. Any incoming
  provenance used to mean “done,” skipping partial results and reprocessing empty ones.
- **Before → after:** successful completion, including valid empty, survives restart
  and is reused only for matching source/schema/model/config identity. Schema loading
  compiles current bytes, avoiding stale timestamp/size bytecode after rapid edits.
- **Database/necessity:** **new `EntityExtractionRun` and `PROCESSED_SOURCE`**; fields
  in schema ledger S1. Enables a specific query: which active source has a complete,
  non-invalidated result for this extraction fingerprint? No new DDL indexes or
  constraints were added for these records.
- **Dependencies:** fingerprints include policy/scope/implementation/dependencies;
  current completion is committed by C06's atomic publisher. Records can be designed
  separately, but cannot be removed without changing selection and publication.
- **Tests:** `test_extraction_identity`, completion integration and coverage restart
  cases verify changed text/schema/model/policy, empty reuse, missing completion,
  invalidation, missing endpoints and same-size schema edits. Mostly mocked providers.
- **Docs/setup:** fingerprint/status/legacy behavior documented in entity README and
  `EXTRACTION_INTERNALS.md`.
- **Compatibility:** old provenance is not a reusable completion record; force is
  not an ownership migration. C06 may refuse replacement on legacy contributions.
- **Smallest:** could disable cache skipping and always extract, but must redesign
  completion/ownership interaction; hiding a tool does not disable internal selection.
- **Open:** no historical failed-job ledger, retention policy or full workflow resume;
  payloads are read before hashing, and broad implementation hashes cause extra reruns.

### C06 — Source-scoped contribution ownership and atomic replacement

- **What/files:** new entity `ownership.py`; major `server.py` publication rewrite;
  C02 ownership emission, reserved-name validation and internal workflow reference.
- **Intent/category:** **architecture plus stabilization**, not merely a small merge
  fix. Re-extraction left removed properties/labels/edges and risked deleting shared
  CSV/user data if cleanup were based only on provenance.
- **Before → after:** additive writes become staged, scope/source-specific replacement
  in one transaction. Removed/empty contributions withdraw supported assertions;
  other scopes/sources, structured ownership and external edits are preserved.
  Source mutation/failure/cancellation before commit preserves previous domain output.
- **Database/necessity:** **new `EntityExtractionClaim` and `CLAIM_SOURCE`**, scoped
  provenance, JSON ownership state, string-list structured ownership, lock counters
  on domain/source objects; full S2 ledger below. Enables withdrawing one source's
  relationship/property claims while retaining other support. This machinery is
  necessary for the chosen granular replacement semantics, not for a one-shot POC.
- **Dependencies:** inseparable current cluster with C02 markers, C04 policy,
  C05 identity and C07 validation. Publisher order, completion and conservative
  cleanup must remain coherent. No new uniqueness constraints protect claim/run MERGEs.
- **Tests:** owned-replacement integration exercises removed schema output, shared
  support, different scopes, CSV before/after, external edits, empty output, null
  withdrawal, rollback, cancellation, legacy refusal, source mutation and duplicate
  partial records. These are state-transition checks, not extraction-quality tests.
- **Docs/setup:** stable `extraction_scope`, explicit `source_ids`, rebuild recipe,
  legacy refusal and Internals page added; domain schema reserves internal names.
- **Compatibility:** scope defaults include schema path/ontology; moving a schema
  can create a new scope. Legacy ownership is never inferred; use fresh isolated
  sources/DB or reviewed migration. No automatic migration supplied.
- **Smallest:** ship as one coherent ownership slice, or replace with an explicitly
  simpler append-only/fresh-DB workflow. Neither `preserve_existing` nor hiding a
  tool disables it. Reverting requires matching publisher/selection/compiler
  changes; stripping existing metadata first would destroy cleanup guarantees.
- **Open:** full results in memory and one publication transaction; serialize
  overlapping jobs. No global concurrency/retention framework. Source deletion can
  leave claim/run cleanup work; element-ID claim references complicate export/rebuild.

### C07 — Static extraction-schema validation and typed endpoints

- **What/files:** new entity `schema_validation.py`; generator, model parser,
  ontology loader and server preflight changes.
- **Intent/category:** stabilization. Unsupported annotations were guessed as strings;
  endpoint keys were stringified; required relationship properties could be mistaken
  for endpoints; invalid schemas reached provider/database work.
- **Before → after:** validates scalar contracts, required keys, endpoint identity/
  types, output completeness, reserved names and duplicate declarations; generated
  bindings remove field-order dependence; integer zero/boolean false remain native.
- **Database/necessity:** no new schema or constraints. Changes values and prevents
  malformed writes. “Key validation” does **not** create/check domain Neo4j uniqueness.
- **Dependencies:** shared boundary used by conversion, file extraction, C19 and C21;
  reserve C06/C13 internal names consistently across CSV/extraction.
- **Tests:** schema-preflight unit and real-DB integration cover invalid schemas
  before work, required/reordered fields, numeric/bool keys, Literal compatibility,
  quoting, duplicate declarations, enums and bad validator return types.
- **Docs/setup:** four extraction scalar types and temporal-as-explicit-string guidance.
- **Compatibility:** formerly tolerated arrays/maps/dates/arbitrary fallback types now
  reject. Custom schemas need explicit supported representations. Trusted Python still
  executes; AST checks are not a sandbox or proof of custom validator correctness.
- **Smallest:** ship the shared module with all callers; cannot delete it while
  retaining the converter/import/export paths. DDL introspection is not required.
- **Open:** numeric/legal coercion semantics are not proven; the legal-run custom
  validators demonstrate this boundary. Concurrent domain uniqueness remains separate.

### C08 — Explicit chunk rebuilds and page-accounting correction

- **What/files:** lexical `server.py`, `graph_reader.py`, `job_manager.py`,
  docs/tools-chunking/version/verification and skill references.
- **Intent/category:** stabilization + UX. Explicit rebuilds skipped already-chunked
  documents; PDF page count was confused with materialized `Page` count.
- **Before → after:** all-document explicit clear/rebuild selects eligible active
  existing chunks; default runs still skip already processed documents. Inventory/
  progress distinguish source pages from page nodes (`sourcePageCount`,
  `pageNodeCount`, `sourcePagesExpected/Processed`).
- **Database/necessity:** no new label/type/property required. `Document.totalPages`,
  chunk-set versions and active flags already existed; response renaming is not a
  new persisted schema.
- **Dependencies:** count checks and workflow examples updated together; pageless
  formats C16 extend counts to zero physical pages without invented pagination.
- **Tests:** chunk-rebuild and page-accounting unit/live suites verify explicit vs
  default selection, scoped rebuild, graph versions and PyMuPDF 2/0 versus
  Docling/page-image 2/2 accounting; real PyMuPDF fixture included.
- **Docs/setup:** replaces ambiguous response names in examples and runtime contracts.
- **Compatibility:** breaking response-field rename/removal; consumers must change
  `pages/pageCount/total_pages*` expectations. Existing graphs remain readable.
- **Smallest:** page response rename and rebuild selection can ship independently
  with their own examples/tests. Reverting rename needs matching contract changes.
- **Open:** rechunking is not a complete domain-claim migration; avoid assuming a
  new chunk set automatically retires every prior entity contribution.

### C09 — Docling completion validation and model-call compatibility

- **What/files:** lexical parser `conversion_validation.py`, `docling_parser.py`;
  entity `build_llm_params` in `base_extractor.py`; description generator/server
  default references, `.env.example`, setup and source Desktop manifest defaults.
- **Intent/category:** stabilization for incomplete conversions/model parameters;
  UX/configuration for changing the default extraction model to `gpt-6-luna`.
- **Before → after:** native conversion must report success with an empty errors
  list before adaptation/publication; partial/failed statuses are rejected.
  This is a status/error gate, not an independent page-by-page completeness oracle.
  Configured model identifiers are
  retained; GPT-family request parameter construction handles reasoning settings.
- **Database/necessity:** no new schema; prevents partial parse publication and
  changes configured `model` metadata values on later extractions.
- **Dependencies:** converter validator consumed by native parsing C15/C16; model
  builder reused by C23's preflight. Default changes are separable from parsing fixes.
- **Tests:** conversion-completion tests exercise native failure/partial statuses;
  `test_gpt6_extraction_params` inspects actual request kwargs for provider forms.
  Real configured model requests passed in saved smoke/benchmark/preflight evidence.
- **Docs/setup:** exact configured model must not be silently substituted; source
  defaults differ from older published artifacts.
- **Compatibility:** incomplete documents now fail; existing `.env` is not migrated.
  New default requires the user's provider/account to support that identifier.
- **Smallest:** keep completion validation; choose default model independently.
  No new provider registry or migration framework is necessary.
- **Open:** parameter tests are not general provider/vision compatibility guarantees.

### C10 — Atomic lexical document/version publication

- **What/files:** lexical `graph_writer.py`, `server.py`, `_TransactionDriver`/
  session adapter, `write_document_atomically`, `activate_document_version`.
- **Intent/category:** stabilization implemented with a transactional refactor.
  Deactivating old versions before independently committed batches exposed partial
  replacements and could leave no usable active document.
- **Before → after:** one document's parsed graph and active-version switch commit
  together; rollback preserves the old graph. Manual document/chunk-set activation
  validates the requested set before changing either selection.
- **Database/necessity:** no new labels/types/properties. Reuses existing active/
  version fields. Existing lexical ID uniqueness constraints are now also ensured
  for PyMuPDF paths, and deferred DDL errors are consumed before data transactions.
- **Dependencies:** wraps all supported writers, including C16. DDL must remain
  outside data transaction; same-version retry assumes uniqueness enforcement.
- **Tests:** publication unit tests cover ordering, commit/DDL errors and invalid
  activation; isolated DB tests cover reader visibility, later-batch failure,
  cancellation, successful switch, concurrent same-version writers and PyMuPDF rollback.
- **Docs/setup:** transaction boundary explicitly documented; no workflow ledger added.
- **Compatibility:** failed ingestion no longer leaves partial replacement records;
  schema permissions may be exercised earlier. No data migration.
- **Smallest:** retain as one writer/activation slice. Reverting only the wrapper
  restores partial writes. Can ship without ownership/embedding architecture.
- **Open:** one parsed document per transaction; chunking, embeddings and extraction
  are later transactions, not one atomic multi-tool pipeline. Large-doc memory limits remain.

### C11 — Exact lexical deletion and protected metadata

- **What/files:** lexical `graph_reader.py`, new `metadata.py`, server/worker/parser
  boundary calls and graph writer.
- **Intent/category:** stabilization. Prefix-derived deletion could remove unrelated
  elements; user metadata could overwrite reserved identity/lifecycle properties.
- **Before → after:** deletion follows exact lexical ownership, retaining shared
  descendants and domain nodes; reserved keys and normalized-name collisions reject
  before work, while ordinary metadata survives.
- **Database/necessity:** no new schema. Uses existing ownership relationships;
  reserved names include the other changes' lifecycle/embedding fields.
- **Dependencies:** must recognize pageless Document→Element membership C16 and
  current field names. Independent of introducing C06 claims, but deletion does not
  fully reconcile them.
- **Tests:** lexical-write-boundary unit/integration suites cover prefix neighbors,
  arbitrary owned IDs, shared children, domain preservation, repeat delete, all
  parser paths, reserved fields, normalized collisions and early rejection.
- **Docs/setup:** deletion and metadata guarantees documented in lexical guides.
- **Compatibility:** metadata accepted before may now fail if it collides; no graph
  migration. Existing explicit deletion still detaches incoming provenance edges.
- **Smallest:** ship exact deletion and metadata validator as separate bug-fix
  slices if all call sites remain coherent; no configuration toggle needed.
- **Open:** deletion is not C06 contribution withdrawal; orphan claims/runs and
  domain facts surviving source removal need an explicit lifecycle decision.

### C12 — Vector/fulltext index creation, fallback and readiness

- **What/files:** lexical `_ensure_vector_index`, `_ensure_fulltext_index` in
  `server.py`; GraphRAG `search_indexes.py` and ranked search paths; docs/tools-embedding.
- **Intent/category:** stabilization + compatibility. Unsupported vector prefilters
  blocked otherwise usable indexes; lazy DDL/fulltext errors could be hidden behind
  successful embedding responses.
- **Before → after:** supported prefilter DDL used where available, otherwise narrow
  unsupported-syntax fallback to plain vector index; named definitions/states checked.
  Fulltext failures surface even on vector-cache hits. Retrieval refuses non-ONLINE
  indexes before embedding; version-aware SEARCH/procedure selection is explicit.
- **Database/necessity:** existing `<label>_text_embedding` and `<label>_text_fulltext`
  indexes are verified/repaired, not novel graph concepts. Vector optional prefilter
  fields commonly `documentName,type`; cosine/dimensions retained. Fulltext uses
  selected text/fallback properties; no analyzer/rank-fusion redesign.
- **Dependencies:** repair runs in C13 cache-hit path; modern retrieval syntax is
  delivered by separate GraphRAG pin C22. Core fulltext error fix is separable.
- **Tests:** vector fallback unit/native 2025.12 integration, fulltext failure unit/
  public MCP integration, GraphRAG search unit/5.26 and 2026.09 integrations verify
  incompatible definitions, pre-provider errors, repair, supported filter/version
  choices and actual ranked retrieval. No inference that all embedding APIs support 5.26.
- **Docs/setup:** index states, explicit migration and post-filter limitations documented.
- **Compatibility:** wrong named indexes now fail instead of silently proceeding;
  production code never auto-drops them. Operator must resolve incompatible schema.
- **Smallest:** ship index helpers/search changes without C13's cache architecture
  after adapting callers; retain unsupported-only fallback, not catch-all retry.
- **Open:** post-filtering can return fewer hits; no scoped fulltext filter argument
  or hybrid ranking was added. POPULATING is not readiness.

### C13 — Exact embedding identity and atomic space publication

- **What/files:** lexical new `embedding_identity.py`, embedder/server changes.
- **Intent/category:** stabilization through **architecture**. Existing non-null
  vectors were reused despite changed source, context, provider/model or dimensions;
  partial/model-space writes could corrupt shared indexes.
- **Before → after:** exact composed input and embedding-space identity govern cache
  reuse; all needed outputs validated and published atomically. Scoped mixed-space
  migrations and overlapping same-property indexes reject; explicit `dimensions`
  and `include_inactive` support controlled whole-label refresh.
- **Database/necessity:** S3 ledger: five scalar cache fields on embedded nodes,
  temporary `EmbeddingPublicationLock`, uniqueness constraint and backing index.
  Enables safe cache-skip decisions and serialization of same-index publication.
  Temporary nodes do not remain after successful calls; the DDL does.
- **Dependencies:** C12 index validation and creation; internal label reservation
  shared by CSV and extraction validation. Independent of entity run/claim ledger.
- **Tests:** identity/vector tests cover exact fallback/context, model/dimensions,
  legacy regeneration, bad provider vectors/cardinality, source mutation, cache/index
  repair, inactive scope, overlapping indexes and concurrent publications. Restricted
  user integration covers missing privileges and admin-precreated constraints.
- **Docs/setup:** whole-label migration/privilege instructions and cache semantics;
  actual restricted-user tests passed. No claim that CREATE CONSTRAINT is universally
  unavailable on a named hosting tier: tested privileges, not a blanket platform rule.
- **Compatibility:** legacy vectors lack identity and regenerate, potentially costing
  provider calls. New publication requires SHOW CONSTRAINT and either creation rights
  or a matching precreated constraint. Dimension changes need explicit index work.
- **Smallest:** can replace with simpler explicit whole-label overwrite semantics,
  but not safely disable individual checks while retaining identity cache promises.
  Reverting writer requires reviewing stored vectors/indexes, not deleting business nodes.
- **Open:** memory/transaction bounds; opaque remote alias retargets; broad endpoint
  environment hashing can over-invalidate; schema/empty-index side effects can remain
  after later provider failure. No persistent run history.

### C14 — Lexical navigation metadata

- **What/files:** lexical `graph_writer.py`, `graph_reader.py`; GraphRAG readers.
- **Intent/category:** new retrieval support + stabilization of ordering.
- **Before → after:** numeric page/element/section ordering replaces accidental
  lexicographic ID ordering; new parses provide efficient outline order/page ranges.
- **Database/necessity:** **new `Element.order`, `Section.order`, `Section.pageStart`,
  `Section.pageEnd`**. No new label/type. Ranges include descendants and are zero-based;
  GraphRAG presents physical citation conventions explicitly. Enables outline reads
  without scanning every section's content; order supports opaque/non-numeric IDs.
- **Dependencies:** optimized PageIndex C17 consumes it; native hierarchy C15 supplies
  meaningful parentage. Legacy retrieval has null/fallback handling.
- **Tests:** navigation metadata integration verifies opaque IDs and page ordering
  across 0/9/10, descendant-inclusive ranges and legacy reads.
- **Docs/setup:** new-parse/legacy behavior explained in GraphRAG delivery review.
- **Compatibility:** additive; no required migration. Existing graphs lack ranges.
- **Smallest:** ordering and range materialization can be separated; compute ranges
  at read time to remove stored ranges at a query cost. Keeping PageIndex does not
  intrinsically require all these properties to be materialized.
- **Open:** no dedicated navigation index added; changed hierarchy must keep derived
  metadata coherent. This is a performance/readability tradeoff for GRAPH-001 review.

### C15 — Native Docling heading hierarchy (N1)

- **What/files:** lexical Docling dependency/lock, parser, all heading-aware
  chunkers/base and hierarchy postprocessor; DOCLING_MODE reference.
- **Intent/category:** new capability + parser stabilization. Semantic heading
  depth was confused with reading-order tree depth, causing flat/wrong paths.
- **Before → after:** Docling 2.152 native hierarchy is retained in Section
  parentage and full chunk heading paths; no default extra LLM hierarchy pass.
  Visual captions and merged contributing section paths are preserved.
- **Database/necessity:** reuses **existing** `Section`, `HAS_SECTION`,
  `HAS_SUBSECTION`, `NEXT_SECTION`, `Section.level`, `Chunk.sectionContext`.
  No new graph vocabulary. C14 adds optional navigation metadata separately.
- **Dependencies:** newer Docling/core; C16 uses the same installed declarative
  ecosystem. Updated chunkers must agree with parser levels.
- **Tests:** native-hierarchy unit/integration verifies semantic parentage/paths
  through writer and chunkers; real PDF smoke and manual PageIndex checks establish
  actual conversion. Controlled Docling-quality variants isolate layout ambiguity.
- **Docs/setup:** native path is default; `assign_section_hierarchy` remains explicit
  correction. Setup installs Docling, while package metadata still calls it an extra.
- **Compatibility:** newly parsed paths/chunks can differ; existing graphs unchanged.
  To change old hierarchy, explicitly reparse/correct and refresh derived embeddings.
- **Smallest:** ship native hierarchy without PageIndex/ontology. Disable section
  extraction or use another PDF mode if unwanted. Do not downgrade only the lock
  while retaining APIs requiring the new version.
- **Open:** Docling interprets bold labels/contents as headings. Controlled clear
  variant was exact; ambiguous variants added headings. Correction changes levels/
  parents, not false-heading classification. Exact author hierarchy is not guaranteed.

### C16 — Markdown, TXT, local HTML/XHTML and DOCX

- **What/files:** lexical `input_formats.py`, `structured_document.py`, models,
  server/worker/reader/writer and all four chunkers; `DOCUMENT_MODE.md`, fixtures.
- **Intent/category:** **new capability**. Workspace previously accepted PDFs only.
- **Before → after:** supported suffixes route automatically to native `document`
  mode; mixed folders work. TXT stays literal; native headings/lists/tables/images
  are retained where available. Resource fetching/scripts are disabled.
- **Database/necessity:** S4 ledger: `Document.sourceFormat`, `Element.sourceAnchor`,
  chunk `sourceFormat/sourceAnchors` and direct Document→Element `HAS_ELEMENT`
  membership when no physical pages exist. Existing page fields become nullable.
  No fabricated Page nodes or new relationship type. Enables truthful pageless
  citations and graph/chunk/retrieval reuse.
- **Dependencies:** Docling extra/declarative backends, C10 atomic writer, C14 order,
  C17 pageless citation extension and deletion's direct-membership handling C11.
- **Tests:** actual lightweight parser tests, routing/remapping, all four chunkers,
  public spawned-worker mixed-format tests; 31 actual-provider acceptance checks
  verify CSV merges/conflicts, embeddings, vector/fulltext and source citations.
- **Docs/setup:** new data/documents structure, routing/encoding limits and format
  table. Non-PDF source IDs include extension to avoid same-stem collisions.
- **Compatibility:** PDF defaults retained; pageless clients must handle null pages.
  UTF-8 required for text formats; no remote HTML rendering or DOCX pagination.
- **Smallest:** individual suffixes can be removed from routing with corresponding
  docs/tests; parser/locator support should stay coherent. Hiding a format does not
  require deleting graphs already created from it.
- **Open:** unstyled DOCX has no inferred outline. Specifying PDF Docling mode does
  not change DOCX routing. Source anchors locate parser elements, not visual pages.

### C17 — Agent-driven document-tree retrieval tools

- **What/files:** separate GraphRAG `pageindex.py`, `server.py`, package/docs/tests;
  lexical support C14/C16.
- **Intent/category:** **new capability** requested for PageIndex-style retrieval.
- **Before → after:** agents can call `list_retrieval_documents`,
  `get_document_outline`, `get_section_content`, `get_document_content`, follow
  bounded continuation and cite original sections/elements. Flat and visual-page
  fallbacks remain; no embedded autonomous PageIndex reasoning model is added.
- **Database/necessity:** **no new label, relationship, constraint or index**.
  Reads existing lexical topology plus C14/C16 optional metadata. Does not create
  section summaries, cross-document edges or document-wide semantic hubs.
- **Dependencies:** separate GraphRAG source delivery C22, active topology and
  useful section hierarchy; flat document content remains usable without sections.
- **Tests:** GraphRAG unit/live integration verify active versions, outlines,
  descendants, pagination within long elements, bounds, citations and fallbacks.
  Manual Claude MD/PDF retrieval/pagination passed; no claim of general retrieval recall.
- **Docs/setup:** tools/method table and source-anchor guidance; shared source pin.
- **Compatibility:** additive read-only APIs; legacy range gaps are null. Fixed
  traversal/pagination limits mean exhaustive traversal must honor continuations.
- **Smallest:** omit registration of four tools and their docs; retain lexical
  hierarchy for chunking. Removing C14 materialized ranges alone is another option.
- **Open:** no summaries, hybrid rank fusion or benchmark comparing retrieval methods;
  client refresh initially failed, addressed at server level by C18.

### C18 — Conditional tool visibility and asynchronous refresh

- **What/files:** GraphRAG `_PageIndexDiscovery` middleware, server lifespan,
  `test_pageindex_refresh.py`, `test_pageindex_refresh_mcp.py`.
- **Intent/category:** UX + capability gating. Unsupported tools should be invisible;
  external lexical ingestion otherwise left a long-lived agent's catalog stale.
- **Before → after:** usable active topology determines tool visibility on list/call;
  a lifespan-owned observer sends `tools/list_changed` after external additions or
  deletion. One two-second probe is shared by subscribed sessions; transient probe
  failure retains advertised state and retry, without terminating the server.
- **Database/necessity:** **none**. No registry or capability node. Reads actual
  topology, not just existence of a Section label.
- **Dependencies:** C17 registrations and FastMCP session notification/lifespan API;
  C22 pin must deliver the fix. Not dependent on ontology storage.
- **Tests:** two-client notification, no-change silence, disconnected/failed
  transport isolation and probe recovery; public MCP live external-write test
  verifies hidden→visible→hidden with no intervening GraphRAG call.
- **Docs/setup:** one-time reload loads new code; subsequent ingestion should not
  need reconnect in clients honoring notifications.
- **Compatibility:** client support is required. Latest GraphRAG 33 unit tests +
  four subtests and hosted 5.26/2026.09 integrations passed at `0867f08`.
- **Smallest:** C17 can work with list/call gating only and documented manual
  refresh; removing observer restores that UX limitation. Do not claim auto-refresh
  if notification handling is disabled.
- **Open:** Claude Code's long-lived notification acceptance remains pending.
  Observer adds periodic read load; multiple proxy mounts have separate instances.

### C19 — Ontology Graph Spec import/export (N4)

- **What/files:** entity `ontology_spec.py`, bundled normative 1.1.0 JSON schema,
  server tools, schema loader/generator, dependencies (`jsonschema`, `PyYAML`).
- **Intent/category:** **new capability**. Existing ontology-as-graph compilation
  lacked portable validated YAML/JSON interchange.
- **Before → after:** `import_ontology_spec(content)` validates supported semantics
  before atomic creation; `export_ontology_spec(name,format)` roundtrips supported
  ontology data. Unsupported/lossy mappings reject with paths.
- **Database/necessity:** reuses pre-release Ontology/NodeType/RelationshipType/
  PropertyDef/AliasMap/Blocklist graph. Spec version/display name and supported
  property/normalizer data are materialized in that graph (S5). **No new ontology
  label/type/DDL vocabulary**, no automatic deployment of domain constraints.
- **Dependencies:** existing setup/load/generate path, C07 validation and normalizer
  registry. Current file-based ontology extraction still imports to an ontology DB
  target before `ontology_name` extraction; this is not direct file extraction.
- **Tests:** normative validation, YAML/JSON semantic roundtrip, generated validators,
  unsupported cases, name collisions and transaction rollback; manual Claude import,
  scoped extraction and export passed. Definition roundtrip alone does not establish
  runtime alias/blocklist performance or complete standard support.
- **Docs/setup:** bounded support vs full normative spec distinguished; bundled
  schema verified in wheel; import creates new names and refuses collisions.
- **Compatibility:** existing ontology schema is retained; globally unique type/
  alias/blocklist names limit multiple overlapping ontologies. No auto replacement.
- **Smallest:** hide import/export tools while retaining existing ontology extraction;
  remove package dependencies/schema only when C21 no longer needs them. A proposed
  single-spec-node backend is not part of this implementation.
- **Open:** full standard semantics exceed extraction's four scalar/single-key/fixed-
  endpoint subset. Current DB materialization is exactly the complexity to review.

### C20 — Ontology retrieval context

- **What/files:** separate GraphRAG `ontology.py`, bundled schema, CLI/server options,
  utils/tests; `.env.example` optional ontology settings.
- **Intent/category:** **new capability**, inspired by the supplied text-to-Cypher agent.
- **Before → after:** `get_ontology` returns semantic context from a configured spec
  file or existing template ontology DB, with selection/bounds; physical schema tools
  remain necessary for realized values/indexes.
- **Database/necessity:** **none added by this tool**. File mode reads no ontology
  metadata graph; DB mode reads existing S5 topology. Full retrieval-context semantics
  are broader than extraction adapter support.
- **Dependencies:** optional configuration and spec schema; no entity Python import.
  C22 delivers it; C19 may populate its DB source but is not needed for a file.
- **Tests:** real reference movie ontology, semantic alias resolution, bounded
  context/endpoint closure and declared-vs-realized distinction; manual file-backed
  context + read-only domain Cypher passed.
- **Docs/setup:** configured `ONTOLOGY_FILE` takes precedence; credentials can reuse
  the existing DBMS. No requirement to create a new DB for ordinary file context.
- **Compatibility:** additive; missing configuration currently returns an error,
  not a clean optional-status object. File content rereads per call, but selected
  path is captured at process startup.
- **Smallest:** omit tool registration, or use file mode only and leave old ontology
  DB unused. Replacing physical schema discovery wholesale would be incorrect.
- **Open:** changing the configured path needs process reload. Runtime registration,
  scalar spec-node storage and future native db.ontology procedures are proposals,
  not implemented. These do not cause PageIndex visibility behavior.

### C21 — Direct supported Python-schema → ontology export

- **What/files:** entity `schema_ontology_export.py`, additive server tool
  `export_extraction_schema_ontology`; normalizer runtime/templates and tests/docs.
- **Intent/category:** **new capability** closing a manual acceptance gap.
- **Before → after:** users had to start from the ontology DB; now supported scalar
  generated Python contracts export normative-valid YAML/JSON without any database.
- **Database/necessity:** none in export. Adds exact `strip`/`strip_lower` normalizer
  tags to existing extension/runtime: existing whitespace/lowercase tags also collapse
  internal spaces, so substituting them would change identities on import.
- **Dependencies:** C07 introspection and C19 spec validator/serializer; imported
  normalized results use the existing runtime. Current loading executes trusted Python.
- **Tests:** seven new focused tests plus retained suites, 38 combined checks;
  normative roundtrip, executable regenerated identity (including internal spaces),
  required/types/endpoints, unsupported validators/config/defaults and no-DB tool call.
  Actual maintenance schema exported four/four definitions.
- **Docs/setup:** absolute path, bounded support and original-ontology export guidance;
  follow-up acceptance prompt updated.
- **Compatibility:** additive. Arbitrary custom validators, aliases/helpers,
  constraints or defaults may reject rather than lose behavior. The legal-run custom
  money/date validators are outside the advertised general conversion guarantee.
- **Smallest:** hide/remove only this tool/module; retain exact normalizers if already
  exported files depend on them. No customer graph migration needed.
- **Open:** fresh manual-client acceptance after loading the updated entity server;
  no sandbox and no claim of arbitrary Python equivalence.

### C22 — Immutable GraphRAG source delivery

- **What/files:** `scripts/setup-graphrag.sh`, setup, proxy server,
  `graphrag_revision.txt`, setup fixtures; separate GraphRAG PR/CI/package schema.
- **Intent/category:** UX + delivery architecture. Cloning moving HEAD once or using
  a stale published version did not deliver the requested retrieval changes reliably.
- **Before → after:** setup and proxy mounts share full SHA `0867f08…`; clean
  checkouts fetch it, dirty mismatched checkouts are preserved and setup stops clearly.
- **Database/necessity:** none. Pin file is package data, not database metadata.
- **Dependencies:** required to deliver C12 GraphRAG changes and C17–C20 consistently.
  Separate repository is gitignored; root commit alone cannot ship those sources.
- **Tests:** fresh-clone/pin/proxy transport fixtures, packaged-resource validation,
  runtime source transport and setup dirty-check preservation. Hosted GraphRAG tests
  pass on exact pin for 5.26 and 2026.09.
- **Docs/setup:** draft PR, source SHA and dirty-check recovery explained.
- **Compatibility:** source installation needs Git/network or cache. Existing modified
  checkout is not forcibly switched. Published Desktop package still needs release.
- **Smallest:** pin an older compatible SHA to disable the new tools, together with
  corresponding skills/tests. This removes retrieval features, not lexical/domain data.
- **Open:** Git source delivery is transitional; no published GraphRAG/versioned
  Desktop artifact with these changes yet. Generated MCP configs were not edited here.

### C23 — Setup safety, dependencies, timing and model preflight

- **What/files:** `setup.sh`, `scripts/setup-env.py`, `setup-dependencies.sh`,
  `check-extraction-model.py`, README and `.env.example`.
- **Intent/category:** stabilization + UX. Shell-sourcing dotenv executes input;
  optional Docling installation caused missing capabilities; provider errors surfaced late.
- **Before → after:** literal allowlisted dotenv parsing, quoted exclusive 0600
  creation/permissions and umask; mandatory Docling sync once; per-server elapsed
  sync timing. Optional `--check-model` makes one bounded structured-output request
  before config generation; normal setup remains provider-free.
- **Database/necessity:** none. Preflight is not ingestion and creates no graph.
- **Dependencies:** Python 3 prerequisite, shared entity request builder C09,
  C22 clone/pin helper and Docling minimum C15/C16.
- **Tests:** temporary-workspace setup tests use synthetic credentials/fake uv;
  verify no shell evaluation/control-variable injection, permission preservation,
  old INSTALL_DOCLING flag handling, exit propagation, pin behavior, preflight
  failure before config generation. Request tests verify bounds/no retries; one real
  configured structured request passed independently.
- **Docs/setup:** measured clean setup/first-conversion limits near Quick Start;
  no invented universal download size. Cold export 27.1s and cached clean clone 7s
  are specific observations, not final-release or platform guarantees.
- **Compatibility:** dotenv variable interpolation intentionally unsupported;
  INSTALL_DOCLING=false ignored; Python required. Explicit preflight may incur cost.
- **Smallest:** safe dotenv, dependency/timing and opt-in probe are three separable
  slices. Omit probe flag/tool if desired; reverting safe parsing restores code execution risk.
- **Open:** no minimal dependency profile, cross-platform cold/download benchmark or
  measured dependency reduction; model probe does not verify vision/embeddings/quality.

### C24 — Experimental/parser surface removal

- **What/files:** deletes lexical `parsers/vlm_blocks.py` and VLM guide; removes
  worker/orchestration/schema parameters, imports and workflow advertisements.
  Removes `create_lexical_graph.extract_toc` parameter and unused forwarding.
- **Intent/category:** UX simplification + stabilization scope reduction.
- **Before → after:** experimental VLM-block parsing and a misleading no-op TOC
  extraction switch are no longer offered. Supported PDF paths are PyMuPDF,
  Docling/page-image plus native pageless document routing.
- **Database/necessity:** no new schema, no existing data deleted. Historical
  TOCEntry references/data are not auto-migrated. `extract_toc` was a parameter,
  not a separately implemented PageIndex retrieval tool.
- **Dependencies:** routing/contracts/docs must all agree. No dependency was exclusive
  to vlm_blocks, so deleting it does not eliminate shared ML/LLM packages.
- **Tests:** live tool-schema/routing rejection and retained parser contracts verify
  removed requests fail before jobs/writes; existing modes still parse.
- **Docs/setup:** removes current recommendations; historical review mentions retained.
- **Compatibility:** intentionally breaking for callers supplying removed arguments
  or mode. Update prompts/configured calls; no DB migration.
- **Smallest:** ship the removal as a slice; restoring the mode means restoring
  implementation, orchestration and docs/tests together, not merely accepting its name.
- **Open:** `assign_section_hierarchy` retirement remains undecided; it still has a
  correction capability not replaced by native inference. No replacement TOC tool shipped.

### C25 — Deterministic fixtures, CI gates and golden extraction evaluation

- **What/files:** reusable `.github/workflows/test-contracts.yml`, publish workflow
  `needs` gates, `tests/contracts`, unit/integration/fixtures, `tests/golden`,
  `tests/skill-evals`; GraphRAG's own test/publish workflows.
- **Intent/category:** stabilization infrastructure. Previously release workflows
  could publish without the corresponding regression suites.
- **Before → after:** package publication requires shared unit/contracts and
  disposable DB/transport checks; golden runner/scorer measures a small known
  extraction fixture separately from deterministic publisher correctness.
- **Database/necessity:** production schema none. Opt-in tests use fixture labels,
  constraints/indexes and clean their owned records; do not run these against a
  valuable shared graph. Persistent test constraints may live until container teardown.
- **Dependencies:** tests follow the implementation changes above; runtime does not
  depend on golden data or CI workflows. Publish gates depend on correct environment
  and provider-free mocking assumptions.
- **Tests:** workflow contracts check required jobs/publish dependencies; golden tests
  validate scorer/schema/runner. Real configured synthetic repeats were saved, but
  small golden success is not a broad model benchmark or a guarantee against aliases.
- **Docs/setup:** opt-in flags, disposable-target requirements and evidence locations.
- **Compatibility:** no customer migration; publication can now block on failures.
- **Smallest:** keep release gates and regression fixtures even when deferring features;
  drop only tests for intentionally removed capabilities. Golden/eval tooling is optional.
- **Open:** root final combined revision has not been committed/released with hosted
  gates green. GraphRAG's hosted green result is not proof of root/Desktop delivery.

### C26 — All-format synthetic smoke/benchmark and investigation controls

- **What/files:** `tests/synthetic/{canonical,renderers,schemas,generate,validate,
  check_ingest,docling_quality,procedure_contract}.py` and tests;
  generation shell wrapper, prompts, dataset guides; generated data/outputs ignored.
- **Intent/category:** stabilization/evaluation tooling + UX, not runtime architecture.
- **Before → after:** repeatable synthetic source facts render across supported
  formats with positive/negative/lifecycle oracles; obvious smoke/benchmark prompts
  separate a small full-feature exercise from 10k-product/50-page workload.
- **Database/necessity:** fixture-only `Fixture*` labels/edges, structured keys and
  ontology data; not product-required domain labels. Real runs also instantiate the
  production schemas above. Source namespace is not business-key isolation.
- **Dependencies:** formats and runtime capabilities under test; generation uses
  isolated pinned rendering dependencies. Runtime packages need not import test tools.
- **Tests:** canonical consistency, deterministic rendering, schema/ingest checks,
  negative fixtures; controlled Docling layout variants isolate inferred headings;
  two procedure-contract tests show only descriptions change and reach the generator.
  Original benchmark failed strict counts despite 7 answers; clarified-description
  rerun passed 43 checks/7 answers with original non-null values and 20,082 edges intact.
- **Docs/setup:** saved prompts, reproduction/evidence and warm-cache timing limits.
- **Compatibility:** original generated fixtures and failed evidence preserved.
  Clarified procedure contract is a separate variant, not a global extraction fix.
- **Smallest:** ship scripts/prompts as optional examples/tests; omit large generated
  data and ignored reports. No runtime switch or user-data migration.
- **Open:** cold end-to-end timing, wider semantic workloads and repeated stochastic
  validation. Manual Claude visibility transition still open. Legal customer docs
  are not redistributed synthetic fixtures.

### C27 — Documentation, backlog and scope decisions

- **What/files:** `docs/product/{README,ROADMAP,BACKLOG,FEATURE_CANDIDATES,DECISIONS,
  PLANNING_AUDIT,RELEASE_CHECKLIST}`, ADRs/reviews, main README, AGENTS/CLAUDE,
  shared skills and new Internals/document references.
- **Intent/category:** UX/planning, not implemented product architecture.
- **Before → after:** release commitments separated from deferred architecture;
  happy path shortened; parser selection, scoped rebuild, ontology alternatives,
  model-setting selection and manual acceptance locations made explicit.
- **Database/necessity:** none. Single-spec-node storage, native db.ontology backend,
  physical-model simplification and detailed graph review are **recorded proposals**.
- **Dependencies:** docs must match actual APIs; current staleness is a release issue,
  not evidence a proposed feature exists.
- **Tests:** workflow/link/skill-structure contracts; SE review is an agent walkthrough,
  not timed novice usability. User smoke runs provide separate acceptance evidence.
- **Docs/setup:** these files are the change; review reports distinguish historical
  findings from subsequent fixes, though some older statements remain stale.
- **Compatibility:** no graph migration. Generated client config guidance now relies
  on actual MCP readiness, not assuming one agent's config path.
- **Smallest:** keep concise user-facing guides and move detailed mechanics/history
  under Internals/reviews; archiving history need not change behavior.
- **Open:** SE-003 tidy-up and owner GRAPH-001 walkthrough still pending; recent legal
  review recommendations are not implemented. Item 4 packaging/cleanup remains held.

### C28 — Desktop/source version alignment work remains incomplete

- **What/files:** source DXT manifest model/example updates; proxy child transport
  and documentation; headless Desktop tests. No newly rebuilt/published artifact.
- **Intent/category:** UX/delivery stabilization.
- **Before → after:** source examples/defaults are improved, but installed Desktop
  still resolves the old published proxy/child versions. This is **partial work**.
- **Database/necessity:** no new independent schema; effective DB behavior depends
  on which child package/source pin actually launches.
- **Dependencies:** coordinated package versions, proxy pins/resources/locks, DXT
  artifact and exact-delivery smoke; cannot advertise source-only changes as shipped.
- **Tests:** runtime schema contract and historical published headless smoke verify
  launch/calls; they do not prove final new package installation or GUI reconnect.
- **Docs/setup:** DESK-001/REL-001 track alignment; DXT→MCPB migration deferred.
- **Compatibility:** final versions/breaking-change notes still needed for field
  renames, removed parameters and legacy ownership/embedding behavior.
- **Smallest:** release coding-agent source path first only if explicitly labeled;
  hold Desktop release until actual packages/artifact are aligned. Reverting manifest
  defaults alone does not solve the package mismatch.
- **Open:** package bump/build/publish, actual final-revision smoke and manual GUI
  installation checks. None were performed while preparing this report.

## 3. Physical schema ledger: additions versus pre-existing graph vocabulary

This ledger is the implementation's possible writes, **not a claim that every
field/label exists in the owner's current database**. No current-DB introspection
or migration was performed for this report.

### S1 — Extraction completion (C05)

| Object | New persisted fields | Reason / enabled operation |
|---|---|---|
| `EntityExtractionRun` **new label** | `runId`, `fingerprint`, `model`, `sourceLabel`, `scopeId`, `completedAt`, `status` | Distinguish a fully published run/configuration from a stray provenance link |
| `PROCESSED_SOURCE` **new type**, run→Chunk/Page/custom source | `sourceFingerprint`, `invalidated` | Reuse only matching completed sources, including valid-empty results |
| Existing `EXTRACTED_FROM` | added `runId`, `extractionFingerprint` alongside existing `model`, `extractedAt`, `passType`, `passNumber` | Join materialized assertions to their publication/configuration |

No new run/source constraints or indexes. One run can have N source edges; repeated
runs accumulate run/completion records. This is a per-run hub, not one global node,
but its degree and retained count grow with workload/repeats.

### S2 — Contribution ownership/conflicts (C02/C04/C06)

| Object | Added fields/types | Reason / enabled operation |
|---|---|---|
| `EntityExtractionClaim` **new label** | `scopeId`, `sourceElementId`, `edgeId`, `proposedPropertiesJson`, `extractedAt`, `sourceLabel`, `runId`, `extractionFingerprint`, `propertyPolicy`, `conflictingProperties` | Per-source support/proposals for relationships, which cannot themselves have provenance edges |
| `CLAIM_SOURCE` **new type**, claim→source | no added properties | Find/remove relationship contributions for selected sources |
| Existing `EXTRACTED_FROM` | `extractionScope`, `ownershipVersion`, `proposedPropertiesJson`, `conflictingProperties`, `propertyPolicy` | Withdraw one scope/source and inspect rejected entity proposals |
| Extracted domain nodes | `__extractionCreated`, `__extractionLabel`, `__extractionKeyProperty`, `__extractionValues`, `__extractionReconcileLock` as applicable | Know creation/last-owned values; serialize reconciliation and conservatively garbage-collect |
| Domain relationships | `__extractionCreated`, `__extractionValues`, `__extractionReconcileLock` as applicable | Same value/deletion ownership for edges |
| Source Chunk/Page/custom node | `__extractionPublicationLock` | Lock/recheck source inputs during atomic publication |
| Structured nodes/edges | `__structuredSource`, `__structuredProperties` | Preserve CSV ownership even when values equal extracted proposals |

`__extractionValues` and `proposedPropertiesJson` are **scalar serialized JSON**,
not map-valued Neo4j properties or a list of ontology nodes. `conflictingProperties`
and `__structuredProperties` are **string lists**. Counter locks remain on records;
they are not only transient in-memory state. These are customer-visible physical
properties unless a viewer/schema projection hides them.

Claim count grows with distinct source/scope/domain-edge support. Entity provenance
degree grows with source mentions per entity. A common organization/source can
be high-degree; there is no measured universal supernode threshold. No new DDL
indexes/uniqueness constraints were added for claim lookup fields. Relationship
identity uses Neo4j element IDs, so data copying/export/reimport deserves review.

The controlled benchmark concretely added `__extractionValues` and
`__extractionReconcileLock` to **95 existing domain edges**, while retaining all
original properties. This is graph-shape/metadata cost even though preservation
tests pass. It belongs in GRAPH-001, not under “no schema changes.”

### S3 — Embedding publication (C13)

| Object | Added schema | Reason / enabled operation |
|---|---|---|
| Any embedded label, commonly Chunk | `embeddingProvider`, `embeddingModel`, `embeddingDimensions`, `embeddingInputHash`, `embeddingSpace` | Validate exact input/config/dimensions before skipping/reusing vectors |
| `EmbeddingPublicationLock` **new temporary label** | `indexName`, `token`, `generation` | Transactionally serialize publication per named index; node deleted before successful commit |
| New constraint | `neo4j_mcp_embedding_lock_unique` on `EmbeddingPublicationLock.indexName` | Make simultaneous first-publication lock acquisition unique; backing index remains |

`text_embedding` and vector/fulltext index concepts existed before this work.
The five cache fields grow linearly with embedded nodes, not relationships. Normal
successful state contains zero lock nodes; the label/constraint can remain visible
in schema tools. A foreign committed lock is refused, not silently deleted.

### S4 — Lexical metadata and format topology (C14–C16)

- `Element.order`: document reading order; `Element.sourceAnchor`: parser locator.
- `Section.order`, `pageStart`, `pageEnd`: outline order and descendant page range.
- `Document.sourceFormat`; `Chunk.sourceFormat`, `sourceAnchors` (string list).
- Pageless input uses existing `HAS_ELEMENT` from **Document directly to Element**;
  PDF modes may use Document→Page→Element. Page numbers/ranges can be null.
- **Existing**, not new: Document, Page, Element, Section, Chunk, Image/Table labels;
  HAS_PAGE/HAS_ELEMENT/HAS_SECTION/HAS_SUBSECTION/NEXT_* / PART_OF / CONTAINS /
  CAPTION_OF lexical relationships; `sectionContext`, document/version/active fields,
  and chunk-set versioning. Existing membership vocabulary gains an endpoint pattern.
- No new navigation-specific constraints/indexes. Existing Document/Element/Chunk/
  Page/Section and asset ID constraints are ensured on applicable write paths.

`Chunk.sourceAnchors` duplicates contributing element locators for convenient
citations; it could instead be derived by traversing chunk membership at query time.
Stored page ranges similarly trade metadata for cheaper outlines. New metadata
does not itself create graph hubs; Document and root Section degrees follow source
size and were already part of the lexical model.

### S5 — Ontology metadata (pre-existing topology, new interchange use)

The **released** implementation already had Ontology, NodeType, RelationshipType,
PropertyDef, AliasMap, Alias, Blocklist and BlockedTerm, with CONTAINS, DEFINES,
HAS_PROPERTY, FROM, TO, USES_ALIAS_MAP, USES_BLOCKLIST, HAS_ALIAS and HAS_TERM.
Do not attribute their introduction to N4 or PageIndex.

N4 import writes that existing shape, including Ontology `name`, spec `version`,
`displayName`, `description`; type names/descriptions; PropertyDef scalar/key/
required/normalizer configuration, alias entries and blocked terms. The import
representation can contain existing list-valued `normalizers`; it does not add a
new list-storage design. Existing global name uniqueness constraints
(`ontology_name_unique`, `node_type_name_unique`, `relationship_type_name_unique`,
`alias_map_name_unique`, `blocklist_name_unique`) and `property_def_name` index are
reused; schema errors are now consumed/reported.

An Ontology root is a type/definition hub, not a hub connected to every extracted
domain instance. Import increases use of the old topology and exposes its global-
name constraints. File-backed `get_ontology` needs none of it. Proposed one-node
spec storage and native DBMS ontology procedures have **no implemented schema** here.

### S6 — Fixed indexes and constraints summary

| Addition/change | Status |
|---|---|
| Embedding lock uniqueness + backing index | Only newly introduced fixed internal constraint in these deltas |
| Existing lexical ID constraints on additional paths/formats | Enforcement/coverage expanded; vocabulary pre-existed |
| Existing ontology constraints/index | Reused; DDL consumption fixed |
| Existing vector/fulltext indexes | Creation/fallback/readiness/definition validation changed; no automatic destructive migration |
| Run/claim indexes or uniqueness constraints | **Not added** |
| Domain key/type/existence constraints derived from ontology/Pydantic | **Not added** |
| PageIndex-specific labels/types/indexes | **Not added** |

## 4. Dependency summary and practical release boundaries

| Cluster | Cannot currently be separated cleanly | Can be deferred independently |
|---|---|---|
| Safe extraction replacement | C06 publisher + C05 completion/selection + C02 structured markers + C04 policy/proposals + shared reserved names in C07 | Exact key-normalization generation itself; whole ontology/PageIndex capability set |
| Embedding safety | C13 identity/cache/locks/publication with C12 vector definition verification; privilege docs/tests | Entity ownership, PageIndex, ontology; fulltext error fix can remain without all identity machinery after caller adaptation |
| Native hierarchy | C15 dependency APIs + parser levels + chunk heading paths + regression fixtures | C17 tree tools; C14 precomputed page ranges; ontology |
| New formats | C16 route/parser/models/reader/writer/chunk locators + C11 direct-membership deletion support | Individual formats; PageIndex optimization, provided source citations remain truthful |
| Tree retrieval delivery | C17 tools + C18 gating/notification lifecycle + C22 source pin/packaged resource + lexical topology compatibility | C20 ontology context; C14 stored ranges if computed on read; native hierarchy for flat-content reads |
| Ontology interchange/export | C19 validator/schema/dependencies + C07 contract + normalizer runtime; C21 export reuses them | C20 context can use a standalone file; C21 Python exporter can be omitted |
| Setup | C23 safe dotenv writer/parser + setup consumers; C22 pin helper/resource | Model probe, timing, mandatory full Docling policy can be reconsidered in separate tested slices |
| Release verification | C01 template/validator/examples; C25 workflow gates + their installed test dependencies | Golden evaluation and C26 generated datasets are optional developer tools |
| Desktop | C28 package versions/pins/locks/manifest/rebuilt artifact/exact-artifact smoke | New format/retrieval packages may be withheld from Desktop while source path is explicitly documented |

The largest candidate for owner scope review is **C06**, followed by **C13**.
Both provide tested guarantees but have architectural/state/privilege costs. Their
smallest viable alternatives require explicitly weaker behavior (fresh-DB or
append-only extraction; explicit whole-label embedding overwrite), not deleting
metadata while promising equivalent replacement/cache behavior.

Good independent stabilization slices are C02 compiler/null correctness, C03 honest
failures/edge ordering, C04 key normalization/property preservation, C07 validation,
C08 rebuild/page accounting, C09 parse completion, C10 lexical atomic publication,
C11 exact deletion/metadata, C12 index errors and C23 safe dotenv. Code overlap in
large server files means these are **semantic slices**, not ready-made cherry-picks.
Some reconstruction/tests would be required to split them from committed ownership.

## 5. Known incomplete work and interpretation cautions

1. **No release was made.** Root combined work is partly committed/partly untracked;
   versions are unchanged, Desktop artifact alignment and exact final-root hosted
   CI remain outstanding. GraphRAG PR is draft; its exact-pin hosted CI is green.
2. **Client acceptance is narrower than server tests.** Functional MD/PDF tree reads
   and pagination passed manually. Automatic long-lived Claude tool refresh after
   loading the new implementation remains open.
3. **N1 does not prove exact headings.** Real controls established native Docling
   extras from bold labels/contents. No blacklist/pruning hack was added. Tool
   retirement still needs a decision about explicit correction gaps.
4. **N4 has deliberate limits.** Standard-valid files can be unsupported extraction
   inputs. File-context retrieval, ontology-DB import/extraction and bounded Python
   export are different routes; they should not be presented as interchangeable.
5. **Ontology reconnect improvement is not implemented.** Path changes still require
   reload; spec-node set/get/native db.ontology backend are backlog proposals.
6. **Source lifecycle is not fully unified.** Lexical delete/rechunk and entity
   contribution cleanup are separate; external writers and old ownership metadata
   need care. No automatic database migration or cross-server recovery exists.
7. **Legal-run feedback remains unresolved product work.** Complete retrieval traces,
   tolerant report headings/tables, optional-ontology status, supported standalone
   schema-check command and improved embedding-field discovery are proposals, not
   fixes already in source. Custom legal money/percent validators are generated
   run artifacts with demonstrated unsafe accepted inputs; not a shipped parser fix.
8. **Semantic quality is separate from transport success.** Case/role aliases,
   agreement title fragmentation, weak absence checks and unexamined conflicts can
   coexist with zero runtime failures/report exit 0. A single synthetic rerun is
   not a universal extraction-quality guarantee.
9. **No new graph simplification was performed.** GRAPH-001 still requires the
   owner's detailed keep/simplify/remove/defer walkthrough, using this ledger.
   No list properties, claims, locks or ontology nodes were removed for this report.
10. **Evaluation artifacts are not shipped domain schema.** Smoke/benchmark Fixture*
    nodes, private test labels and legal-run Organization/Agreement/etc. belong to
    particular datasets. They are not fixed product labels introduced by N1/N4.

## 6. Evidence map

Detailed earlier evidence (historical snapshots; read their stated limits):

- [Owned replacement](2026-11-24-owned-replacement.md),
  [completion](2026-11-24-extraction-lifecycle.md),
  [bridge fixes](2026-11-24-bridge-fixes.md),
  [schema validation](2026-11-24-schema-validation.md).
- [Embedding identity](2026-11-24-embedding-identity.md),
  [restricted privileges](2026-11-24-restricted-onboarding.md),
  [indexes](2026-11-24-search-indexes.md),
  [atomic document publication](2026-11-24-atomic-document-publication.md),
  [deletion/metadata](2026-11-24-lexical-boundaries.md).
- [N1/N4](2026-11-24-n1-n4.md), [formats](2026-11-24-document-formats.md),
  [GraphRAG delivery](2026-11-24-graphrag-retrieval.md),
  [refresh fix](2026-11-26-pageindex-refresh.md),
  [Python export](2026-11-26-python-schema-ontology-export.md).
- [Setup](2026-11-24-setup-improvements.md),
  [cold setup](2026-11-24-cold-setup.md),
  [parser reduction](2026-11-24-parser-surface.md),
  [SE walkthrough](2026-11-24-se-usability-followup.md).
- [Original benchmark](2026-11-24-synthetic-benchmark-live.md),
  [clarified contract](2026-11-26-procedure-contract.md),
  [Docling controls](2026-11-26-docling-quality.md),
  [manual Claude acceptance review](2026-11-26-claude-smoke-review.md),
  [legal-run review](2026-11-26-legal-documents-review.md).

Snapshot file paths and hashes, including modifications not individually named
above (fixtures, locks, package metadata and review history), are in the linked
inventory. This report intentionally does not reproduce customer legal text,
credentials or all ignored generated outputs.
