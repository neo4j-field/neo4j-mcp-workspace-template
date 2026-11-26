# Parallel hardening review — 2026-11-24

## Checkpoint and scope

Committed the previously tested ownership/lifecycle pass as `5ab2613` on
`stabilization` before parallel work. Existing FEATURE_CANDIDATES.md and ROADMAP.md
edits were left unstaged and preserved. No branch changes, credential changes or
operations on the configured user graph were needed for this pass.

Three agents implemented separate components; the parent reviewed cross-component
compatibility, registered CI coverage and ran combined regressions.

| Track | Result | Evidence |
|---|---|---|
| EMB-001 | Complete: exact input/provider/model/dimension identity, cache regeneration and atomic vector publication with migration/race guards | [Embedding review](2026-11-24-embedding-identity.md) |
| EXT-004 | Complete for static extraction schema/key contracts; native numeric/bool endpoints, fail-fast validation and safe generated strings | [Schema review](2026-11-24-schema-validation.md) |
| SETUP-003 | Complete: mandatory Docling baseline, including older configuration files | [Setup review](2026-11-24-setup-improvements.md) |
| SETUP-004 | Partial: per-server timing plus measured warm no-change syncs; cold/download benchmarks and justified dependency reduction remain open | [Setup review](2026-11-24-setup-improvements.md) |

Parent review additionally reserved the embedding lock label in entity preflight,
ownership writes and CSV model compilation so a generated domain schema cannot
collide with another component's internal records. Static regressions cover it.

## Combined validation

81 fast tests passed:

- Entity/schema/identity/golden runner: 31.
- Lexical/parser/runtime contracts/embedding identity/vector fallback: 21.
- Setup/workflow/CI/scorer: 17.
- CSV compiler: 6.
- Report validator: 6.

56 isolated database checks passed:

- Combined schema/ownership/completion/bridge/ontology: 35.
- Standalone relationship fixtures: 2.
- Lexical chunk rebuilding and page accounting: 2.
- Structured ingest: 1.
- Embedding identity and original vector fallback: 16, with no skips.

The parent used disposable Docker Neo4j 5.26.33 and 2025.12.1 Enterprise databases
on separate localhost ports. Model/provider paths were stubbed. Hosted GitHub CI
and a rebuilt packaged Desktop smoke were not run in this pass. Shared CI now
includes the new setup, schema and vector integration modules. Shell syntax,
workflow YAML and git diff --check also passed.

Fixture teardown left zero nodes and temporary publication locks. The disposable
containers were stopped/removed. The native vector test database retains its
reserved uniqueness constraint only until container removal. No credentials,
workspace .env or generated MCP config were changed.

## Remaining boundaries

- SETUP-004 is not done: no invented cold-install timing or speculative dependency
  removal. The five direct ingest dependencies are currently used.
- Static schema validation does not introspect existing Neo4j DDL constraints or
  prove arbitrary Python validator behavior.
- Index dimension/model migrations require explicit compatible storage/index work;
  production code does not automatically drop indexes. Schema/empty-index side
  effects may remain after vector publication aborts, as documented in the embedding
  review. A mere additional label on the same physical nodes is not separate storage.
- Opaque remote model aliases, conservative routing-env invalidation, fulltext-index
  migration, memory/queue bounds, release alignment and source/deletion lifecycle
  remain separate work. These passing checks are not a release readiness sign-off.
