# Product planning

This directory is the durable source of truth for product decisions and planned
work. It complements issue tracking: issues may describe implementation tasks,
while these documents preserve the reasoning and acceptance criteria.

- `BACKLOG.md` records candidate work, evidence, scope, and acceptance criteria.
- `ROADMAP.md` groups accepted work into outcomes and sequencing.
- `FEATURE_CANDIDATES.md` preserves the unprioritized post-stabilization idea pool
  and its traceability to `IDEAS_HARVEST.md`.
- `DECISIONS.md` is the decision index; detailed decisions live in `adr/`.
- `reviews/` contains dated reviews and research notes.

`IDEAS_HARVEST.md` is an input to planning, not the committed backlog itself. Its
ideas are indexed in `FEATURE_CANDIDATES.md` and should be independently validated
before being promoted to `BACKLOG.md` and scheduled in `ROADMAP.md`.
