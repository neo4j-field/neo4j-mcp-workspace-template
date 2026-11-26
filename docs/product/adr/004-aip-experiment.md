# ADR-004: Evaluate AIP before adoption

- Status: accepted
- Priority: deferred; outside the stabilization critical path
- Date: 2026-09-10
- Updated: 2026-11-24 (AIP v0.9.0 assessment)

## Context

AIP offers a structured execution-graph representation and schema validation for
agent procedures. It may improve authoring and adherence, but validation of the
procedure description is not runtime enforcement of step completion, graph
semantics, or report content.

Since this ADR was accepted, AIP shipped **v0.9.0 (19 Nov 2026)** plus
`console-v0.9.0`: a breaking rewrite of the earlier YAML format with no upgrade
tool. A `procedure.aip` file compiles to a hash-identified `.rl` bundle. Steps are
`Start`, `Decide` (typed questions to a decision model), `Route` (branch with an
optional confidence gate), `Aggregate` (`All`/`Any`/`None`), `Execute` (local
script, **unsandboxed**, 300 s default timeout), `Task_Agent` (pause for an agent
or human to produce keys) and `End`; `For`/`Loop` have caps. State is a single
typed JSON document. Clients are a CLI (`aip run/resume/search/audit/export`), an
MCP server (`aip mcp`) and a Python SDK; the console (`npx aip-console`) offers
Studio chat authoring, graph views and run history. Runs are stored in **Relate**
by default, or Neo4j/Aura for shared use. Decision models are currently tested
with **Jev** (TypeSafe), the same model as candidate N6. `aip export <procedure>
--skill DIR` emits a plain Agent Skill, so AIP can remain an authoring-time tool
with no runtime dependency. The installer detects Claude Code, Cursor, Copilot,
Gemini, Codex and OpenCode. `pip install` requires Python 3.14+ (or use
`uv tool install`).

The strongest fit is authoring and verifying the `develop-neo4j-graph` workflow,
where WF-005 already defines the report-completion contract. AIP's catalog, run
records and console are a durable runtime control plane; that is **Trellis**
scope, not template scope. AIP's published benchmarks do not measure graph
building, so only our own fixture is decisive.

## Decision

Keep AIP as a pinned side experiment. Encode the `develop-neo4j-graph` procedure,
add the semantic checks needed locally, and compare it with the current skill plus
the WF-005 report validator. Measure activation, required-step adherence, report
completeness, recovery, latency, and token/tool cost over repeated scenarios on
the team's PDF-to-graph fixture rather than relying on AIP's published numbers.

Run two additional bounded checks:

1. **`Decide`/`Route` + Jev** on a real decision point (parser choice, model
   choice, or confidence-gated escalation), measured against the current
   deterministic default. This informs N6, not the workflow-adherence result.
2. **`aip export <procedure> --skill`** — verify that the exported plain Agent
   Skill is usable in all seven supported tools and keeps the template
   dependency-free. This is the preferred adoption shape if it works.

Trust and operational cautions to record during the experiment: `Execute` runs
local scripts unsandboxed; `pip` needs Python 3.14+; the format is young and has
already broken once; decision models are Jev-only today; and AIP's resumable runs
do **not** replace Neo4j write idempotency (WRITE-002 stays deferred).

Do not fork AIP, rebuild it in the template, or make it a customer dependency
until the experiment demonstrates a material advantage. Prefer upstream
contributions for generic validator improvements. Keep AIP and gbuild in separate
roles: gbuild is for developing the template, AIP for the user-facing workflow,
and Trellis for durable runtime orchestration.

## Consequences

- The product roadmap is not blocked by a young procedure format.
- Evidence, rather than format preference, drives adoption.
- AIP can still become an authoring/validation layer over the same portable runtime
  completion contract, and the export-to-skill path lets it stay out of the
  runtime entirely.
- One workflow gains a machine-checkable description only if the experiment shows
  adherence or authoring gains that justify maintaining a second representation.
