# Version Management Tools

## list_documents

List all documents in the graph, grouped by sourceId with version info. Shows parse mode, node counts, embedding status, and active flag for each version.

### Parameters

None.

### Example Output

```json
{
  "status": "success",
  "documents": [
    {
      "sourceId": "my-paper",
      "name": "My Paper",
      "source": "/path/to/my-paper.pdf",
      "versions": [
        {
          "id": "my-paper_v1",
          "version": 1,
          "active": false,
          "parseMode": "pymupdf",
          "pages": 13,
          "elements": 0,
          "sections": 0,
          "chunks": 42,
          "hasEmbeddings": true,
          "createdAt": "2026-02-15T10:30:00Z"
        },
        {
          "id": "my-paper_v2",
          "version": 2,
          "active": true,
          "parseMode": "docling",
          "pages": 13,
          "elements": 142,
          "sections": 18,
          "chunks": 47,
          "hasEmbeddings": false,
          "createdAt": "2026-02-16T14:20:00Z"
        }
      ]
    }
  ]
}
```

---

## delete_document

Delete a document version and ALL its children (pages, elements, sections, chunks, TOC entries). Cascading delete.

### Parameters

| Name | Required | Default | Description |
|------|----------|---------|-------------|
| `document_id` | Yes | - | Document version id to delete |

### Example Output

```json
{
  "status": "success",
  "document_id": "my-paper_v1",
  "deleted": {
    "Document": 1,
    "Page": 13,
    "Element": 142,
    "Section": 18,
    "Chunk": 47
  },
  "message": "Deleted document my-paper_v1 and all children."
}
```

---

## set_active_version

Activate a specific document version (deactivates all other versions with the same sourceId). Optionally also activate a specific chunk set version.

### Parameters

| Name | Required | Default | Description |
|------|----------|---------|-------------|
| `document_id` | Yes | - | Document version to activate |
| `chunk_set_version` | No | `null` | If provided, activate this chunk set version for the document |

### Example Output

```json
{
  "status": "success",
  "message": "Activated document version my-paper_v2. Activated chunk set v2 (47 chunks)."
}
```

---

## clean_inactive

Delete inactive document versions and/or inactive chunk sets. Use to reclaim space after testing different parse modes or chunking strategies.

### Parameters

| Name | Required | Default | Description |
|------|----------|---------|-------------|
| `source_id` | No | `null` | Clean inactive document versions for this sourceId. `null` = all sourceIds |
| `document_id` | No | `null` | Clean inactive chunk sets for this document. `null` = all active documents |

When neither parameter is provided, deletes all inactive document versions across the entire graph.

### Example Output

```json
{
  "status": "success",
  "inactive_documents_deleted": 2,
  "nodes_deleted": {
    "Document": 2,
    "Page": 26,
    "Element": 284,
    "Section": 36,
    "Chunk": 94
  }
}
```
