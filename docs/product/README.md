# Product planning

This directory is the durable source of truth for product decisions and planned
work. It complements issue tracking: issues may describe implementation tasks,
while these documents preserve the reasoning and acceptance criteria.

- `BACKLOG.md` records candidate work, evidence, scope, and acceptance criteria.
- `ROADMAP.md` groups accepted work into outcomes and sequencing.
- [Release checklist](RELEASE_CHECKLIST.md) records finite release gates and pending evidence.
- [Simplification decisions](reviews/2026-11-24-se-simplification.md) records keep / Internals / defer choices.
- `FEATURE_CANDIDATES.md` preserves the idea pool (N1/N4 are now pre-release commitments)
  and its traceability to `IDEAS_HARVEST.md`.
- `DECISIONS.md` is the decision index; detailed decisions live in `adr/`.
- [N1/N4 implementation and validation](reviews/2026-11-24-n1-n4.md) records the latest feature pass.
- [GraphRAG retrieval implementation](reviews/2026-11-24-graphrag-retrieval.md) records document-tree tools and ontology context.
- [Live release acceptance](reviews/2026-11-24-live-release-acceptance.md) records the passing live workflow and the corrected harness-only metadata issue.
- [Cold setup](reviews/2026-11-24-cold-setup.md), [restricted roles](reviews/2026-11-24-restricted-onboarding.md), and [lexical bug fixes](reviews/2026-11-24-lexical-boundaries.md) record onboarding/correctness evidence.
- [Document-format implementation](reviews/2026-11-24-document-formats.md) records all four formats and actual-provider acceptance.
- [Input-format options](reviews/2026-11-24-format-options.md) assesses small extensions without adding them to release scope.
- `reviews/` contains dated reviews and research notes.

`IDEAS_HARVEST.md` is an input to planning, not the committed backlog itself. Its
ideas are indexed in `FEATURE_CANDIDATES.md` and should be independently validated
before being promoted to `BACKLOG.md` and scheduled in `ROADMAP.md`.

[Synthetic dataset and SE walkthrough](SYNTHETIC_DATASET.md) · [coverage plan](SYNTHETIC_DATASET_PLAN.md)
