# Skill evaluations

This directory defines client-neutral evaluations for graph-development skills.
The first goal is to catch contract drift and incomplete outcomes, not to judge
writing style.

The stabilization suite covers existing functionality first. Scenarios marked
`deferred_until_after_stabilization` document future acceptance criteria but are not
part of the current release gate.

## Evaluation layers

1. Static contract: validate every documented MCP call against the live tool schema.
2. Activation: verify complete, incomplete, negative, build, and improve requests
   trigger the intended workflow.
3. Trace: verify required partial ordering, checkpoints, approvals, and prohibited
   calls without requiring one exact agent transcript.
4. Outcome: query deterministic graph invariants and validate generated artifacts,
   especially required report sections and evidence.
5. Recovery: repeat with injected parser, provider, restart, partial extraction,
   ontology-change, and cancellation failures.

## Metrics

- workflow completion rate
- required-step and required-report-field recall
- invalid tool-call count
- unnecessary/repeated tool-call count
- recovery rate
- graph invariant pass rate
- elapsed time and estimated provider cost

Use an LLM judge only for genuinely semantic criteria. Structural requirements,
counts, provenance, schema versions, report headings, and evidence links should use
deterministic verifiers.

`scenarios.yaml` is the initial scenario inventory. The packaged contract at
`mcp-neo4j-proxy/src/mcp_neo4j_proxy/report_contracts.yaml` turns the detailed
report requirements into machine-checkable contracts for both the CLI and Desktop
MCP tool.

The first executable gate lives in `tests/contracts/` and checks current MCP/skill
contracts without installing server dependencies:

```bash
python -m unittest discover -s tests/contracts -v
```

Run the report-verifier tests with:

```bash
uv run --project mcp-neo4j-proxy \
  python -m unittest discover -s tests/report_validation -v
```

The first live-database test exercises structured ingestion, relationship
properties, replay idempotency, graph invariants, and fixture-scoped cleanup:

```bash
NEO4J_MCP_RUN_INTEGRATION=1 uv run --project mcp-neo4j-ingest \
  python -m unittest discover -s tests/integration -v
```

Run it only against a disposable database. It is opt-in and is not part of the
pull-request gate until CI has an isolated Neo4j service.
