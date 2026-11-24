# ADR-003: Add an iterative graph quality workflow

- Status: accepted
- Priority: deferred until after stabilization
- Date: 2026-09-10

## Context

The common iteration is not adding new documents. A graph is built, inspected for
quality problems, reported on, improved by changing its schema or extraction rules,
and extracted again. The cycle repeats until quality is acceptable.

## Decision

Create a separate `assess-and-improve-neo4j-graph` workflow with these phases:

1. Capture the current schema, extraction configuration, source/run provenance,
   and baseline metrics.
2. Run structural and semantic diagnostics for duplicates, wrong labels, malformed
   properties, anomalies, orphans, relationship direction/types, provenance gaps,
   and extraction coverage.
3. Produce a detailed quality report with evidence, severity, confidence, proposed
   change, expected impact, and validation method for each finding.
4. Ask for approval before schema changes or destructive replacement.
5. Version the schema/configuration and re-extract the affected scope, replacing
   stale generated entities and relationships safely.
6. Re-run the same checks and publish a before/after comparison with regressions and
   remaining issues.
7. Repeat only when evidence supports another round.

The build workflow may recommend this workflow after its initial report, but the two
remain separately triggerable and testable.

## Consequences

- “Build” stays understandable for first-time users.
- Improvement can be applied to graphs created earlier or outside the current run.
- Quality reports become actionable specifications for the next extraction round.
- Re-extraction needs explicit ownership, versioning, and rollback/recovery rules.
