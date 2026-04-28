from fastmcp import FastMCP
from fastmcp.client.transports import StdioTransport
from fastmcp.server import create_proxy

app = FastMCP("neo4j-workspace")

# neo4j-data-modeling (stateless — no credentials needed)
# export_to_pydantic_models hidden: incompatible Pydantic dialect with extract_entities.
# Use neo4j-entity-graph:convert_schema instead.
app.mount(
    create_proxy(
        StdioTransport(command="uvx", args=["mcp-neo4j-data-modeling@0.8.2", "--transport", "stdio"]),
        name="neo4j-data-modeling",
    ),
    tool_names={"export_to_pydantic_models": "_export_to_pydantic_models"},
)

app.mount(create_proxy(
    StdioTransport(command="uvx", args=["mcp-neo4j-ingest@0.1.0"]),
    name="neo4j-ingest",
))

app.mount(create_proxy(
    StdioTransport(command="uvx", args=["mcp-neo4j-lexical-graph@0.2.0"]),
    name="neo4j-lexical-graph",
))

app.mount(create_proxy(
    StdioTransport(command="uvx", args=["mcp-neo4j-entity-graph@0.3.0"]),
    name="neo4j-entity-graph",
))

app.mount(create_proxy(
    StdioTransport(command="uvx", args=["mcp-neo4j-graphrag@0.4.1"]),
    name="neo4j-graphrag",
))


def main():
    app.run()
