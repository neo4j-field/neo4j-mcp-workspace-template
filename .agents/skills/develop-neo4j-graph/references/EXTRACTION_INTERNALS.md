# Internals: extraction replacement

Read when rebuilding existing output, diagnosing conflicts or handling legacy
provenance. The common flow needs only an agreed key policy, the default
`property_policy="preserve_existing"`, and a stable extraction scope.

Replacement removes only tracked contributions from the explicitly selected
sources in that scope, then publishes new output atomically. Source/model/write
failure leaves prior domain output intact; counters describe extraction attempts
even when no replacement was published. Different scopes coexist.

Missing/null fields withdraw prior owned assertions during replacement; they do
not delete external/structured values. Property proposals and conflicts are
recorded on `EXTRACTED_FROM` for entities and source-linked
`EntityExtractionClaim` records for relationships. Inspect conflicts even when
the extraction succeeds.

If legacy `EXTRACTED_FROM` links lack ownership metadata, use fresh sources with
`source_ids` explicitly selecting their new Chunk/Page IDs, or a separately
reviewed migration. Do not tag old data as owned, clear the database or infer
ownership from labels/ID prefixes. A namespace alone does not isolate domain
nodes with matching labels and merge keys.

For storage mechanics and diagnostics, see
[scoped replacement and ownership](../../../../mcp-neo4j-entity-graph/README.md#scoped-replacement-and-ownership).
