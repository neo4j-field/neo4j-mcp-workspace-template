"""Opt-in live LEX-001 regression for source-page and Page-node accounting."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock

from fastmcp import Client
from neo4j import AsyncGraphDatabase

from mcp_neo4j_lexical_graph.server import create_mcp_server


RUN_INTEGRATION = os.getenv("NEO4J_MCP_RUN_INTEGRATION") == "1"
DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")
TEST_RUN_ID = "lex001-live-regression-20260910"
ID_PREFIX = f"{TEST_RUN_ID}-"


@unittest.skipUnless(
    RUN_INTEGRATION,
    "set NEO4J_MCP_RUN_INTEGRATION=1 to run against the configured Neo4j database",
)
class LexicalPageAccountingMCPIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.driver = AsyncGraphDatabase.driver(
            os.environ["NEO4J_URI"],
            auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
        )
        await self._cleanup_fixture()
        self.golden_before = await self._golden_snapshot()
        await self._create_fixture()
        self.server = create_mcp_server(
            self.driver,
            database=DATABASE,
            process_pool=MagicMock(),
        )
        self.client = Client(self.server)
        await self.client.__aenter__()

    async def asyncTearDown(self) -> None:
        await self.client.__aexit__(None, None, None)
        await self._cleanup_fixture()
        self.assertEqual(self.golden_before, await self._golden_snapshot())
        await self.driver.close()

    async def _cleanup_fixture(self) -> None:
        async with self.driver.session(database=DATABASE) as session:
            await session.run(
                """
                MATCH (n)
                WHERE n.testRunId = $testRunId
                   OR coalesce(n.id, '') STARTS WITH $idPrefix
                DETACH DELETE n
                """,
                testRunId=TEST_RUN_ID,
                idPrefix=ID_PREFIX,
            )

    async def _golden_snapshot(self) -> tuple[int, int]:
        async with self.driver.session(database=DATABASE) as session:
            result = await session.run(
                """
                MATCH (n)
                WHERE any(k IN keys(n) WHERE toString(n[k]) CONTAINS 'golden-e2e-20260910')
                   OR coalesce(n.id, '') STARTS WITH 'golden-e2e-20260910'
                   OR coalesce(n.sourceId, '') STARTS WITH 'golden-e2e-20260910'
                WITH collect(n) AS nodes
                UNWIND nodes AS n
                OPTIONAL MATCH (n)-[r]-()
                RETURN count(DISTINCT n) AS nodes,
                       count(DISTINCT r) AS relationships
                """
            )
            record = await result.single(strict=True)
            return record["nodes"], record["relationships"]

    async def _create_fixture(self) -> None:
        cases = [
            {"mode": "pymupdf", "pageNodeCount": 0},
            {"mode": "docling", "pageNodeCount": 2},
            {"mode": "page_image", "pageNodeCount": 2},
        ]
        async with self.driver.session(database=DATABASE) as session:
            await session.run(
                """
                UNWIND $cases AS item
                CREATE (d:Document {
                    id: $idPrefix + item.mode + '-v1',
                    sourceId: $idPrefix + item.mode,
                    version: 1,
                    active: true,
                    name: item.mode + '.pdf',
                    source: '/fixtures/' + item.mode + '.pdf',
                    parseMode: item.mode,
                    totalPages: 2,
                    totalElements: 0,
                    createdAt: '2026-09-10T00:00:00Z',
                    testRunId: $testRunId
                })
                CREATE (c:Chunk {
                    id: $idPrefix + item.mode + '-chunk-0',
                    text: 'LEX-001 deterministic fixture',
                    index: 0,
                    tokenCount: 4,
                    active: true,
                    chunkSetVersion: 1,
                    testRunId: $testRunId
                })-[:PART_OF {testRunId: $testRunId}]->(d)
                FOREACH (pageNumber IN range(0, item.pageNodeCount - 1) |
                    CREATE (d)-[:HAS_PAGE {testRunId: $testRunId}]->(:Page {
                        id: $idPrefix + item.mode + '-page-' + toString(pageNumber),
                        pageNumber: pageNumber,
                        testRunId: $testRunId
                    })
                )
                """,
                cases=cases,
                idPrefix=ID_PREFIX,
                testRunId=TEST_RUN_ID,
            )

    async def test_inventory_and_verification_report_both_counts(self) -> None:
        result = await self.client.call_tool("list_documents", {})
        self.assertFalse(result.is_error, result)
        payload = json.loads(result.content[0].text)
        versions = {
            version["parseMode"]: version
            for document in payload["documents"]
            if document["sourceId"].startswith(ID_PREFIX)
            for version in document["versions"]
        }
        self.assertEqual(
            (2, 0),
            (
                versions["pymupdf"]["sourcePageCount"],
                versions["pymupdf"]["pageNodeCount"],
            ),
        )
        self.assertEqual(
            (2, 2),
            (
                versions["docling"]["sourcePageCount"],
                versions["docling"]["pageNodeCount"],
            ),
        )
        self.assertEqual(
            (2, 2),
            (
                versions["page_image"]["sourcePageCount"],
                versions["page_image"]["pageNodeCount"],
            ),
        )

        with tempfile.TemporaryDirectory(prefix="lex001-") as output_dir:
            for mode, expected_nodes in (("pymupdf", 0), ("docling", 2), ("page_image", 2)):
                result = await self.client.call_tool(
                    "verify_lexical_graph",
                    {
                        "document_id": f"{ID_PREFIX}{mode}-v1",
                        "output_dir": output_dir,
                    },
                )
                self.assertFalse(result.is_error, result)
                verification = json.loads(result.content[0].text)
                stats = verification["statistics"]
                self.assertEqual(2, stats["sourcePageCount"])
                self.assertEqual(expected_nodes, stats["pageNodeCount"])
                self.assertNotIn("pages", stats)
                self.assertTrue(Path(verification["reconstruction_file"]).exists())


if __name__ == "__main__":
    unittest.main()
