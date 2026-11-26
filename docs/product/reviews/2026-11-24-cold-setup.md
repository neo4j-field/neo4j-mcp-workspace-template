# Cold dependency setup measurement — 2026-11-24

## Scope and isolation

This is a pristine **working-tree source export**, not a clean Git clone of a final
release commit: the root has uncommitted combined implementation changes on base
`5ab261337624a0c90f1de67af6f9c15ca2a29871`. The export copied 223 meaningful source
files, excluding user `.env`, generated client configuration, data, outputs,
`.venv`, caches and the existing nested GraphRAG checkout. Setup performed a real
new GraphRAG clone at its exported revision resource:
`d575b0cb94fb4484272cbd23700640321bef6668`.

Both attempts used separate empty `UV_CACHE_DIR` and Python installation directories,
new project virtual environments, synthetic credentials and no provider requests.
The synthetic Neo4j URI was `bolt://127.0.0.1:1`; this verifies setup/import/config
creation, not database connectivity or authentication. All generated configuration
stayed inside disposable `/private/tmp` workspaces. No actual user credential or
client configuration was read or changed by the harness.

Host: macOS 26.7.3, arm64. uv reused installed CPython 3.11.15 for ingest/lexical/entity
and CPython 3.12.15 for GraphRAG. Interpreter/uv/toolbox installation, OS caches and
Git transport caches are therefore outside this dependency-cold measurement.
Docling first-use model assets are measured separately by the parent live run;
these dependency numbers must not be advertised as total cold time to parse.

## Attempts

The first attempt installed all four environments successfully using explicit
`UV_LINK_MODE=copy`: ingest 5s, lexical with mandatory Docling 28s, entity 8s,
GraphRAG 13s. Total elapsed time was 58.256s, **exit 1**. The host has optional Google
MCP Toolbox installed; the harness supplied EOF, so setup stopped at its BigQuery
prompt. This was not a successful full setup and is not the headline timing.
No dependency or setup source fix was needed: the repeated standard-mode harness
supplies an explicit blank line to skip that optional prompt.

## Successful standard-mode setup

A second independent export/environment/cache used uv's **default linking mode**
and an explicit blank response to the optional BigQuery prompt. Actual `setup.sh`
completed **exit 0 in 27.067s**, including the fresh pinned GraphRAG clone, all four
syncs, ingest import verification and configuration generation.

| Dependency sync | Whole seconds reported | Initial project environment |
|---|---:|---|
| Ingest | 4s | absent |
| Lexical graph, including mandatory Docling | 16s | absent |
| Entity graph | 2s | absent |
| GraphRAG | 3s | absent |

uv version: 0.11.19 (aarch64-apple-darwin). Timings are one observation on this host
and connection, not a promised first-install time. Each attempt had an empty uv
cache and absent project environments, but host/OS/network-side caching was not
flushed. Shared dependencies may be reused between servers within a single setup,
which matches normal setup behavior.

`du -sk` after the successful run reported:

| Location | Reported KiB |
|---|---:|
| Isolated uv cache | 1,322,344 |
| Ingest virtual environment | 142,796 |
| Lexical + Docling virtual environment | 1,048,720 |
| Entity virtual environment | 241,840 |
| GraphRAG virtual environment | 238,412 |

The empty-cache growth was approximately **1.26 GiB** and lexical environment
approximately **1.00 GiB**, as reported by `du`. These are local allocated-size
observations, **not measured network-download bytes**, and APFS shared extents mean
summing cache/environment sizes does not prove exclusive physical consumption.
No packet/transport byte counter was collected; compressed download size remains
unmeasured. No parser asset directories were created during setup.

Verification: the pinned GraphRAG checkout resolved to the exact resource SHA;
all seven generated client configuration files were present; all five JSON
configuration files parsed successfully. The ingest import check passed as part
of setup. Docling 2.152.0 and `docling.document_converter.DocumentConverter` imported successfully from the newly installed lexical environment.

Disposable raw evidence:
`/private/tmp/neo4j-cold-default-s2ydk6bm/{export.json,setup-result.json,setup.log}`.
The first attempt is retained separately at
`/private/tmp/neo4j-cold-setup-r90cnjds/`.

## Actual clean Git clone of the updated combined source

After the lexical fixes and GraphRAG probe-notification fix, a second verification
used the **current** combined working-tree source, including meaningful untracked
modules, tests, setup helpers and the shared revision resource. It was exported to
a disposable directory, initialized as a Git repository and committed there with
an explicit fixture author. Nothing was committed in the user's repository.
`git add` respected the exported `.gitignore`; no `.env`, generated configuration,
cache, environment or existing GraphRAG clone entered that snapshot.

A real `git clone --no-local` of that disposable repository created a new empty
checkout. Its status was clean before synthetic fixture configuration was added,
and all four project environments were absent. Required newly added source/test
files were explicitly verified as tracked in the clone.

- Disposable source snapshot and clone SHA:
  `010c3dbcbe18ca6652899423f0b3b4595086200c`.
- Root source base remains `5ab261337624a0c90f1de67af6f9c15ca2a29871`, with current
  uncommitted fixes included in the disposable snapshot.
- Setup freshly cloned GraphRAG from GitHub at the updated exact resource SHA
  `e096736059d7dfa0182b49ba07297cf83898d7be`.
- This run **reused the earlier isolated uv dependency cache** deliberately. It is
  a **warm-cache clean Git clone check**, not another cold download measurement.
- Actual `setup.sh` completed **exit 0 in 7.029s**. Reported syncs: ingest 1s,
  lexical + Docling 2s, entity 0s, GraphRAG 1s; `0s` means below the whole-second
  timer resolution. The optional BigQuery prompt received a blank response.
- All seven generated client configurations parsed successfully: five JSON and
  two TOML. Ingest's actual import check passed. `git diff --name-only` in the
  clone remained empty after setup: no tracked source/lock changes were needed.

| Installed component | Version | Python |
|---|---|---|
| Ingest | 0.1.0 | 3.11.15 |
| Lexical graph | 0.2.1 | 3.11.15 |
| Docling | 2.152.0 | 3.11.15 |
| Entity graph | 0.4.1 | 3.11.15 |
| GraphRAG | 0.4.2 | 3.12.15 |

Raw evidence is retained at
`/private/tmp/neo4j-clean-git-setup-mlo0b9mj/`: `snapshot.json`, `setup-result.json`,
`versions-and-configs.json` and `setup.log`. This establishes that the updated
combined source can set up from an actual clean local Git clone. It is not a claim
that this disposable snapshot is the final published workspace revision.

## Remaining limits

- A true clean Git clone of the final committed/published release still needs its
  final-revision check; this measurement includes uncommitted working-tree source.
- No database authentication/query, provider call, extraction or first answer was
  tested here. First-use Docling model downloads and live POC timings are separate.
- Windows/Linux, uv/Python bootstrap and exact network transfer bytes are not
  covered. No `--minimal` implementation follows automatically from one timing.

