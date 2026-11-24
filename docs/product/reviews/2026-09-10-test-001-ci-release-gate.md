# TEST-001 CI release-gate evidence

Date: 2026-09-10

## Outcome

The repository has one reusable GitHub Actions test suite covering unit and
contract behavior, report validation, representative live Neo4j integrations,
and an exact-DXT headless Desktop ingestion smoke. All four package publication
workflows require that suite to pass before their publish job can run.

## Coverage added

- `.github/workflows/test-contracts.yml` exposes `workflow_call` and runs three
  required jobs: `unit-and-contract`, `neo4j-integration`, and `desktop-smoke`.
- The integration jobs start an isolated Neo4j 5.26 Community service and use
  unique, self-cleaning fixture namespaces.
- The deterministic CI Desktop smoke starts the exact DXT command and reaches
  lexical ingestion without making an embedding-provider request. The existing
  opt-in form still exercises embedding when the skip flag is absent.
- `tests/contracts/test_ci_release_gates.py` checks that the reusable suite
  retains every required coverage class and that every publish workflow depends
  on it.

## Local verification

- Unit, contract, and report-validation tests: 32 passed.
- Live Neo4j integration tests: 7 passed.
- Exact-DXT headless Desktop ingestion smoke: 1 passed.
- All five workflow YAML files parsed successfully.
- Temporary test fixture nodes after cleanup: 0.
- Retained golden graph after cleanup: 5 nodes and 8 relationships, unchanged.

The underlying workflow commands were exercised locally. GitHub-hosted runner
execution remains the normal final validation when the branch is pushed.

## Known separate release issue

The published DXT dependency set still emits a PyMuPDF deprecation warning onto
stdio during startup, although the smoke request succeeds. Package-version
alignment and clean stdio framing remain tracked by `DESK-001`; they do not
weaken the new publication dependency.
