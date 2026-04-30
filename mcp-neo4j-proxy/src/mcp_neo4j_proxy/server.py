import os
import re

from fastmcp import FastMCP
from fastmcp.client.transports import StdioTransport
from fastmcp.server import create_proxy

app = FastMCP("neo4j-mcp-workspace")


# Parse EXTRA_ENV (KEY=VALUE pairs) and inject into the process environment
# before any subprocess is spawned. This supports non-OpenAI LiteLLM providers
# (Anthropic, Azure OpenAI, AWS Bedrock, etc.) configured via the DXT installer.
#
# Pairs are separated by whitespace, commas, or semicolons, so users can paste
# into either a single-line input or a multi-line textarea without learning a
# delimiter. KEY must match [A-Z_][A-Z0-9_]* (standard env-var convention);
# VALUE is any run of characters other than whitespace, comma, or semicolon.
_extra_env_raw = os.environ.get("EXTRA_ENV", "").strip()
if _extra_env_raw:
    for _m in re.finditer(r"([A-Z_][A-Z0-9_]*)=([^\s,;]+)", _extra_env_raw):
        os.environ.setdefault(_m.group(1), _m.group(2))


def _docs_env() -> dict[str, str]:
    """Environment for servers that connect to the Documents DB."""
    return {**os.environ, "NEO4J_DATABASE": os.environ.get("NEO4J_DATABASE", "neo4j")}


def _ontology_env() -> dict[str, str]:
    """Environment for the ontology graphrag instance.

    Overrides NEO4J_URI/USERNAME/PASSWORD with ontology-specific credentials
    when NEO4J_ONTOLOGY_URI is set (separate Aura instance). Falls back to
    the Documents DB credentials for single-instance / local setups.
    """
    env = {**os.environ}
    ontology_uri = os.environ.get("NEO4J_ONTOLOGY_URI", "").strip()
    if ontology_uri:
        env["NEO4J_URI"] = ontology_uri
        ontology_username = os.environ.get("NEO4J_ONTOLOGY_USERNAME", "").strip()
        if ontology_username:
            env["NEO4J_USERNAME"] = ontology_username
        ontology_password = os.environ.get("NEO4J_ONTOLOGY_PASSWORD", "").strip()
        if ontology_password:
            env["NEO4J_PASSWORD"] = ontology_password
    env["NEO4J_DATABASE"] = os.environ.get("NEO4J_ONTOLOGY_DATABASE", "neo4j")
    return env


# ── neo4j-data-modeling (stateless — no credentials needed) ──────────────────
#
# Tools hidden by rename to leading-underscore (FastMCP soft filter):
# - export_to_pydantic_models: incompatible Pydantic dialect with extract_entities.
#   Use neo4j-entity-graph:convert_schema or generate_schema_from_ontology instead.
# - export_to_owl_turtle / load_from_owl_turtle: OWL/Turtle out of scope for the lawyer flow.
# - export_to_neo4j_graphrag_pkg_schema / load_from_neo4j_graphrag_pkg_schema:
#   replaced by ontology-driven schema generation.
# - export_to_arrows_json / load_from_arrows_json: Arrows.app roundtrip,
#   not part of the lawyer-facing workflow.
app.mount(
    create_proxy(
        StdioTransport(command="uvx", args=["mcp-neo4j-data-modeling@0.8.2", "--transport", "stdio"]),
        name="neo4j-data-modeling",
    ),
    tool_names={
        "export_to_pydantic_models": "_export_to_pydantic_models",
        "export_to_owl_turtle": "_export_to_owl_turtle",
        "load_from_owl_turtle": "_load_from_owl_turtle",
        "export_to_neo4j_graphrag_pkg_schema": "_export_to_neo4j_graphrag_pkg_schema",
        "load_from_neo4j_graphrag_pkg_schema": "_load_from_neo4j_graphrag_pkg_schema",
        "export_to_arrows_json": "_export_to_arrows_json",
        "load_from_arrows_json": "_load_from_arrows_json",
    },
)

app.mount(create_proxy(
    StdioTransport(command="uvx", args=["mcp-neo4j-ingest@0.1.0"], env={**os.environ}),
    name="neo4j-ingest",
))

app.mount(create_proxy(
    StdioTransport(command="uvx", args=["mcp-neo4j-lexical-graph@0.2.0"], env={**os.environ}),
    name="neo4j-lexical-graph",
))

app.mount(create_proxy(
    StdioTransport(command="uvx", args=["mcp-neo4j-entity-graph@0.4.0"], env={**os.environ}),
    name="neo4j-entity-graph",
))

# Two graphrag instances pointing at different databases.
# namespace= on app.mount() prefixes tool names: e.g. documents_read_neo4j_cypher,
# ontology_read_neo4j_cypher — the agent picks by intent from the tool name.
app.mount(
    create_proxy(
        StdioTransport(
            command="uvx",
            args=["mcp-neo4j-graphrag@0.4.1"],
            env=_docs_env(),
        ),
    ),
    namespace="documents",
)

app.mount(
    create_proxy(
        StdioTransport(
            command="uvx",
            args=["mcp-neo4j-graphrag@0.4.1"],
            env=_ontology_env(),
        ),
    ),
    namespace="ontology",
)


def main():
    app.run()
