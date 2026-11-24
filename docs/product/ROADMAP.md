# Roadmap

The roadmap is ordered by dependency and user outcome. Dates should be added only
when there is a delivery commitment.

## Stabilization release

No new product capability is required for this release. The objective is to make
the existing promise correct, testable, safe, scalable, and supportable.

### 1. Create the automated safety net and repair current contracts

- Repair the four known skill/tool contract mismatches.
- Add unit tests for server logic and contract tests across MCP tools and skills.
- Add small end-to-end fixtures for current parser modes, structured ingest,
  extraction, coding-agent workflows, and Desktop workflows.
- Add failure-path tests and a deterministic final-report verifier.
- Reproduce and fix the known chunk-clear and relationship/extraction regressions.

Exit condition: CI catches every currently known workflow mismatch and blocks a
release when unit, contract, integration, or Desktop smoke tests fail.

### 2. Correct extraction and embedding semantics

- Define source, schema, extractor, configuration, and embedding identities.
- Make forced re-extraction remove or replace stale generated data.
- Replace broad “data exists” skip checks with explicit successful-run semantics.
- Preserve provenance for every generated entity and relationship.

Exit condition: repeat and changed-schema runs are deterministic, attributable, and
covered by regression tests.

### 3. Make graph writes safe and resumable

- Publish document versions atomically.
- Add idempotent batches and stage-local checkpoints for restart/retry; do not build
  the Trellis cross-server run ledger in the template.
- Validate dynamic identifiers and replace prefix deletion with explicit ownership.
- Protect reserved metadata and surface index/write failures.

Exit condition: interruption or retry cannot activate a partial version, duplicate
generated data, or delete unrelated data.

### 4. Fix scaling architecture inside the servers

- Stream or batch CSV reads and Neo4j writes.
- Bound embedding and extraction queues, concurrency, and retained results.
- Benchmark representative workloads and define memory/throughput expectations.
- Decide image-storage policy using measured size and transfer costs.

Exit condition: representative larger inputs stay within configured resource bounds
and preserve retry/correctness guarantees.

### 5. Reduce product surface

- Inventory servers, skills, proxies, packaging paths, and duplicated implementations.
- Remove the experimental `vlm_blocks` mode while retaining PyMuPDF, Docling, and
  page-image.
- Assign keep, merge, deprecate, or Trellis/shared-library ownership.
- Remove approved duplication with compatibility and migration tests.

Exit condition: every published surface has a clear owner and purpose, and there is
one maintained implementation for each core responsibility.

### 6. Improve Desktop packaging

- Build Desktop artifacts from aligned source versions.
- Make provider requirements conditional.
- Test installation, startup, tool schemas, and a small workflow in the packaged form.

Exit condition: the Desktop artifact is version-aligned and its advertised provider
configurations pass smoke tests.

### 7. Harden setup and release

- Install Docling as part of the standard lexical-graph environment without an
  optional prompt.
- Measure and report per-server cold/warm installation time, then remove avoidable
  ingest dependencies.
- Parse credentials without shell execution and restrict `.env` permissions.
- Align package metadata, locks, versions, and licenses.
- Add compatibility/release checks and require the complete CI suite before publish.

Exit condition: a clean checkout can be configured and released reproducibly, and
the published artifacts are demonstrably the tested artifacts.

## After stabilization: future capabilities

Only prioritize these after the stabilization exit conditions are met:

1. Multi-format normalization using distinct PyMuPDF, Docling, and page-image
   adapters behind one canonical contract.
2. The iterative `assess-and-improve-neo4j-graph` quality workflow.
3. Candidates from `FEATURE_CANDIDATES.md`, reviewed and promoted through an explicit
   prioritization pass.

## Deferred experiment: AIP and hooks

This is not part of the stabilization critical path. When capacity permits, test
whether AIP improves trace adherence and authoring, and whether tool-specific hooks
add useful preflight/postflight guards. Adoption requires measured improvement over
the portable workflow-state approach.
