# Develop a Graph Data Model with Neo4j Data Modeling MCP Server

Details the data modeling process with the Neo4j Data Modeling MCP server.

## Graph Data Modeling Process

Primary Instructions:
* Ensure that if you know the source information for Properties, you include it in the data model.
* If you deviate from the user's requests, you must clearly explain why you did so.
* Only use data from the provided sample data to create the data model (Unless explicitly stated otherwise).
* If the user requests use cases that are outside the scope of the provided sample data, you should explain why you cannot create a data model for those use cases.

Process:
1. Analysis
    1a. Analyze the sample data
    1b. Use the `list_example_data_models` tool to check if there are any relevant examples that you can use to guide your data model
    1c. Use the `get_example_data_model` tool to get any relevant example data models
2. Generation
    2a. Generate a new data model based on your analysis, the provided context and any examples
    2b. Use the `get_mermaid_config_str` tool to validate the data model and get a Mermaid visualization configuration
    2c. If necessary, correct any validation errors and repeat step 2b
3. Final Response
    3a. Show the user the visualization with Mermaid, if possible
    3b. Explain the data model and any gaps between the requested use cases
    3c. Request feedback from the user (remember that data modeling is an iterative process)

## Refine Data Model with User Feedback
* Prompt the user to provide any feedback on the graph data model
* Make any necessary changes and repeat step 2

## Final Data Model
* If no changes are necessary, then persist the data model as json in `outputs/data_models/`

---

## Designing the Entity Extraction Sub-Model

When unstructured data (PDFs) is also present, a separate **entity extraction model** must be designed. This is distinct from both the structured data model and the full unified model, and it serves as the schema passed to `extract_entities`.

### What to include in the entity extraction model

The entity extraction model should contain node types that can be meaningfully identified by an LLM from document text. It will typically **partially overlap** with the structured data model — some node labels will appear in both (the bridge nodes), while others will be unique to either the structured graph or the entity graph.

Include a node type if:
- An LLM can reliably identify instances of it from natural language text
- It is relevant to the use cases defined during discovery

Do **not** include node types that require precise structured records to instantiate (e.g. transaction records, event logs, financial claims) — these cannot be reliably inferred from document text.

### Bridge node alignment

Bridge nodes are node labels that exist in **both** the structured data model and the entity extraction model. They are the connection points between the two layers and are merged on a shared key property (typically `name` or a domain identifier).

For each bridge node, note the key property used for MERGE. If the vocabulary is small and known, consider adding an explicit allowed values list to the Pydantic schema field description to reduce LLM name variation.

### Relationship type uniqueness

**All relationship types in the entity extraction model must be unique.** The `convert_schema` tool generates one Python class per relationship type. If two relationships share the same type name (e.g., two different node pairs both connected by `RELATES_TO`), the output will contain a duplicate class name and the schema file will be broken.

To avoid this, either:
- Use distinct relationship type names that encode the node pair (e.g., `A_RELATES_TO_B` and `C_RELATES_TO_B`), or
- Remove the redundant relationship and navigate to it via an intermediate node instead

> **Note on LLM extraction behaviour:** When a relationship type can be extracted from two different start nodes, LLMs tend to only populate one of the two paths — usually the more abstract or categorical one. If precise traversal from a specific start node matters for your queries, verify post-extraction that the expected path is populated before relying on it.

### Using `convert_schema` to generate the Pydantic schema

Use `convert_schema` from the **`neo4j-entity-graph`** server with the **entity extraction model** as input — not the full unified model, and not `export_to_pydantic_models` from the data-modeling server. Pass only the entity extraction nodes and their relationships into `convert_schema`. The resulting Pydantic schema is saved to `outputs/schemas/` and passed directly to `extract_entities`.
