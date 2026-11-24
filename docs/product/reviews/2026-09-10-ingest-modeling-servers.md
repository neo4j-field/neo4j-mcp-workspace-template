# Ingest and data-modeling server review

Date: 2026-09-10

Status: recommendation for discussion; this document does not authorize a migration.

## Executive recommendation

Do not continue treating these two servers as opaque infrastructure, and do not immediately fork the complete data-modeling package.

During stabilization:

1. Put contract, security, and integration tests around the small subset of tools the workspace actually uses.
2. Fix or contain the unsafe hand-off of generated Cypher before relying on structured-data ingestion.
3. Rewrite the local ingest implementation around bounded batches and the Neo4j driver rather than importing an entire Cypher MCP server.
4. Assign an explicit maintainer and dependency-update policy.

During product-surface reduction, evaluate replacing the two-server boundary with one small, owned structured-data component. It should share a validated model and ingestion compiler internally while preserving temporary compatibility aliases for existing tools.

The full modeling package contains useful conversions and transports, but most are not used by this template. Owning all of it would create unnecessary maintenance responsibility.

## What installation is doing

- `mcp-neo4j-ingest` is local source in this repository. Setup creates its environment and downloads its dependencies.
- `mcp-neo4j-data-modeling` is not local source. Setup invokes the published `mcp-neo4j-data-modeling==0.8.2` package through `uvx`, so application code and dependencies are resolved into the uv cache.
- The ingest environment currently resolves approximately 103 packages and occupies approximately 166 MB. Much of this comes from FastMCP and its transitive stack, plus `mcp-neo4j-cypher`, pandas/numpy, and tiktoken.

This explains a substantial part of the ingest installation delay. A clean-machine benchmark is still required before setting a target.

## Ingest server findings

Reviewed source: `mcp-neo4j-ingest/src/mcp_neo4j_ingest/server.py`.

### Critical

- A complete CSV is loaded into a pandas DataFrame, converted to a list of dictionaries, and sent in a single request. Memory usage and transaction size grow with the entire input.
- An agent-supplied write query is forwarded to the generic Cypher server. There is no validated ingestion-plan boundary.
- The server exposes the underlying generic write tool as `execute_write_cypher_query`. This duplicates existing write capability and widens the destructive surface.

### High

- File paths, type, size, encoding, delimiter, and required columns are not validated.
- There is no batching, checkpoint, progress reporting, bounded retry, dead-letter output, or safe resume mechanism.
- Runtime validation uses `assert`; assertions can be disabled and do not produce a useful MCP error contract.
- The async driver is initialized at module import and is not explicitly closed.

### Architecture and performance

- The server imports and constructs the full `mcp-neo4j-cypher` server merely to reuse one write tool.
- Dependency constraints are open-ended enough to allow surprising environment changes.
- pandas may be unnecessary for a streaming CSV path; that decision should follow type and dialect requirements rather than convenience.

### Recommended disposition

Retain the ingestion capability, not this implementation. Replace it locally with:

- a direct Neo4j-driver implementation;
- a validated declarative ingestion plan rather than arbitrary Cypher;
- streaming input and configurable bounded `UNWIND` batches;
- explicit transaction, retry, idempotency, checkpoint, error, and progress contracts;
- allowlisted local paths and input limits;
- lazy driver creation and deterministic shutdown;
- integration tests against a disposable Neo4j database and performance tests at representative file sizes.

Remove the generic write alias once compatibility impact has been measured. Existing general Cypher tooling should remain the explicit escape hatch.

## Data-modeling server findings

Reviewed artifact: `mcp-neo4j-data-modeling==0.8.2`, corresponding to the upstream `mcp-neo4j-data-modeling-v0.8.2` tag.

The package is approximately 5,591 lines across its main modules. Its upstream unit suite passes (216 tests), but those tests do not cover several important failures reproduced during this review.

### Critical correctness and safety defects reproduced

- Relationship ingestion generates an unbound relationship and applies relationship properties to the end node instead.
- Labels, relationship types, and property identifiers are interpolated into generated Cypher without safe validation or quoting. A malicious or malformed label is accepted and produces executable malformed/injected Cypher.
- Invalid Neo4j property-type names are accepted.

The first two defects become substantially more serious when the output is passed directly to the ingest server's generic write function.

### Additional correctness defects reproduced or identified

- Duplicate relationship definitions with the same pattern are accepted.
- GraphRAG-schema import mutates its caller's input payload when it removes the selected key property.
- Some schema-import validation uses `assert`.
- Generated Python identifiers are protected against Python keywords but not all invalid identifier characters.
- Relationship constraint names can collide.
- Several mutable list/dictionary defaults should be replaced with factories.
- Direct module execution calls an async function incorrectly, although the installed console entry point wraps it correctly.

### Actual template usage

The current instructions primarily use:

- model validation;
- example listing and retrieval;
- Mermaid rendering;
- node and relationship ingest-query generation;
- constraint generation.

The workspace does not currently demonstrate a strong need for the package's HTTP/SSE hosting, MCP prompt, Arrows conversions, OWL/RDF conversions, GraphRAG schema round trips, or Pydantic-model export. Extraction already has a separate schema conversion path.

### Recommended disposition

Short term:

- keep the exact version pin;
- add black-box compatibility tests for every modeling tool invoked by workspace instructions;
- stop using the relationship ingest-query result until its semantics are corrected and tested;
- validate model identifiers and Neo4j property types at the workspace boundary;
- add tests that compile a model, ingest records, and verify the resulting labels, relationships, properties, constraints, and rejection behavior;
- report fixes upstream, but do not make stabilization depend on upstream response time.

Later, replace only the used core with owned code, or maintain a narrow adapter if upstream ownership becomes reliable. Do not copy the entire package by default.

## Proposed target boundary

One owned structured-data component could expose stateless modeling tools even when no database is configured, and create a database driver lazily only for ingestion. Internally it should have three separable layers:

1. Validated graph model.
2. Deterministic compiler from model plus mappings to an ingestion plan.
3. Bounded executor for that plan.

This removes the current `modeling server -> raw Cypher string -> generic write server` trust boundary. It also reduces setup surface while keeping modeling and execution independently testable.

Compatibility names should be maintained for a deprecation window. Consolidation should happen only after contract tests describe current customer-visible behavior.

## Minimum test matrix

- Valid and invalid model identifiers and property types.
- Node keys, composite keys, null/missing values, and duplicate records.
- Relationship direction, endpoints, keys, and relationship properties.
- Re-running each batch without duplicating graph entities or relationships.
- Partial failure followed by resume.
- Empty, malformed, differently encoded, and oversized files.
- Batch and file-size scaling with recorded time and peak memory.
- Cancellation and database unavailability.
- Generated constraints and compatibility of retained MCP tool schemas.

## Ownership actions

- Name a maintainer and backup owner in `CODEOWNERS` or the project governance documentation.
- Inventory every externally fetched runtime component, version pin, license, upstream repository, and update procedure.
- Retain the MIT license and attribution if any upstream modeling code is vendored.
- Add dependency and tool-contract checks to CI.
- Define a supported-version and deprecation policy before publishing renamed or consolidated tools.

## Suggested sequencing

1. Characterization and adversarial tests for both current servers.
2. Immediate containment of unsafe/generated Cypher and relationship-property behavior.
3. Rewrite and benchmark the small local ingest server.
4. Complete the broader extraction, resumability, scaling, setup, and release stabilization work.
5. Decide, using usage evidence, whether to build the minimal owned combined component or retain a tested modeling adapter.
6. Consider optional modeling conversions only during later feature prioritization.

## Decision needed later

After the characterization tests, choose between:

- **Preferred if the used surface stays small:** build the minimal owned structured-data component and deprecate the two-server workflow.
- **Lower initial effort:** keep the published modeling package behind a strict local adapter and own only ingestion.
- **Not recommended:** vendor the complete modeling package and inherit every transport, conversion, and example as supported product surface.
