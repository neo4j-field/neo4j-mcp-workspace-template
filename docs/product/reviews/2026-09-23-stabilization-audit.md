# Stabilization audit — 2026-09-23

## Scope and result

Reviewed the uncommitted stabilization work against the backlog and exercised
the current local source without changing the existing fixture data. The
contract, parser, ingest, entity, and report changes have executable coverage.
The workspace remains uncommitted pending the owner's Claude Code extraction
and release review.

## Verification

- Fast unit, contract, golden-scorer/schema, and report tests: 46 passed.
- Isolated Neo4j 2026.06.0 integration fixtures: 8 passed across entity,
  ontology, structured ingest, and lexical graph paths.
- Exact Claude Desktop DXT headless smoke: 1 passed against the isolated DB.
- BUG-004 helper against live Neo4j: prefiltered index created and observed as
  `POPULATING`; deliberate prefilter rejection fell back to an `ONLINE` plain
  index. Both fixture indexes were dropped.
- Isolated database node count after fixture teardown: 0; container removed.
- Manifest JSON, setup shell syntax, and `git diff --check`: passed.

## Changes under current review

- BUG-005: GPT-6 extraction requests omit `temperature`, set low reasoning,
  and use LiteLLM's per-request `allowed_openai_params` escape hatch. The
  `gpt-6-luna` default now appears in setup, source servers, documentation,
  Desktop manifest, and local `.env`. Parameter and mocked request-boundary
  tests pass. A live GPT-6 provider request remains to be verified.
- BUG-004: vector-index creation now consumes the result, falls back to a plain
  index if prefilter creation fails, reads the actual index state and definition,
  and errors when creation or verification fails. A repeat `embed_chunks` call
  with no new embeddings repairs/verifies the index using a stored vector's
  dimension. Unit and live Cypher checks pass. A live `embed_chunks` model call
  against Neo4j 2025.12.1 remains to be verified.
- TEST-003: a synthetic, hand-authored reference, matching Pydantic schema, and
  deterministic comparison tool are in `tests/golden/`. CI checks the reference/scorer without a model
  call. A real extraction candidate and prior-run baseline are still needed to
  report an observed quality delta.

## Important remaining risks

1. **Before the owner's extraction:** confirm the restarted Claude Code MCP
   servers load the local source and `gpt-6-luna`; use a fresh fixture namespace
   to avoid forced re-extraction on existing data. Inspect job coverage,
   relationships, provenance, vector index, and validated final report.
2. **Before commit/release:** finish review of `EXT-001` and `EXT-002` because
   forced re-extraction can leave stale graph data and skip logic can treat
   partial/incompatible work as complete. These are separate accepted backlog
   items, not covered by the current idempotent-retry fixtures.
3. **Before release:** `WRITE-001`, `SEC-001`, and `EMB-001` remain accepted
   correctness/safety gaps: atomic document publication, identifier and
   deletion ownership, and embedding cache identity. Size/performance items
   remain in the roadmap after those semantics.
4. **Claude Desktop release:** the DXT currently pins proxy `0.2.1`; that
   proxy pins lexical `0.2.0` and entity `0.4.0`, while local source is already
   `0.2.1` and `0.4.1`. The exact DXT smoke still showed the published PyMuPDF
   warning on stdio. Align package versions, publish tested server builds, then
   build and smoke-test a new DXT before distributing it. `DESK-002` provider
   requirements and `REL-001` release consistency also remain open.

The live tests used a disposable local Neo4j container. No tests were run
against the user's configured graph.
