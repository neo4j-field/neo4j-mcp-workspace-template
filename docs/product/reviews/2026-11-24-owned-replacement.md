# Owned extraction replacement — 2026-11-24

## Problem and resulting behavior

The lifecycle audit showed that MERGE plus property updates retained removed schema
labels, relationships and properties. EXT-001 now replaces tracked contributions
for explicit sources in a stable extraction scope instead of accumulating output.

- `extraction_scope` is stable across schema/model revisions. Its default derives
  from source label plus absolute schema path or ontology name. Different scopes
  coexist. `source_ids` optionally limits a rebuild to selected Chunk/Page IDs.
- All source/model results are staged. A single managed Neo4j transaction removes
  selected contributions, reconciles remaining support, writes new graph output,
  garbage-collects unused owned objects and publishes completion.
- Source inputs are checked again under publication locks. Mutation/deletion during
  model work aborts publication rather than writing stale results.
- Model failure publishes no partial domain results. Missing endpoints/write
  failures roll back withdrawal and new writes together. Cancellation during
  extraction stops child work and preserves prior domain output. A completed commit
  cannot be undone by a later cancellation request.
- Partial duplicate entity/relationship records are coalesced so every supported
  property is retained in the source contribution. Preserve mode takes the first
  non-null duplicate value; overwrite takes the last. Publication order is stable
  by source ID, not model completion time.
- Missing/null fields withdraw prior owned assertions; they do not explicitly
  delete external/structured properties. Empty successful extraction withdraws
  the whole old contribution.
- Kept canonical
  nodes retain identity; stale extraction-created objects are removed only when
  unchanged and unreferenced by other contributions or foreign data.

## Ownership and preservation

Entities retain scope-specific EXTRACTED_FROM links. Relationship contributions use
EntityExtractionClaim records linked to their source. Both retain proposed values,
run ID/fingerprint and scope metadata. Only properties introduced by extraction and
objects created by it are owned. Reconciliation retains other sources/scopes and
can rematerialize a property from remaining support after its original source is
withdrawn. External edits and foreign properties, labels and relationships are
conservatively preserved.

The CSV compiler declares structured ownership on nodes and relationships with
reserved __structuredSource/__structuredProperties metadata. This protects imports
after extraction even when they assert identical values. Custom writers must use
equivalent protection for such assertions; equal-value ownership cannot be inferred.
Reserved extraction labels, relationship types and ownership property prefixes are
rejected at the relevant extraction/CSV write boundaries.

The preserve_existing/overwrite policy now applies to relationship properties too;
previously relationships always overwrote. Relationship conflicts/proposals are on
EntityExtractionClaim records. This preserves pre-existing CSV relationship values
by default while keeping explicit overwrite available.

## Legacy boundary

Older provenance lacks deletion ownership and is never automatically adopted.
Selected legacy/incomplete links cause actionable refusal before replacement. Known
legacy proposals from other sources may support values without granting ownership;
unknown property support aborts an ambiguous replacement and rolls back cleanup.
Use a reviewed migration or a fresh source namespace with source_ids explicitly
selecting its new chunks. No database reset or automatic migration is performed.

## Verification

On disposable Neo4j Kernel 5.26.33 Enterprise:

- 55 fast tests passed: entity/identity/schema/runner 15, lexical 15, ingest compiler
  6, workflow/release/scorer contracts 13, report validation 6.
- 34 database checks passed: 19 ownership/replacement, 5 completion, 2 coverage and
  restart, 6 bridge/schema/relationship, 1 ontology workflow, 1 structured ingest.
- Replacement scenarios cover removed schema labels/edges/properties; empty output;
  support from another source or scope; CSV before/after extraction; external node
  and edge edits; shared relationship properties; failure rollback; cancellation;
  legacy support/refusal; source mutation during model work; partial duplicate
  records; and owned null-field withdrawal.
- Existing partial-coverage tests now verify zero published partial data on failure.
  Snapshot fixtures tolerate list-valued ownership metadata.
- New regression coverage is included in the reusable CI release gate. Hosted CI
  itself was not run here. Python compilation and git diff --check passed.
- Teardown left zero nodes and the disposable container was removed. No test used
  the owner's configured graph, changed credentials, or made model/provider calls.

## Remaining limits

Publication retains results in memory and uses one transaction per selected scope;
large-run bounds/throughput remain PERF work. Serialize jobs touching shared
canonical entities until broader uniqueness/checkpoint/concurrency hardening lands.
Claims are current contribution state, not complete property-level history. Custom
non-JSON types are retained conservatively when identity cannot be proven. Source
deletion outside this publisher, orphan-claim/history retention and cross-server
recovery remain separate write/lifecycle work. Packaged Desktop versions still need
alignment before these source changes can be advertised in a Desktop release.
