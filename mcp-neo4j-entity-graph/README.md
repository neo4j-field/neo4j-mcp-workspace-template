# MCP Neo4j Entity Graph Server

[![PyPI version](https://badge.fury.io/py/mcp-neo4j-entity-graph.svg)](https://pypi.org/project/mcp-neo4j-entity-graph/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

MCP server for extracting entities and relationships from graph nodes using LLM structured output, creating entity graphs directly in Neo4j.

**Supports 100+ LLM providers via LiteLLM** (OpenAI, Anthropic, Google, Azure, Bedrock, Ollama, etc.)

## Features

- **Dual extraction pipeline**: Text-only (LLM) and visual (VLM) extraction auto-routed per chunk
- **Strongly-typed Pydantic models**: Generated from your data model schema with validators
- **Async background processing**: Long extractions run in background with job tracking
- **Multi-provider LLM support**: Use any LLM via LiteLLM (OpenAI, Claude, Gemini, etc.)
- **Schema-driven**: Define entity types and relationships to extract
- **Provenance tracking**: `EXTRACTED_FROM` relationships link entities to source chunks
- **High parallelism**: Configurable concurrency (text: up to 50, VLM: up to 50)
- **Batched writes**: Optimized Neo4j writes (configurable batch size)
- **Incremental**: Only processes nodes without prior extraction (unless `force=true`)
- **Multi-pass ready**: Architecture supports entity-only, relationship-only, and corrective passes (v2)

## Tools

### `convert_schema`

Converts data model output from the Data Modeling MCP to extraction schema + Pydantic models.

**Parameters:**

| Parameter | Required | Description |
|-----------|----------|-------------|
| `modeling_output` | Yes | JSON output from the Data Modeling MCP server |
| `output_path` | Yes | Path to save the extraction schema JSON file |

**Outputs:**
- `{output_path}` - Extraction schema JSON (for Neo4j writes and prompt generation)
- `{output_path}.py` - Strongly-typed Pydantic models (for LLM structured output)

The `.py` file can be customized with domain-specific validators before running extraction.

### `extract_entities`

Extracts entities and relationships from graph nodes using LLM. Returns immediately with a job ID.

The tool auto-detects chunk types and routes accordingly:
- **Text chunks** (`type="text"`): sent to LLM with text only
- **Image/Table chunks** (with `imageBase64`): sent to VLM with text + image
- **Page nodes** (`:Page` label with `imageBase64`): sent to VLM with text + page image

**Parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `schema_json` | required | Path to JSON schema file or inline JSON string |
| `source_label` | `"Chunk"` | Label of source nodes (`Chunk` or `Page`) |
| `pydantic_model_path` | None | Path to generated `.py` file for typed extraction |
| `force` | `false` | Re-extract all nodes (ignore existing `EXTRACTED_FROM`) |
| `text_parallel` | `20` | Max concurrent text extractions |
| `vlm_parallel` | `5` | Max concurrent VLM extractions |
| `batch_size` | `10` | Chunks to batch before writing to Neo4j |
| `model` | env var | LLM model (defaults to `EXTRACTION_MODEL`) |
| `pass_type` | `"full"` | `full`, `entities_only`, `relationships_only`, `corrective` |
| `pass_number` | `1` | Pass number for multi-pass extraction |

### `check_extraction_status`

Monitor background extraction jobs.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `job_id` | None | Specific job to check. If omitted, returns all jobs. |

### `cancel_extraction`

Cancel a running extraction job.

| Parameter | Required | Description |
|-----------|----------|-------------|
| `job_id` | Yes | Job ID to cancel |

## Quick Start

```python
# 1. Convert schema from Data Modeling MCP
convert_schema(
    modeling_output='{"nodes": [...], "relationships": [...]}',
    output_path="data_models/my_schema.json"
)
# Creates: my_schema.json + my_schema.py (Pydantic models)

# 2. Extract entities (runs in background)
extract_entities(
    schema_json="data_models/my_schema.json",
    pydantic_model_path="data_models/my_schema.py"
)
# Returns: {"job_id": "abc123", "status": "started", ...}

# 3. Check progress
check_extraction_status(job_id="abc123")
# Returns: {"status": "extracting", "chunks_completed": 45, ...}
```

## Schema Format

```json
{
  "entity_types": [
    {
      "label": "Drug",
      "description": "A pharmaceutical drug",
      "key_property": "name",
      "properties": [
        {"name": "name", "type": "STRING", "description": "Drug name"},
        {"name": "dose", "type": "STRING", "description": "Dosage"}
      ]
    }
  ],
  "relationship_types": [
    {
      "type": "TREATS",
      "description": "Drug treats a disease",
      "source_entity": "Drug",
      "target_entity": "Disease",
      "properties": []
    }
  ]
}
```

## Generated Pydantic Models

The `convert_schema` tool generates strongly-typed Pydantic models:

```python
class DrugEntity(BaseModel):
    _node_label: ClassVar[str] = "Drug"
    _key_property: ClassVar[str] = "name"

    name: str = Field(..., description="Drug name")
    dose: Optional[str] = Field(default=None, description="Dosage")

    @field_validator("name", mode="before")
    @classmethod
    def _normalize_name(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

class TreatsRel(BaseModel):
    _relationship_type: ClassVar[str] = "TREATS"
    drug_name: str = Field(..., description="Drug name")
    disease_name: str = Field(..., description="Disease name")

class ExtractionOutput(BaseModel):
    drugs: list[DrugEntity] = Field(default_factory=list)
    treats: list[TreatsRel] = Field(default_factory=list)
```

You can add custom validators (normalization, enum constraints, regex patterns) to the generated file before running extraction.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `NEO4J_URI` | `bolt://localhost:7687` | Neo4j connection URI |
| `NEO4J_USERNAME` | `neo4j` | Neo4j username |
| `NEO4J_PASSWORD` | (required) | Neo4j password |
| `NEO4J_DATABASE` | `neo4j` | Neo4j database name |
| `EXTRACTION_MODEL` | `gpt-5-mini` | Default LLM model for extraction |
| `OPENAI_API_KEY` | - | Required for OpenAI models |

## Usage with Cursor

Add to your `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "neo4j-entity-graph": {
      "command": "uv",
      "args": [
        "--directory", "/path/to/mcp-neo4j-entity-graph",
        "run", "mcp-neo4j-entity-graph"
      ],
      "env": {
        "NEO4J_URI": "neo4j://127.0.0.1:7687",
        "NEO4J_USERNAME": "neo4j",
        "NEO4J_PASSWORD": "your-password",
        "OPENAI_API_KEY": "your-api-key",
        "EXTRACTION_MODEL": "gpt-5-mini"
      }
    }
  }
}
```

## Performance

Tested on 5 pharma pipeline PDFs (102 pages) with `gpt-5-mini`:

| Mode | Concurrency | Time | Entities | Relationships |
|------|-------------|------|----------|---------------|
| Text-only | 50 | 107s | 1,584 | 1,257 |
| VLM (page images) | 50 | 114s | 1,597 | 1,378 |

## Architecture

```
server.py          - MCP tools (convert_schema, extract_entities, check/cancel)
job_manager.py     - Async job tracking, progress, cancellation
base_extractor.py  - Shared: prompts, parsing, model loading
text_extractor.py  - Text-only LLM extraction (high parallelism)
vlm_extractor.py   - Vision+text VLM extraction (configurable parallelism)
schema_generator.py - Pydantic model code generation from schemas
models.py          - Internal types (ExtractionSchema, ClassifiedChunk, etc.)
```

## Graph Schema

After extraction, your Neo4j database will contain:

```
(:Entity)-[:EXTRACTED_FROM]->(:Chunk)
(:Entity)-[relationship]->(:Entity)
```

Example query:

```cypher
MATCH (e)-[:EXTRACTED_FROM]->(c:Chunk)-[:PART_OF]->(d:Document {name: "my-doc"})
RETURN labels(e)[0] as type, count(e) as count
ORDER BY count DESC
```
