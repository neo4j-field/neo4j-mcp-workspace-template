"""Runtime MCP-schema contract for Claude Desktop lexical examples.

Unlike the lightweight AST checks, this test obtains schemas from a live
FastMCP client connected to the maintained lexical server object. It does not
connect to Neo4j or call any provider API.
"""

from __future__ import annotations

import ast
from pathlib import Path
import re
import unittest
from unittest.mock import MagicMock

from fastmcp import Client

from mcp_neo4j_lexical_graph.server import create_mcp_server


REPO_ROOT = Path(__file__).resolve().parents[2]
DESKTOP_SKILL_ROOT = REPO_ROOT / "skills/build-ontology-driven-graph"
LEXICAL_TOOLS = {
    "create_lexical_graph",
    "check_processing_status",
    "cancel_job",
    "list_documents",
    "generate_chunk_descriptions",
    "embed_chunks",
}


def _desktop_skill_corpus() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(DESKTOP_SKILL_ROOT.rglob("*.md"))
    )


def _documented_calls(markdown: str, tool_name: str) -> list[set[str]]:
    calls: list[set[str]] = []
    for match in re.finditer(
        rf"(?<![A-Za-z0-9_]){re.escape(tool_name)}\((.*?)\)",
        markdown,
        flags=re.DOTALL,
    ):
        parsed = ast.parse(f"{tool_name}({match.group(1)})", mode="eval").body
        if not isinstance(parsed, ast.Call):
            raise AssertionError(f"Invalid documented call for {tool_name}")
        calls.append({kw.arg for kw in parsed.keywords if kw.arg is not None})
    return calls


class DesktopLexicalRuntimeContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_documented_calls_validate_against_runtime_mcp_schemas(self) -> None:
        server = create_mcp_server(
            MagicMock(), database="neo4j", process_pool=MagicMock()
        )
        corpus = _desktop_skill_corpus()
        async with Client(server) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}

        for name in LEXICAL_TOOLS:
            with self.subTest(tool=name):
                self.assertIn(name, tools)
                schema = tools[name].inputSchema
                properties = set(schema.get("properties", {}))
                required = set(schema.get("required", []))
                for supplied in _documented_calls(corpus, name):
                    self.assertFalse(
                        supplied - properties,
                        f"{name} documents unsupported arguments",
                    )
                    self.assertFalse(
                        required - supplied,
                        f"{name} omits required arguments",
                    )


if __name__ == "__main__":
    unittest.main()
