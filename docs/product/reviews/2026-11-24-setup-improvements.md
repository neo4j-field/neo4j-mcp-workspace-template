# Setup baseline and dependency timing — 2026-11-24

## SETUP-003: implemented

The standard setup now syncs lexical-graph exactly once with `--extra docling`.
The optional Docling question and optional-dependency `.env` append are removed.
An existing `INSTALL_DOCLING=false` value is ignored without modifying the user's
file. Manual setup instructions include the same extra. Documentation explains
that PDF/ML dependencies can require substantial downloads and first use may fetch
model assets; fixed download-size/time promises were removed.

Dependency functions live in `scripts/setup-dependencies.sh`, sourced by setup.sh.
They can be exercised without touching credentials or client configuration.

## SETUP-004: instrumentation and warm measurements complete; broader task open

Each dependency sync reports elapsed whole seconds, its actual uv failure status,
and whether the project `.venv` directory existed before the sync. The final
summary repeats per-server sync timings. Directory presence is intentionally not
called a warm/cold cache: it does not prove what uv can reuse, and custom uv
project-environment settings can select a different environment. The timer is
coarse; `0s` denotes a sub-second result. Import verification remains separate
from dependency-sync time.

### Safe local measurement

Host: Darwin arm64, Python 3.13.13, uv 0.11.19. Every project already had `.venv`.
First, `uv sync --directory SERVER --frozen --offline --dry-run --cache-dir TEMP`
confirmed “Would make no changes” for all four projects (lexical also used
`--extra docling`). A temporary cache avoided the sandbox-protected global cache.
Then the corresponding actual frozen/offline sync ran twice, using Python's
monotonic timer around the complete uv subprocess. Both samples exited 0 and
reported only package audits; no packages were installed or removed.

| Server | Audited packages | No-change sync sample 1 | Sample 2 |
|---|---:|---:|---:|
| ingest | 91 | 0.030 s | 0.030 s |
| lexical-graph with Docling | 172 | 0.041 s | 0.042 s |
| entity-graph | 111 | 0.035 s | 0.033 s |
| graphrag | 115 | 0.034 s | 0.033 s |

These are warm existing-environment audit costs, not cold install or download
measurements. Temporary cache state was controlled, but no artifact download was
needed. Graphrag emitted an existing `tool.uv.dev-dependencies` deprecation warning;
its dependency metadata was not changed in this slice.

### Ingest dependency inspection

The installed ingest environment contains 91 distributions on this host. Largest
listed installed-file totals included pandas 3.0.1 (36.9 MiB), cryptography 46.0.5
(20.5 MiB), and numpy 2.4.2 (18.6 MiB). These sums use distribution metadata file
lists; they are not download sizes or exclusive physical disk usage, and exclude
unlisted cache/bytecode files. They must not be compared directly with the older
103-package observation as evidence of a reduction.

All five declared ingest dependencies are used directly: FastMCP tool transforms,
Neo4j driver, dotenv configuration, pandas CSV loading/type inference, and the
wrapped mcp-neo4j-cypher server/write tool. Dropping pandas/numpy requires a CSV
semantics/streaming change; dropping the Cypher package would require replacing
its server/safety behavior. No dependency was removed speculatively, and no server
pyproject/lock file was modified by this setup track.

Remaining SETUP-004 work: a reproducible cold installation/download-size benchmark
per supported platform, then measured dependency reductions coordinated with the
CSV streaming and Cypher safety design. Do not mark SETUP-004 fully done.

## Verification

- `python3 -m unittest tests.unit.test_setup_dependencies -q`: 4 passed.
- Fixture setup tests execute copied setup.sh in temporary workspaces with fake
  uv, dummy fixture credentials, no stdin and isolated PATH. They verify mandatory
  Docling with and without the old flag, unchanged fixture `.env`, generated
  fixture config, timing output, missing-directory skips, and failure status/flags.
- `bash -n setup.sh scripts/setup-dependencies.sh` passed.
- `git diff --check` passed.
- No real `.env`, generated MCP config, credentials or graph data was changed.
- No interactive setup ran against the real workspace, and no workspace-root
  `uv sync` was run.

## SETUP-001 / SETUP-002 follow-up

Implemented safe dotenv loading and an optional bounded extraction-model probe.
Setup now uses umask 077, exclusive 0600 dotenv creation, and chmod 600 for an
existing dotenv. Credentials serialize as quoted literal values; no dotenv line
is sourced/evaluated by a shell. The standalone parser supports comments,
optional `export`, single/double quotes, multiline values and UTF-8 BOM. Dollar
and backtick text is literal; variable interpolation is intentionally unsupported.
Only application/provider environment prefixes and documented optional settings
are exported, preventing control-variable injection through PATH, WORKSPACE_DIR,
BASH_ENV or CHECK_MODEL. Python 3 is an explicit setup prerequisite.

`./setup.sh --check-model` runs one small text structured-output request after
dependency installation and before any config generation or ingestion. It reuses
`build_llm_params`, the configured EXTRACTION_MODEL and provider environment,
strictly validates a tiny Pydantic response, sets a 30-second provider timeout and
35-second outer bound, and disables retries. Error messages expose categories and
recovery steps rather than raw provider exception bodies. The default setup
prints this opt-in command and remains provider-free. This probe does not claim
vision, embeddings or semantic extraction-quality validation.

Verification: 4 dotenv security/roundtrip tests, 4 dependency setup tests (including
full temporary-workspace setup, 0600 preservation and preflight failure before
config generation), 7 GraphRAG setup tests, and 3 mocked request-boundary model
preflight tests passed. Shell syntax and Python compilation passed. Tests used
only temporary synthetic credentials; no real .env or generated configuration was
changed and no live provider call was made by this setup track.

Parent acceptance: the standalone model preflight passed one real request with the configured provider/model, without running setup or changing configuration.
