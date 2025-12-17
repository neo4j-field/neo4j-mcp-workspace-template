# MCP Neo4j Entity Graph Server

**Status:** POC (Proof of Concept)

MCP server for extracting entities from graph nodes and creating entity graphs in Neo4j.

## Features

- **LLM-based extraction**: Uses OpenAI SDK with structured output (gpt-5-mini recommended)
- **Direct graph creation**: Entities created directly in Neo4j (no intermediate files)
- **Schema-driven**: Define what entities/relationships to extract
- **Provenance tracking**: EXTRACTED_FROM relationships link entities to source nodes
- **Parallelization**: Concurrent extraction for speed
- **Incremental**: Only processes nodes without prior extraction (unless force=true)
- **Key normalization**: Entity keys are normalized (lowercase) for better matching

## Tools

### `extract_entities_from_graph`

Extracts entities from source nodes and creates entity graph directly in Neo4j.

**Parameters:**
- `schema_json`: Path to JSON schema file or inline JSON string
- `source_label`: Label of source nodes (default: "Chunk")
- `source_text_property`: Property containing text (default: "text")
- `force`: If true, reprocess all nodes (default: false)
- `parallel`: Concurrent extractions (default: 5)
- `model`: LLM model to use (default: from EXTRACTION_MODEL env)

**Workflow:**
1. Queries all nodes with the specified label: `MATCH (n:{source_label}) WHERE NOT (n)<-[:EXTRACTED_FROM]-()`
2. LLM extracts entities using structured output (per node)
3. Creates entity nodes + EXTRACTED_FROM relationships immediately after each node
4. Creates relationships between entities

**Examples:**
```python
# Extract from Chunk nodes (default)
extract_entities_from_graph(schema_json="/path/to/schema.json")

# Extract from Page nodes
extract_entities_from_graph(schema_json="/path/to/schema.json", source_label="Page")

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

- `NEO4J_URI`: Neo4j connection URI (default: bolt://localhost:7687)
- `NEO4J_USERNAME`: Neo4j username (default: neo4j)
- `NEO4J_PASSWORD`: Neo4j password
- `NEO4J_DATABASE`: Neo4j database (default: neo4j)
- `OPENAI_API_KEY`: OpenAI API key
- `EXTRACTION_MODEL`: Default extraction model (default: gpt-5-mini)

## Usage with Cursor

Add to your `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "neo4j-entity-graph": {
      "command": "uv",
      "args": ["--directory", "/path/to/mcp-neo4j-entity-graph", "run", "mcp-neo4j-entity-graph"],
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
    schema_json="/path/to/schema.json",
    parallel=5
)

# Or extract from a different node type
extract_entities_from_graph(
    schema_json="/path/to/schema.json",
    source_label="Page",
    source_text_property="content"
)
```
