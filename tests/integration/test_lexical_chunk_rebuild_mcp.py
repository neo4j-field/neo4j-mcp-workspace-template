"""Opt-in live regression test for all-document chunk rebuilding.

Every mutable graph element uses the unique BUG001 namespace. The test also
snapshots the retained golden E2E graph before and after the rebuild.
"""

from __future__ import annotations

import json
import os
import unittest
from unittest.mock import MagicMock

from fastmcp import Client
from neo4j import AsyncGraphDatabase

from mcp_neo4j_lexical_graph.server import create_mcp_server


RUN_INTEGRATION = os.getenv("NEO4J_MCP_RUN_INTEGRATION") == "1"
DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")
TEST_RUN_ID = "bug001-live-regression-20260910"
ID_PREFIX = f"{TEST_RUN_ID}-"
DOCUMENT_IDS = (f"{ID_PREFIX}doc-a", f"{ID_PREFIX}doc-b")


@unittest.skipUnless(
    RUN_INTEGRATION,
    "set NEO4J_MCP_RUN_INTEGRATION=1 to run against the configured Neo4j database",
)
class LexicalChunkRebuildMCPIntegrationTests(unittest.IsolatedAsyncioTestCase):
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

    async def _create_fixture(self) -> None:
        async with self.driver.session(database=DATABASE) as session:
            await session.run(
                """
                UNWIND $documentIds AS documentId
                CREATE (d:Document {
                    id: documentId,
                    sourceId: documentId,
                    version: 1,
                    active: true,
                    parseMode: 'docling',
                    name: documentId + '.pdf',
                    totalElements: 1,
                    testRunId: $testRunId
                })
                CREATE (p:Page {
                    id: documentId + '-page-1',
                    pageNumber: 1,
                    testRunId: $testRunId
                })
                CREATE (e:Element {
                    id: documentId + '-element-1',
                    type: 'paragraph',
                    text: 'Deterministic BUG-001 fixture text for ' + documentId,
                    pageNumber: 1,
                    testRunId: $testRunId
                })
                CREATE (old:Chunk {
                    id: documentId + '-old-chunk',
                    text: 'stale chunk',
                    chunkSetVersion: 7,
                    active: true,
                    strategy: 'token_window',
                    testRunId: $testRunId
                })
                CREATE (d)-[:HAS_PAGE {testRunId: $testRunId}]->(p)
                CREATE (p)-[:HAS_ELEMENT {testRunId: $testRunId}]->(e)
                CREATE (old)-[:PART_OF {testRunId: $testRunId}]->(d)
                """,
                documentIds=list(DOCUMENT_IDS),
                testRunId=TEST_RUN_ID,
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

    async def _chunk(self, document_id: str | None = None) -> dict[str, object]:
        result = await self.client.call_tool(
            "chunk_lexical_graph",
            {
                "document_id": document_id,
                "strategy": "token_window",
                "clear_existing_chunks": True,
            },
        )
        self.assertFalse(result.is_error, result)
        return json.loads(result.content[0].text)

    async def _chunk_rows(self) -> list[dict[str, object]]:
        async with self.driver.session(database=DATABASE) as session:
            result = await session.run(
                """
                UNWIND $documentIds AS documentId
                MATCH (c:Chunk)-[:PART_OF]->(d:Document {id: documentId})
                RETURN documentId, count(c) AS chunks,
                       collect(c.id) AS chunkIds,
                       collect(c.retryMarker) AS retryMarkers
                ORDER BY documentId
                """,
                documentIds=list(DOCUMENT_IDS),
            )
            return await result.data()

    async def test_all_document_rebuild_is_scoped_idempotent_and_retry_safe(self) -> None:
        first = await self._chunk()
        self.assertEqual(set(DOCUMENT_IDS), {r["document_id"] for r in first["results"]})
        first_rows = await self._chunk_rows()
        self.assertEqual([1, 1], [row["chunks"] for row in first_rows])
        self.assertTrue(
            all("-old-chunk" not in chunk_id for row in first_rows for chunk_id in row["chunkIds"])
        )

        second = await self._chunk()
        self.assertEqual(set(DOCUMENT_IDS), {r["document_id"] for r in second["results"]})
        self.assertEqual(first_rows, await self._chunk_rows())

        async with self.driver.session(database=DATABASE) as session:
            await session.run(
                """
                MATCH (c:Chunk)-[:PART_OF]->(:Document {id: $documentId})
                SET c.retryMarker = 'must-survive-other-document-rebuild'
                """,
                documentId=DOCUMENT_IDS[1],
            )

        explicit = await self._chunk(DOCUMENT_IDS[0])
        self.assertEqual([DOCUMENT_IDS[0]], [r["document_id"] for r in explicit["results"]])
        final_rows = await self._chunk_rows()
        self.assertEqual([], final_rows[0]["retryMarkers"])
        self.assertEqual(
            ["must-survive-other-document-rebuild"],
            final_rows[1]["retryMarkers"],
        )
        self.assertEqual(self.golden_before, await self._golden_snapshot())


if __name__ == "__main__":
    unittest.main()
