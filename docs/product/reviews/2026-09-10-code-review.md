# Code review — 2026-09-10

Scope: source, packaging, and agent workflows in the published workspace template.
This review was produced independently, then compared with the external idea
harvest. It is a planning input; priorities are maintained in `BACKLOG.md`.

## Highest-risk functional gaps

1. Claude Desktop lexical ingestion uses argument names that do not match the MCP
   tool contract.
2. The coding-agent workflow describes a JSON extraction schema where the converter
   and extractor use Python schema files.
3. Desktop verification checks an embedding property name different from the one
   written by the lexical graph.
4. Desktop ontology examples use relationship types different from the ontology
   implementation.
5. The workflow attempts a report but has no deterministic check that every required
   section and per-question/per-use-case detail is present.

## Data correctness and safety

- Forced extraction can leave stale generated entities or relationships.
- Document-version deactivation and replacement are not one atomic publication step.
- Some dynamic Cypher identifiers are interpolated directly.
- Prefix-based cascade deletion can select data that is not explicitly owned by the
  target document.
- User metadata can overwrite reserved identity/version fields.

## Performance and operations

- CSV ingestion materializes whole files and can send a whole dataset in one write.
- Embedding and extraction paths can accumulate unbounded tasks/results in memory.
- Embedding reuse does not record enough model/input identity to prove cache validity.
- Index-creation failures can be hidden while the operation appears successful.
- Images stored inline as base64 can dominate graph storage and transfer cost.

## Packaging and maintenance

- Published Desktop proxy versions lag the local server versions.
- Desktop packaging requires an OpenAI key even where alternative providers exist.
- Setup writes credential material without explicitly restricting file mode and
  sources `.env` through the shell.
- Package license metadata and the repository license should be aligned.
- There are publish workflows but no repository test suite or compatibility matrix
  covering source packages, Desktop artifacts, and skill contracts.

## Architectural recommendations

- Stabilize before adding features: automated tests and current contract repairs,
  extraction semantics, safe/resumable writes, bounded server internals, reduced
  product surface, Desktop packaging, and setup/release hardening—in that order.
- Keep the template focused on rapid prototyping and as a reference implementation;
  avoid duplicating the future Trellis control plane.
- Use PyMuPDF, Docling, and page-image as separate parser adapters over one canonical
  parsed-document model and graph writer when multi-format work is prioritized after
  stabilization.
- If later prioritized, add a dedicated iterative graph-quality workflow rather than
  overloading initial graph construction.
- Keep coding-agent and Desktop skill adapters separate and validate both against
  shared contracts; generation from a common source is a later design option.
- Evaluate AIP and hooks later and experimentally; neither substitutes for persisted
  run state and deterministic outcome verification.
