# MCP Neo4j Entity Graph Server

[![PyPI version](https://badge.fury.io/py/mcp-neo4j-entity-graph.svg)](https://pypi.org/project/mcp-neo4j-entity-graph/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

MCP server for extracting entities from graph nodes and creating entity graphs in Neo4j.

**Supports 100+ LLM providers via LiteLLM** (OpenAI, Anthropic, Google, Azure, Bedrock, Ollama, etc.)

## Installation

```bash
# Using pip
pip install mcp-neo4j-entity-graph

# Using uv (recommended)
uv pip install mcp-neo4j-entity-graph
```

## Features

- **Multi-provider LLM support**: Use any LLM via LiteLLM (OpenAI, Claude, Gemini, etc.)
- **Structured output**: Uses JSON schema for reliable entity extraction
- **Direct graph creation**: Entities created directly in Neo4j (no intermediate files)
- **Schema-driven**: Define what entities/relationships to extract
- **Provenance tracking**: EXTRACTED_FROM relationships link entities to source nodes
- **High parallelism**: Default 20 concurrent extractions (configurable)
- **Batched writes**: Optimized Neo4j writes (batch every 10 chunks by default)
- **Incremental**: Only processes nodes without prior extraction (unless force=true)
- **Key normalization**: Entity keys are normalized (lowercase) for better matching

## Supported Models

Models must support structured output (JSON schema). Tested models include:

| Provider | Models |
|----------|--------|
| **OpenAI** | `gpt-5`, `gpt-5-mini`, `gpt-5-nano`, `gpt-4o`, `gpt-4o-mini` |
| **Anthropic** | `claude-sonnet-4-20250514`, `claude-3-5-sonnet-20241022` |
| **Google** | `gemini/gemini-2.5-pro`, `gemini/gemini-2.5-flash`, `gemini/gemini-1.5-pro` |
| **Azure OpenAI** | `azure/gpt-4o`, `azure/gpt-4o-mini` |
| **AWS Bedrock** | `bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0` |

> **Note**: If a model doesn't support structured output, you'll get a clear error message with suggestions.

## Tools

### `extract_entities_from_graph`

Extracts entities from source nodes and creates entity graph directly in Neo4j.

**Parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `schema_json` | required | Path to JSON schema file or inline JSON string |
| `source_label` | "Chunk" | Label of source nodes to extract from |
| `source_text_property` | "text" | Property containing text to extract from |
| `force` | false | If true, reprocess all nodes |
| `parallel` | 20 | Concurrent extractions (reduce to 5-10 if hitting rate limits) |
| `batch_size` | 10 | Chunks to batch before writing to Neo4j |
| `model` | env var | LLM model to use (from EXTRACTION_MODEL env) |

**Workflow:**
1. Queries all nodes with the specified label: `MATCH (n:{source_label}) WHERE NOT (n)<-[:EXTRACTED_FROM]-()`
2. Extracts entities using LLM with structured output (parallel)
3. Batches results and writes to Neo4j (optimized transactions)
4. Creates EXTRACTED_FROM relationships for provenance

**Examples:**

```python
# Extract from Chunk nodes with default model
extract_entities_from_graph(schema_json="/path/to/schema.json")

# Use a specific model
extract_entities_from_graph(
    schema_json="/path/to/schema.json",
    model="claude-sonnet-4-20250514"
)

# Reduce parallelism if hitting rate limits
extract_entities_from_graph(
    schema_json="/path/to/schema.json",
    parallel=5
)

# Extract from Page nodes
extract_entities_from_graph(
    schema_json="/path/to/schema.json",
    source_label="Page",
    source_text_property="content"
)

# Force re-extraction of all nodes
extract_entities_from_graph(schema_json="/path/to/schema.json", force=True)
```

### `convert_schema`

Converts data model output from the Data Modeling MCP to extraction schema format.

**Parameters:**
- `modeling_output`: JSON output from the Data Modeling MCP server
- `output_path`: Path to save the extraction schema JSON file

**Outputs:**
- `{output_path}` - Extraction schema JSON
- `{output_path}.py` - Generated Pydantic model with normalization validators

## Schema Format

```json
{
  "entity_types": [
    {
      "label": "Medication",
      "description": "A pharmaceutical drug or medication",
      "key_property": "name",
      "properties": [
        {"name": "medicationClass", "type": "STRING", "description": "Drug class"}
      ]
    }
  ],
  "relationship_types": [
    {
      "type": "TREATS",
      "description": "Drug treats a condition",
      "source_entity": "Medication",
      "target_entity": "MedicalCondition"
    }
  ]
}
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `NEO4J_URI` | bolt://localhost:7687 | Neo4j connection URI |
| `NEO4J_USERNAME` | neo4j | Neo4j username |
| `NEO4J_PASSWORD` | (required) | Neo4j password |
| `NEO4J_DATABASE` | neo4j | Neo4j database name |
| `EXTRACTION_MODEL` | gpt-5-mini | Default LLM model for extraction |
| `OPENAI_API_KEY` | - | Required for OpenAI models |
| `ANTHROPIC_API_KEY` | - | Required for Anthropic models |
| `GEMINI_API_KEY` | - | Required for Google Gemini models |

## LLM Provider Configuration

LiteLLM supports 100+ providers. Set the appropriate API key for your provider:

### OpenAI (default)
```bash
export OPENAI_API_KEY="sk-..."
export EXTRACTION_MODEL="gpt-5-mini"  # or gpt-4o-mini, gpt-4o
```

### Anthropic Claude
```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export EXTRACTION_MODEL="claude-sonnet-4-20250514"
```

### Google Gemini
```bash
export GEMINI_API_KEY="..."
export EXTRACTION_MODEL="gemini/gemini-2.5-pro"
```

### Azure OpenAI
```bash
export AZURE_API_KEY="..."
export AZURE_API_BASE="https://your-resource.openai.azure.com/"
export AZURE_API_VERSION="2024-02-15-preview"
export EXTRACTION_MODEL="azure/your-deployment-name"
```

### AWS Bedrock
```bash
export AWS_ACCESS_KEY_ID="..."
export AWS_SECRET_ACCESS_KEY="..."
export AWS_REGION_NAME="us-east-1"
export EXTRACTION_MODEL="bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0"
```

### Local Models (Ollama)
```bash
export EXTRACTION_MODEL="ollama/llama3.1"
# Note: Local models may not support structured output
```

> See [LiteLLM docs](https://docs.litellm.ai/docs/providers) for all providers.

## Usage with Cursor

Add to your `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "neo4j-entity-graph": {
      "command": "uvx",
      "args": ["mcp-neo4j-entity-graph"],
      "env": {
        "NEO4J_URI": "bolt://localhost:7687",
        "NEO4J_USERNAME": "neo4j",
        "NEO4J_PASSWORD": "your-password",
        "OPENAI_API_KEY": "your-api-key",
        "EXTRACTION_MODEL": "gpt-5-mini"
      }
    }
  }
}
```

> **Note**: `uvx` automatically downloads and runs the package from PyPI. No local installation needed!

## Rate Limits & Performance

### Parallelism

The default parallelism is **20** concurrent extractions, optimized for fast processing. However, this may exceed rate limits for some providers.

**If you see rate limit errors**, reduce the `parallel` parameter:

```python
# For rate-limited accounts
extract_entities_from_graph(
    schema_json="/path/to/schema.json",
    parallel=5  # Reduce from default 20
)
```

### Batch Size

Extractions are batched before writing to Neo4j (default: 10 chunks per batch). This reduces Neo4j transactions while maintaining progress visibility.

```python
# Larger batches for better Neo4j performance
extract_entities_from_graph(
    schema_json="/path/to/schema.json",
    batch_size=20
)
```

## Usage Example

```python
# 1. Convert schema from Data Modeling MCP
convert_schema(
    modeling_output='{"nodes": [...], "relationships": [...]}',
    output_path="/path/to/schema.json"
)
# Creates: schema.json + schema.py (Pydantic model)

# 2. Extract entities from all Chunk nodes
extract_entities_from_graph(
    schema_json="/path/to/schema.json"
)
# Default: parallel=20, batch_size=10, model=gpt-5-mini

# 3. Use a different model
extract_entities_from_graph(
    schema_json="/path/to/schema.json",
    model="claude-sonnet-4-20250514",
    parallel=10  # Claude may have stricter rate limits
)
```

## Graph Schema

After extraction, your Neo4j database will contain:

```
(:Entity)-[:EXTRACTED_FROM]->(:Chunk)
(:Entity)-[relationship]->(:Entity)
```

Example query to explore extracted entities:

```cypher
// Find all entities extracted from a document
MATCH (e)-[:EXTRACTED_FROM]->(c:Chunk)-[:PART_OF]->(d:Document {name: "my-document"})
RETURN labels(e)[0] as type, count(e) as count
ORDER BY count DESC
```
