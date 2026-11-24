"""Opt-in headless smoke test for the maintained Claude Desktop DXT command.

The test reads the command and arguments from the checked-in DXT manifest, starts
that exact stdio MCP process, validates the documented lexical calls against the
runtime tool schemas, ingests one uniquely named PDF, embeds its chunk, verifies
the canonical property, and removes only the fixture namespace.

Run with::

    NEO4J_MCP_RUN_DESKTOP_SMOKE=1 uv run --env-file .env \
      --project mcp-neo4j-proxy python -m unittest \
      tests.integration.test_desktop_lexical_smoke_mcp -v

CI sets ``NEO4J_MCP_DESKTOP_SMOKE_SKIP_EMBEDDING=1`` so the maintained DXT
surface is exercised through lexical ingestion without requiring a provider
secret.  The default remains the full smoke, including the embedding write and
idempotent retry assertion used by WF-003.
"""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import unittest

from fastmcp import Client
from fastmcp.client.transports import StdioTransport


REPO_ROOT = Path(__file__).resolve().parents[2]
DXT_MANIFEST = REPO_ROOT / "neo4j-mcp-workspace-dxt/manifest.json"
DESKTOP_SKILL_ROOT = REPO_ROOT / "skills/build-ontology-driven-graph"
PDF_FIXTURE = REPO_ROOT / "tests/fixtures/desktop/wf001_wf003_smoke.pdf"
RUN_SMOKE = os.getenv("NEO4J_MCP_RUN_DESKTOP_SMOKE") == "1"
SKIP_EMBEDDING = os.getenv("NEO4J_MCP_DESKTOP_SMOKE_SKIP_EMBEDDING") == "1"
SOURCE_ID = "wf001-wf003-desktop-smoke-20260910"
ID_PREFIX = f"{SOURCE_ID}_v"
TERMINAL_JOB_STATUSES = {"complete", "completed", "failed", "cancelled"}


def _tool_payload(result) -> dict:
    if result.is_error:
        raise AssertionError(str(result))
    return json.loads(result.content[0].text)


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


@unittest.skipUnless(
    RUN_SMOKE,
    "set NEO4J_MCP_RUN_DESKTOP_SMOKE=1 for the live Desktop stdio smoke test",
)
class DesktopLexicalSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        manifest = json.loads(DXT_MANIFEST.read_text(encoding="utf-8"))
        config = manifest["server"]["mcp_config"]
        env = {**os.environ, **{key: os.environ[key] for key in (
            "NEO4J_URI",
            "NEO4J_USERNAME",
            "NEO4J_PASSWORD",
            "NEO4J_DATABASE",
            "OPENAI_API_KEY",
            "EMBEDDING_MODEL",
            "EXTRACTION_MODEL",
        )}}
        self.transport = StdioTransport(
            command=config["command"], args=config["args"], env=env
        )
        self.client = Client(self.transport, timeout=120, init_timeout=120)
        await self.client.__aenter__()
        self.tempdir = Path(tempfile.mkdtemp(prefix="wf001-wf003-desktop-smoke-"))
        self.pdf_dir = self.tempdir / "pdfs"
        self.output_dir = self.tempdir / "output"
        self.pdf_dir.mkdir()
        shutil.copy2(PDF_FIXTURE, self.pdf_dir / f"{SOURCE_ID}.pdf")
        await self._cleanup_fixture()
        self.golden_before = await self._golden_snapshot()

    async def asyncTearDown(self) -> None:
        try:
            await self._cleanup_fixture()
            self.assertEqual(self.golden_before, await self._golden_snapshot())
        finally:
            await self.client.__aexit__(None, None, None)
            shutil.rmtree(self.tempdir, ignore_errors=True)

    async def _call(self, name: str, arguments: dict | None = None) -> dict:
        return _tool_payload(await self.client.call_tool(name, arguments or {}, timeout=180))

    async def _query(self, query: str, params: dict | None = None) -> list[dict]:
        payload = await self._call(
            "documents_read_neo4j_cypher", {"query": query, "params": params or {}}
        )
        return payload if isinstance(payload, list) else payload.get("result", payload)

    async def _write(self, query: str, params: dict | None = None) -> None:
        await self._call(
            "documents_write_neo4j_cypher", {"query": query, "params": params or {}}
        )

    async def _cleanup_fixture(self) -> None:
        await self._write(
            """
            MATCH (n)
            WHERE n.sourceId = $sourceId
               OR coalesce(n.id, '') STARTS WITH $idPrefix
            DETACH DELETE n
            """,
            {"sourceId": SOURCE_ID, "idPrefix": ID_PREFIX},
        )

    async def _golden_snapshot(self) -> list[dict]:
        return await self._query(
            """
            MATCH (n)
            WHERE any(k IN keys(n) WHERE toString(n[k]) CONTAINS $golden)
               OR coalesce(n.id, '') STARTS WITH $golden
               OR coalesce(n.sourceId, '') STARTS WITH $golden
            WITH collect(n) AS nodes
            UNWIND nodes AS n
            OPTIONAL MATCH (n)-[r]-()
            RETURN count(DISTINCT n) AS nodes, count(DISTINCT r) AS relationships
            """,
            {"golden": "golden-e2e-20260910"},
        )

    async def test_documented_desktop_lexical_workflow(self) -> None:
        tools = {tool.name: tool for tool in await self.client.list_tools()}
        documented_tools = {
            "create_lexical_graph",
            "check_processing_status",
            "list_documents",
            "embed_chunks",
        }
        corpus = _desktop_skill_corpus()
        for name in documented_tools:
            with self.subTest(tool=name):
                self.assertIn(name, tools)
                schema = tools[name].inputSchema
                properties = set(schema.get("properties", {}))
                required = set(schema.get("required", []))
                for supplied in _documented_calls(corpus, name):
                    self.assertFalse(supplied - properties)
                    self.assertFalse(required - supplied)

        started = await self._call(
            "create_lexical_graph",
            {
                "path": str(self.pdf_dir),
                "output_dir": str(self.output_dir),
                "parse_mode": "pymupdf",
                "extract_images": False,
                "extract_tables": False,
                "max_parallel": 1,
            },
        )
        self.assertEqual(1, started.get("files_total"))
        job_id = started["job_id"]

        for _ in range(60):
            status = await self._call("check_processing_status", {"job_id": job_id})
            normalized_status = str(status.get("status", "")).lower()
            if normalized_status in TERMINAL_JOB_STATUSES:
                break
            import asyncio

            await asyncio.sleep(1)
        else:
            self.fail(f"Desktop lexical job {job_id} did not finish")
        self.assertIn(normalized_status, {"complete", "completed"}, status)

        if not SKIP_EMBEDDING:
            embedded = await self._call("embed_chunks")
            self.assertEqual("success", embedded.get("status"), embedded)
        rows = await self._query(
            """
            MATCH (c:Chunk)-[:PART_OF]->(d:Document {sourceId: $sourceId})
            RETURN d.totalPages AS sourcePageCount,
                   count(DISTINCT c) AS chunks,
                   count(DISTINCT c.text_embedding) AS embedded,
                   count { (d)-[:HAS_PAGE]->(:Page) } AS pageNodeCount
            """,
            {"sourceId": SOURCE_ID},
        )
        expected_embedded = 0 if SKIP_EMBEDDING else 1
        self.assertEqual(
            [{
                "sourcePageCount": 1,
                "chunks": 1,
                "embedded": expected_embedded,
                "pageNodeCount": 0,
            }],
            rows,
        )

        if not SKIP_EMBEDDING:
            retry_probe = await self._call("embed_chunks")
            self.assertEqual(0, retry_probe.get("embedded"), retry_probe)


if __name__ == "__main__":
    unittest.main()
