# ADR-004: Evaluate AIP before adoption

- Status: accepted
- Priority: deferred; outside the stabilization critical path
- Date: 2026-09-10

## Context

AIP offers a structured execution-graph representation and schema validation for
agent procedures. It may improve authoring and adherence, but validation of the
procedure description is not runtime enforcement of step completion, graph
semantics, or report content.

## Decision

Keep AIP as a pinned side experiment. Encode one existing workflow, add the semantic
checks needed locally, and compare it with the current skill plus external workflow
state. Measure activation, required-step adherence, report completeness, recovery,
latency, and token/tool cost over repeated scenarios.

Do not fork AIP, rebuild it in the template, or make it a customer dependency until
the experiment demonstrates a material advantage. Prefer upstream contributions for
generic validator improvements.

## Consequences

- The product roadmap is not blocked by a young procedure format.
- Evidence, rather than format preference, drives adoption.
- AIP can still become an authoring/validation layer over the same portable runtime
  completion contract.
