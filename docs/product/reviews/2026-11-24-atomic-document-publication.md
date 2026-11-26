# WRITE-001 — atomic document publication

Status: implemented and verified against isolated Neo4j Enterprise 2026.09.

Previously, ingestion deactivated all earlier document versions before writing the
replacement, and graph batches committed independently. A failed later batch could
leave no active usable version and a visible partial replacement.

Each document graph now writes through one managed Neo4j data transaction. Existing
batch queries share that transaction. Only after every graph write succeeds does
the same transaction switch the source's active document. Commit publishes the
complete graph and active-version change together; failures and cancellation roll
back every new record. The PyMuPDF path includes its built-in chunks. The native
ParsedDocument paths include pages/elements/sections and their relationships.

Schema constraints are created and consumed before the data transaction. PyMuPDF
now also ensures its Document/Chunk/asset uniqueness constraints, making concurrent
same-version writes fail safely and enabling the existing version-retry path.

`set_active_version` switches its document and optional chunk set in one transaction.
It validates the requested chunk set before any activation change. An unknown set
returns an actionable error and preserves both current selections.

## Verification

- Five focused unit checks: graph writes precede activation in the same
  transaction; failed writes never activate; an invalid chunk set never activates;
  commit failures propagate; deferred DDL failures prevent any data transaction.
- Six real database checks in disposable `hardening-atomic`:
  - Failure after an element batch preserves the old active graph, with no new
    document or child records left behind. A separate reader sees only the old
    committed version during the unfinished write.
  - Successful replacement exposes the old version until commit, then exactly
    one complete new active version.
  - Cancelled first ingestion publishes nothing.
  - Invalid manual chunk-set selection preserves current document/chunks; valid
    selection succeeds.
  - Concurrent same-version writers produce one complete committed replacement,
    one uniqueness failure and no duplicate/partial graph.
  - PyMuPDF failure rolls back its replacement and preserves the previous version.
- Eleven retained database regressions passed: pageless graph/chunkers, ownership
  boundaries, navigation metadata, native Docling hierarchy, and public spawned
  MCP workers for all four added formats plus mixed PDF folders.
- The focused combined unit run passed 21 checks including retained routing,
  metadata and pageless flow behavior.

Commands used the lexical server's existing virtualenv and standard unittest
modules `test_document_version_publication`, `test_document_version_publication_mcp`
and the retained lexical integration modules. All fixtures used UUID ownership and
were cleaned after each test. No user database or credentials were modified.

## Scope

Atomic publication covers a document's parsed lexical graph, not the later
multi-tool chunking/embedding/entity-extraction workflow. It introduces no job
ledger or resumability framework. One document is one transaction, which is
appropriate for this SE POC template; extremely large document transactions remain
subject to the configured Neo4j transaction memory limit and fail without replacing
the previous version.

A later combined lexical unit/contract run passed 59 checks including fulltext failure propagation and vector fallback; the two additional commit/DDL propagation tests also passed in the final five-test publication suite.
