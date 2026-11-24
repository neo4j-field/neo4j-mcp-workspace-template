# ADR-002: Enforce workflow completion outside skill prose

- Status: accepted
- Priority: report contracts and deterministic validation are stabilization;
  persistent workflow control and hooks are deferred
- Date: 2026-09-10

## Context

Agents generally create the final report but sometimes omit required detail. Long
skills place step instructions, tool contracts, recovery behavior, and output
requirements in one context. Hooks can intercept lifecycle events in some clients,
but are not portable across Claude Desktop, Claude Code, Codex, and other agents.

## Decision

For stabilization, define machine-checkable report contracts and a deterministic
verifier. Existing skills must run the verifier before claiming completion and must
correct missing sections or per-question/per-use-case details. This does not require
a new workflow controller.

After stabilization, experiment with explicit workflow state outside the model's
prose. A run could record phase status, artifacts, validation evidence, failures,
and decisions. A future MCP controller or Trellis service may expose `start`,
`next_actions`, `record_result`, `status`, and `finalize` operations.

Use hooks where available only as optional fast safeguards. Do not use hooks as the
only workflow engine or source of truth.

## Consequences

- Report completion is defined by validated evidence rather than whether the final
  step was attempted.
- Required report sections become testable artifacts.
- Persistent run control is not added to the stabilization release.
- Any later hook integrations remain thin, client-specific adapters.
