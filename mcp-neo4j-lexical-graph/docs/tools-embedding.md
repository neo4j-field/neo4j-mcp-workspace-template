# Embedding tools

## embed_chunks

Embed eligible inputs and reuse only verified matching vectors. Creates/verifies the
label's vector index and optionally a fulltext index. The stored vector property is
always `text_embedding`; the index name is `<node_label.lower()>_text_embedding`.

### Input and cache identity

The provider input is the exact Cypher-composed string: ordered `context_properties`
joined with spaces, then the chosen text property, trimmed when context is present.
Missing context contributes an empty string. With a fallback, the first non-null text
property wins. For default Chunk calls, any available `textDescription` enables
`textDescription` with raw `text` fallback. Page/Image/Table labels require a description
property instead of the default raw-text call.

Stored metadata:

| Property | Meaning |
|---|---|
| `embeddingProvider` | LiteLLM-resolved provider |
| `embeddingModel` | Exact configured model identifier |
| `embeddingDimensions` | Actual stored vector dimensions |
| `embeddingInputHash` | SHA-256 of the exact provider input |
| `embeddingSpace` | Hash of provider/model/requested-dimension/routing identity |

Vectors with absent or inconsistent metadata regenerate. Changing an unused raw-text
fallback does not regenerate a vector whose actual description input is unchanged.
The routing identity stores only a hash, never endpoint URLs or credentials.

### Parameters

| Name | Default | Meaning |
|---|---|---|
| `node_label` | `Chunk` | Node label; the property/index is shared across this label |
| `text_property` | `text` | Main text property |
| `text_property_fallback` | `null` | First non-null fallback |
| `context_properties` | `[documentName, sectionContext]` | Ordered input prefix |
| `index_prefilter_properties` | `[documentName, type]` | Index metadata prefilters; plain-index fallback on unsupported servers |
| `document_id` | `null` | Filters **documentName**, not the version node ID |
| `overwrite` | `false` | Force a refresh; otherwise regenerate only stale/unverifiable vectors |
| `include_inactive` | `false` | Include inactive Chunk inputs in a label-wide refresh |
| `parallel` | `10` | Concurrent provider batches, positive |
| `model` | configured `EMBEDDING_MODEL` | Exact LiteLLM model; never substituted |
| `dimensions` | `null` | Optional provider-requested dimension |
| `create_fulltext_index` | `true` | Create the label's resolved text-property fulltext index |

### Safe index boundaries

Every preserved vector in an index must have the same verified embedding space and
dimensions. A document-only model migration fails before provider work when it would
mix spaces with other documents. Refresh the whole indexed label, including inactive
nodes when needed, or use separate physical nodes/storage and indexes. Nodes with old
vectors but no usable input cannot be silently migrated by this tool.

Adding another label to the same nodes does **not** isolate storage: all these calls
write the same `text_embedding` property. Space-changing writes refuse another
same-property index overlapping the selected nodes. Existing dimensions are checked
before publication, including overlapping indexes. An incompatible named index is
never automatically dropped/recreated. A separately reviewed schema migration is
required, or use separate physical storage. Hidden remote alias changes require a
versioned model identifier or explicit whole-label overwrite.

Explicit requested dimension mismatches are rejected without a provider call.
Provider-default dimensions are known from cache or the actual refresh response;
there is no extra billable probe request.

### Publication, permissions, and failures

A reserved uniqueness constraint (`neo4j_mcp_embedding_lock_unique`) is required for
safe per-index publication. Runtime users need `SHOW CONSTRAINT` to verify it. If the
constraint is absent, grant `CREATE CONSTRAINT` or ask an administrator to create it:

```cypher
CREATE CONSTRAINT neo4j_mcp_embedding_lock_unique IF NOT EXISTS
FOR (lock:EmbeddingPublicationLock) REQUIRE lock.indexName IS UNIQUE;
```

On the tested Neo4j 2025.12.1 Enterprise server, a matching precreated constraint lets
a user without `CREATE CONSTRAINT` embed successfully. The user still needs graph
read/write, name and index privileges. A missing creation/inspection privilege fails
before provider requests or vector writes with the required privilege names and
administrator alternative. This describes database-role permissions, not an Aura Free
product restriction.

A temporary lock node serializes writes; its transaction
rechecks current labels, source inputs and preserved vector spaces. Vector data and
metadata commit together, with no temporary lock node left after commit or rollback.
Partial/duplicate/mixed-dimension/non-finite/zero-vector responses are rejected.

Schema work is separate: a uniqueness constraint and an empty vector index may have
been created before a later source-race check fails. No existing index or constraint
is automatically dropped. Valid cached inputs still create/repair a missing index
without re-embedding. Responses report the actual `plain`/`prefiltered` mode and
`ONLINE`/`POPULATING` state. Confirm ONLINE before retrieval if population is pending.
