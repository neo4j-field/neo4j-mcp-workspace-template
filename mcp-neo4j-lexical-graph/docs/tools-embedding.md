# Embedding Tools

## embed_chunks

Add embeddings to active Chunk nodes that don't have them yet. Creates a vector index and optionally a fulltext index.

### Embedding Logic

The tool composes the embedding input text depending on the node type:

| Node type | Embedding input |
|-----------|----------------|
| Text chunk | `documentName + sectionContext + text` |
| Image/Table/Page with `textDescription` | `documentName + sectionContext + textDescription` |
| Image/Table/Page without `textDescription` | **Skipped** |

Uses Neo4j native `VECTOR(list, dims, FLOAT32)` type for storage. Creates a vector index with `documentName` prefilter for efficient filtered search (Cypher 25 syntax).

### Parameters

| Name | Required | Default | Description |
|------|----------|---------|-------------|
| `document_id` | No | `null` | Document ID to embed chunks for. `null` = all active chunks without embeddings |
| `parallel` | No | `10` | Max concurrent embedding batches |
| `model` | No | env `EMBEDDING_MODEL` | Embedding model via [LiteLLM](https://docs.litellm.ai/docs/embedding/supported_embedding) |
| `create_fulltext_index` | No | `true` | Create fulltext index on `Chunk.text` |

### Indexes Created

- **Vector index**: `chunk_text_embedding` on `Chunk.text_embedding` with `documentName` prefilter
- **Fulltext index**: `chunk_text_fulltext` on `Chunk.text` (original extracted content for keyword search)

### Example Output

```json
{
  "status": "success",
  "model": "text-embedding-3-small",
  "embedded": 47,
  "dimensions": 1536,
  "message": "Embedded 47 chunks (VECTOR FLOAT32, 1536d). Vector index with documentName prefilter created."
}
```
