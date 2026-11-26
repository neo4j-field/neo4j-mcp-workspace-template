# Required search indexes and current Neo4j alignment

WRITE-003 fixed. `embed_chunks(create_fulltext_index=true)` consumes DDL results,
verifies the named index's node label/properties/entity type and reports its actual
ONLINE/POPULATING state. Missing, incompatible and FAILED indexes raise a tool
error. Errors are no longer warnings followed by success. Fulltext checks occur
before provider calls and also run when all embeddings are cached, allowing index
repair without paying to regenerate vectors. No index is dropped automatically.

Schema DDL consumption was also checked for lexical constraints and Ontology DB
setup. Exceptions propagate rather than allowing an unconsumed driver result to
hide a schema failure. Existing vector creation fallback and identity/dimension
checks remain; unsupported filtered vector creation falls back to a plain index.

The current official manuals prefer SEARCH for vector queries from Neo4j 2026.01
and fulltext queries from 2026.09. GraphRAG now selects that syntax by server version,
retaining procedures for older servers. This is deliberate compatibility, not an
error-triggered fallback that could hide authentication/query failures. Index
identifiers and caller-selected property names are escaped; values remain parameters.
Vector filters use in-index SEARCH predicates when all requested properties are
indexed; other cases retain documented post-filtering and overfetching (which can
return fewer than top_k). Retrieval refuses non-ONLINE indexes before embedding.
Node and relationship fulltext search, projection and Lucene query semantics remain.

Both index types expose population state; POPULATING is not reported as query-ready.
The existing cosine/FLOAT32 defaults remain. This does not add hybrid rank fusion,
change analyzers, or tune HNSW/quantization without a workload measurement.

Sources checked 2026-11-24:

- [Search indexes](https://neo4j.com/docs/cypher-manual/current/indexes/search-indexes/)
- [Vector indexes](https://neo4j.com/docs/cypher-manual/current/indexes/search-indexes/vector-indexes/)
- [Fulltext indexes](https://neo4j.com/docs/cypher-manual/current/indexes/search-indexes/full-text-indexes/)
- [SEARCH syntax](https://neo4j.com/docs/cypher-manual/current/clauses/search/)

Verification: 9 lexical vector/fulltext unit checks passed; real Neo4j 2026.09
public-tool conflict failure occurred before provider calls, then dropping only the
fixture's wrong fulltext index let a cached-vector call repair it without provider
work. Public GraphRAG vector/node-fulltext/relationship-fulltext tests passed on
2026.09 and 5.26. Current-server tests also exercise indexed filtering. Unit version
boundaries cover 5.26, 2025.12, 2026.01, 2026.08 and 2026.09. Hosted unit and both integration matrix jobs passed on the new commit; CodeQL check and Actions analysis also passed. The root workspace final release revision still needs its separate delivery check.

Final local GraphRAG evidence: 28 unit checks and all 12 integrations passed on each of Neo4j 5.26 and 2026.09. Source delivery commit: `cd755ebfc7fb28afa153b156595aea693eaa86af`; the workspace source/proxy share this immutable pin.

The configured real-provider model preflight also passed its one structured-output request. No real database or generated config was changed.

Both dedicated disposable Neo4j containers were removed after tests. The configured user database, actual .env and generated client configs were untouched.
