# Planning conformance audit — 2026-09-10

## Decisions from the discussion

| Decision | Conformance after audit |
|---|---|
| Stabilize existing code before new features. | Yes. The roadmap contains one stabilization release before future capabilities. |
| Stabilization order: tests/contracts, extraction semantics, safe/resumable writes, server scaling, reduced surface, Desktop packaging, setup/release. | Yes. Roadmap phases 1–7 use this order. |
| Add automated tests. | Yes. Unit, MCP/skill contract, integration, Desktop smoke, failure, golden regression, and performance coverage are P0. |
| Keep PyMuPDF, Docling, and page-image; unify their contract later rather than merging implementations. | Yes, deferred until after stabilization. `vlm_blocks` removal is P0 surface reduction. |
| The graph assessment/improvement loop is useful but not a current priority. | Yes. Its design is retained as deferred P2 and its eval scenario is disabled for stabilization. |
| AIP must be experimented with before adoption or rebuilding. | Yes. It is a deferred P3 experiment outside the release path. |
| Hooks may guard report completeness but cannot be the portable workflow engine. | Yes. Stabilization requires a deterministic report validator; hooks/controller work is deferred. |
| Coding-agent and Desktop skills should not become one giant skill. | Yes. Stabilization tests their shared contracts while preserving client adapters; later generation from a common source remains a design option. |
| Template work must not duplicate Trellis's control plane. | Yes after correction. P0 resumability is stage-local; the full run ledger, deterministic spine, and ontology registry remain Trellis scope. |

## Corrections made by this audit

1. Narrowed P0 report completeness from a new workflow controller to a deterministic
   validator used by the existing skills.
2. Narrowed P0 resumability from a cross-server durable ledger to stage-local,
   idempotent checkpointing.
3. Made removal of `vlm_blocks` explicit in surface reduction while retaining the
   three agreed parser strategies.
4. Added known harvested regressions, model preflight, golden tests, deprecated
   retrieval compatibility, and bounded retry/dead-letter behavior to stabilization.
5. Added `FEATURE_CANDIDATES.md` so all harvested themes remain available for later
   prioritization without entering the current roadmap.

## Code-review findings outside stabilization

The concrete defects, correctness risks, scaling problems, packaging drift, setup
risks, missing tests, and product-surface reduction found in the code review all
belong to stabilization.

These architectural recommendations do not:

- a canonical multi-format parser adapter model beyond what is necessary to remove
  `vlm_blocks` safely;
- the iterative graph assessment/improvement workflow;
- AIP adoption, hook integrations, or a portable workflow controller;
- new provenance/citation products such as Fact/Evidence modeling;
- entity resolution, ontology collaboration, modeling-server replacement, and other
  feature candidates;
- Trellis control-plane capabilities such as a cross-server run ledger.

The base64 image-storage finding is the only boundary case: measuring it and making
current behavior safe/configurable is stabilization; redesigning media storage as a
new external asset subsystem is a later product decision.
