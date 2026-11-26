# Lexical deletion and metadata boundaries — 2026-11-24

Completed SEC-001 and WRITE-004 without changing parser or extraction policy.

## Exact document deletion

`delete_document_cascade` now selects lexical descendants through exact ownership
relationships rather than `Element.id STARTS WITH document_id`. Arbitrarily named
owned elements are deleted; unrelated prefix-looking records are retained. Children
also owned by another Document survive, including Page/Section/Chunk element paths.
Deletion never traverses provenance into domain nodes. Existing explicit-delete
behavior detaches provenance pointing to removed lexical sources; generalized
extraction-claim cleanup remains a separate lifecycle concern.

## Metadata boundary

All parser/server/worker and graph-writer paths share metadata normalization and
validation before background work, constraints or writes. Custom keys retain the
existing space/hyphen-to-underscore normalization. Reserved document identity,
lifecycle and embedding properties, internal ownership prefixes and normalized-key
collisions are rejected with actionable errors. Ordinary custom metadata survives.

## Validation

The combined lexical suite passed **35 fast checks**. **6 isolated database checks**
passed: the two new boundary checks plus existing native-hierarchy, navigation
metadata, chunk-rebuild and page-accounting checks. Disposable Neo4j2025.12.1
Enterprise, database `bug-check`, UUID fixtures; no provider calls or user data.

The deletion regression includes prefix neighbors, unowned prefix-looking elements,
shared Page/Section/Chunk contents, differently named owned elements, domain-node
preservation and repeat deletion. Metadata checks cover reserved properties and
normalized collisions on all four modes, early rejection and valid custom fields.
New tests are included in the shared workflow. Root hosted CI on the final release
revision remains part of release delivery.
