# Embedding identity — 2026-11-24

## Behavior

EMB-001 records provider, exact configured model, actual dimensions, exact composed
input hash and embedding-space fingerprint with each text_embedding. Cache reuse
requires all these fields plus actual vector size to agree. Legacy vectors without
identity regenerate. Input hashes cover the exact text sent to LiteLLM, including
ordered context and whichever raw-text/visual-description fallback actually wins.
An unused raw-text change does not invalidate a preferred visual description.

Optional dimensions is forwarded to the provider; optional include_inactive expands
label-wide Chunk refreshes to inactive nodes whose vectors also share the index.
Explicit dimension conflicts with an existing index fail without a provider request.
Provider-default dimensions are obtained from cache or the actual refresh response;
there is no additional billable dimension-probe request. A hidden remote model-alias
retargeting with unchanged identifiers cannot be inferred: use versioned model IDs
or an explicit whole-label overwrite when an alias changes.

## Index-space and publication boundaries

All vectors preserved in a label's shared index must have verifiable matching
provider/model/request configuration and dimensions. Document-only model migration
refuses to mix spaces with other documents or inactive indexed nodes. A compatible
whole-label same-dimensional migration regenerates all needed vectors atomically.
Incompatible named-index dimensions require an explicit reviewed index migration
or genuinely separate physical storage; the tool never drops indexes automatically.

An added label on the same nodes is not separate vector storage: this API always
writes text_embedding. New/model-space writes refuse other same-property indexes
that overlap the selected nodes. Same-space refreshes validate overlapping index
dimensions. Current labels/metadata and index overlaps are checked again after source
row locks, so labels/indexes attached during provider work do not bypass the guard.

Vector data and cache metadata commit together in one managed transaction. A reserved
unique constraint enables a temporary per-index publication lock; create/inspect
privileges are checked before provider requests. The temporary node is deleted at
commit or rollback. A committed pre-existing reserved lock node is refused and
preserved, not claimed/deleted as if created by the current call. Source locks use a
self-assignment of the vector property instead of adding a persistent lock-counter
field to domain nodes. Provider response cardinality, unique IDs, uniform/requested
dimensions, numeric/finite FLOAT32 representation and nonzero cosine vectors are
validated before writes. Preserved vector spaces are rechecked under the lock.

The uniqueness constraint and an empty verified vector index can remain after a
later provider/source check aborts. These schema side effects are separate from
atomic vector/metadata publication. Existing indexes/constraints are never dropped
by production code. Exact equivalent-schema creation races proceed only to named
index verification; ordinary failures still surface. Valid cached inputs repair a
missing vector index without another provider request. Indexed nodes whose usable
source text was removed cause an actionable error instead of a false cached no-op.

## Verification

- 5 new identity/dimension/constraint unit tests and 6 existing/extended vector-index
  fallback/race unit tests passed (11 focused tests).
- 15 embedding-identity integration scenarios and the existing vector-index fallback
  integration passed against the parent-provided disposable Neo4j 2025.12.1 target
  (16 checks, no skips, no provider calls).
- Scenarios cover legacy regeneration; cache skip/index repair; exact context,
  fallback and visual-description changes; document/inactive scope migration;
  explicit/default dimension mismatch; partial provider responses; source mutation;
  missing constraint privilege; overlapping-label refusal; labels/indexes attached
  during provider work; preserved-space tampering; dimension metadata repair; removed
  source input; concurrent incompatible document publications; and foreign lock data.
- Concurrency fixture uses one shared provider patch so it leaves no mock behind.
  Auto-description assertions do not depend on Neo4j record order.
- Each integration teardown asserts zero temporary publication locks and removes
  only its private fixture nodes/indexes. The shared constraint remains for parent
  combined checks/container teardown.

Tests use deterministic embedding outputs. No operation used the configured user
graph, modified credentials/generated MCP config, or made a model/provider request.
The parent runs the broader combined suite and owns CI/backlog registration.

## Files and test entry points

Implementation: lexical server.py, embedder.py and new embedding_identity.py.
Docs: lexical README.md and docs/tools-embedding.md. Standalone install now uses
uv sync --extra docling to match the setup track's supported baseline.

Fast modules:
- tests.unit.test_embedding_identity
- tests.unit.test_vector_index_fallback

Native vector modules:
- tests.integration.test_embedding_identity_mcp
  (NEO4J_MCP_RUN_EMBEDDING_IDENTITY=1)
- tests.integration.test_vector_index_fallback_mcp
  (NEO4J_MCP_RUN_VECTOR_FALLBACK=1)

## Remaining limits

Publication still retains inputs/results in memory and uses a single write
transaction; queue/memory bounding is separate PERF work. Existing fulltext-index
definitions and fulltext-only cache-hit repairs are not migrated by this change.
Current routing identity conservatively hashes endpoint-style environment variables;
unrelated endpoint changes can cause extra invalidation. Narrowing that list to the
resolved provider's SDK prefixes would reduce unnecessary refreshes without weakening
model/input identity. Metadata fields belong to this embedding API; external vector
writers must keep them coherent or explicitly refresh. This is not a historical
embedding-run ledger or a solution for opaque remote model-version changes.
