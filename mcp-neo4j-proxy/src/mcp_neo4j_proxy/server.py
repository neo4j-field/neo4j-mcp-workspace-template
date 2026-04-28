import os
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.client.transports import StdioTransport
from fastmcp.server import create_proxy

# In the workspace, server.py lives at mcp-neo4j-proxy/src/mcp_neo4j_proxy/server.py
# — 4 parents up reaches the workspace root where all sibling server dirs live.
# For MCPB bundling, override by setting NEO4J_WORKSPACE_ROOT to the bundle root.
_default_root = Path(__file__).resolve().parent.parent.parent.parent
WORKSPACE_ROOT = Path(os.environ.get("NEO4J_WORKSPACE_ROOT", _default_root))

app = FastMCP("neo4j-workspace")

# neo4j-data-modeling (published package, stateless — no credentials needed)
# export_to_pydantic_models is hidden: its output dialect is incompatible with
# extract_entities. Use neo4j-entity-graph:convert_schema instead.
app.mount(
    create_proxy(
        StdioTransport(
            command="uvx",
            args=["mcp-neo4j-data-modeling@0.8.2", "--transport", "stdio"],
        ),
        name="neo4j-data-modeling",
    ),
    tool_names={"export_to_pydantic_models": "_export_to_pydantic_models"},
)

# neo4j-ingest — structured CSV ingestion
app.mount(
    create_proxy(
        StdioTransport(
            command="uv",
            args=["--directory", str(WORKSPACE_ROOT / "mcp-neo4j-ingest"), "run", "mcp-neo4j-ingest"],
        ),
        name="neo4j-ingest",
    )
)

# neo4j-lexical-graph — PDF → chunk graph with embeddings
app.mount(
    create_proxy(
        StdioTransport(
            command="uv",
            args=["--directory", str(WORKSPACE_ROOT / "mcp-neo4j-lexical-graph"), "run", "mcp-neo4j-lexical-graph"],
        ),
        name="neo4j-lexical-graph",
    )
)

# neo4j-entity-graph — LLM entity extraction from chunk nodes
app.mount(
    create_proxy(
        StdioTransport(
            command="uv",
            args=["--directory", str(WORKSPACE_ROOT / "mcp-neo4j-entity-graph"), "run", "mcp-neo4j-entity-graph"],
        ),
        name="neo4j-entity-graph",
    )
)

# neo4j-graphrag — vector/fulltext/Cypher retrieval
app.mount(
    create_proxy(
        StdioTransport(
            command="uv",
            args=["--directory", str(WORKSPACE_ROOT / "mcp-neo4j-graphrag"), "run", "mcp-neo4j-graphrag"],
        ),
        name="neo4j-graphrag",
    )
)


def main():
    app.run()
