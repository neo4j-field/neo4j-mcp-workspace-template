# Post-processing Tools

## assign_section_hierarchy

Use an LLM to assign proper heading levels to sections, rebuild `HAS_SUBSECTION` relationships, and propagate heading chains to chunks.

Fixes Docling's flat `level=1` sections. After running:

- `Section.level` values reflect the real document hierarchy
- `HAS_SUBSECTION` relationships link parent to child sections
- Active `Chunk.sectionContext` contains the full heading chain (e.g., `"Chapter 1 > Section 1.1 > Sub 1.1.1"`)

### Modes

- **LLM mode** (default): Automatically infers hierarchy using the configured LLM model with medium reasoning effort
- **Agent mode**: Pass a `hierarchy` JSON to apply levels directly (no LLM call). If the LLM call fails (no API key, network error), returns sections for the agent to decide

### Parameters

| Name | Required | Default | Description |
|------|----------|---------|-------------|
| `document_id` | Yes | - | Document version id to process |
| `model` | No | env `EXTRACTION_MODEL` | LLM model to use |
| `hierarchy` | No | `null` | Agent-provided hierarchy as JSON string (see below) |

### Hierarchy JSON Format

```json
[
  {"id": "doc_v1_sec_0", "level": 1},
  {"id": "doc_v1_sec_1", "level": 2},
  {"id": "doc_v1_sec_2", "level": 2}
]
```

### Example Output (LLM mode)

```json
{
  "status": "success",
  "sections_updated": 12,
  "subsection_relationships_created": 8,
  "chunks_updated": 47,
  "message": "Section hierarchy assigned for document 'Production of Chimeric Antibodies'."
}
```

### Example Output (Agent fallback)

```json
{
  "status": "needs_agent_input",
  "needs_agent_input": true,
  "sections": [
    {"id": "doc_v1_sec_0", "title": "Abstract", "current_level": 1},
    {"id": "doc_v1_sec_1", "title": "Introduction", "current_level": 1}
  ],
  "message": "LLM call failed. Please provide the hierarchy JSON."
}
```

---

## generate_chunk_descriptions

Generate text descriptions for image/table chunks using a Vision Language Model (VLM).

Works with all parse modes:

- **Docling**: Image/table chunks have `imageBase64` directly
- **PyMuPDF**: Chunks link to Image/Table nodes via `HAS_ELEMENT`. The Image/Table nodes receive the `:Chunk` label, `documentName`, and `active` properties
- **Page-image**: Page nodes receive `textDescription` from VLM analysis of the page image + extracted text

After running:

- `textDescription` stores the VLM-generated description
- `text` is **NOT** modified (stays as original extracted content)

### Parameters

| Name | Required | Default | Description |
|------|----------|---------|-------------|
| `document_id` | Yes | - | Document version id to process |
| `model` | No | env `EXTRACTION_MODEL` | VLM model (must support vision) |
| `parallel` | No | `5` | Max concurrent VLM calls |

### Example Output

```json
{
  "status": "success",
  "descriptions_generated": 8,
  "message": "Generated 8 text descriptions for visual chunks."
}
```
