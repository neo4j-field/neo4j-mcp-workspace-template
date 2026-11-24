"""Live BUG-003 regression with deterministic Chunk and Page extraction outcomes.

No model API is called. All graph mutations use an exact fixture namespace and are
removed in teardown; the retained golden E2E graph is snapshotted before and after.
"""

from __future__ import annotations

import asyncio
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from fastmcp import Client
from neo4j import AsyncGraphDatabase

from mcp_neo4j_entity_graph.models import (
    ChunkExtractionOutcome,
    ChunkExtractionResult,
    ExtractedEntity,
)
from mcp_neo4j_entity_graph.server import create_mcp_server


RUN_INTEGRATION = os.getenv("NEO4J_MCP_RUN_INTEGRATION") == "1"
DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")
TEST_RUN_ID = "bug003-live-regression-20260910"
RESTART_TEST_RUN_ID = "test002-restart-reextract-20260910"
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "fixtures/entity/bug003_schema.py"


@unittest.skipUnless(
    RUN_INTEGRATION,
    "set NEO4J_MCP_RUN_INTEGRATION=1 to run against configured Neo4j",
)
class EntityExtractionCoverageMCPIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.driver = AsyncGraphDatabase.driver(
            os.environ["NEO4J_URI"],
            auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
        )
        await self._cleanup_fixture()
        self.golden_before = await self._golden_snapshot()

    async def asyncTearDown(self) -> None:
        await self._cleanup_fixture()
        self.assertEqual(self.golden_before, await self._golden_snapshot())
        await self.driver.close()

    async def _cleanup_fixture(self) -> None:
        async with self.driver.session(database=DATABASE) as session:
            await session.run(
                "MATCH (claim:EntityExtractionClaim) WHERE claim.sourceLabel IN $labels DETACH DELETE claim",
                labels=['Bug003ChunkSource', 'Bug003PageSource', 'Test002RestartSource'],
            )
            await session.run(
                "MATCH (run:EntityExtractionRun) WHERE run.sourceLabel IN $labels DETACH DELETE run",
                labels=['Bug003ChunkSource', 'Bug003PageSource', 'Test002RestartSource'],
            )
            await session.run(
                """
                MATCH (n) WHERE n.testRunId IN $testRunIds
                DETACH DELETE n
                """,
                testRunIds=[TEST_RUN_ID, RESTART_TEST_RUN_ID],
            )

    async def _golden_snapshot(self) -> tuple[int, int]:
        async with self.driver.session(database=DATABASE) as session:
            result = await session.run(
                """
                MATCH (n)
                WHERE any(k IN keys(n) WHERE toStringOrNull(n[k]) CONTAINS 'golden-e2e-20260910')
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

    async def _create_sources(self, source_label: str, *, page: bool) -> None:
        page_label = ":Page" if page else ""
        image_props = ", imageBase64: 'aW1hZ2U=', imageMimeType: 'image/png'" if page else ""
        async with self.driver.session(database=DATABASE) as session:
            await session.run(
                f"""
                UNWIND ['success', 'empty', 'failed'] AS outcome
                CREATE (n:{source_label}{page_label} {{
                    id: $testRunId + '-' + outcome,
                    type: 'text',
                    text: 'SENTINEL-' + toUpper(outcome) + '-END',
                    testRunId: $testRunId
                    {image_props}
                }})
                """,
                testRunId=TEST_RUN_ID,
            )

    async def _stub_text(self, chunk, _schema, _output_model):
        return await self._stub_result(chunk)

    async def _stub_vlm(self, chunk, _schema, _output_model):
        return await self._stub_result(chunk)

    async def _stub_result(self, chunk):
        if chunk.id.endswith("-success"):
            return ChunkExtractionResult(
                chunk_id=chunk.id,
                outcome=ChunkExtractionOutcome.SUCCESS,
                entities=[
                    ExtractedEntity(
                        label="Bug003Sentinel",
                        properties={
                            "sentinelId": f"{chunk.id}-entity",
                            "testRunId": TEST_RUN_ID,
                        },
                    )
                ],
            )
        if chunk.id.endswith("-empty"):
            return ChunkExtractionResult(
                chunk_id=chunk.id, outcome=ChunkExtractionOutcome.EMPTY
            )
        return ChunkExtractionResult(
            chunk_id=chunk.id,
            outcome=ChunkExtractionOutcome.FAILED,
            attempts=3,
            error="fixture truncated structured response after retries",
        )

    async def _run_mode(self, source_label: str, *, page: bool) -> None:
        await self._create_sources(source_label, page=page)
        server = create_mcp_server(self.driver, database=DATABASE)

        with (
            patch(
                "mcp_neo4j_entity_graph.server.TextExtractor.extract_chunk",
                new=self._stub_text,
            ),
            patch(
                "mcp_neo4j_entity_graph.server.VlmExtractor.extract_chunk",
                new=self._stub_vlm,
            ),
        ):
            async with Client(server) as client:
                result = await client.call_tool(
                    "extract_entities",
                    {
                        "schema": str(SCHEMA_PATH),
                        "source_label": source_label,
                        "force": True,
                        "batch_size": 1,
                    },
                )
                started = json.loads(result.content[0].text)
                for _ in range(100):
                    status_result = await client.call_tool(
                        "check_extraction_status", {"job_id": started["job_id"]}
                    )
                    status = json.loads(status_result.content[0].text)
                    if status["status"] in {"complete", "failed"}:
                        break
                    await asyncio.sleep(0.02)
                else:
                    self.fail("BUG-003 live extraction did not finish")

        self.assertEqual("failed", status["status"], status)
        self.assertEqual(3, status["eligible_sources"])
        self.assertEqual(3, status["selected_sources"])
        self.assertEqual(3, status["sources_attempted"])
        self.assertEqual(1, status["sources_succeeded"])
        self.assertEqual(1, status["sources_empty"])
        self.assertEqual(1, status["sources_failed"])
        self.assertEqual(0, status["sources_persisted"])
        self.assertEqual([f"{TEST_RUN_ID}-failed"], status["failed_source_ids"])

        async with self.driver.session(database=DATABASE) as session:
            graph_result = await session.run(
                """
                MATCH (e:Bug003Sentinel {testRunId: $testRunId})
                      -[:EXTRACTED_FROM]->(source {testRunId: $testRunId})
                RETURN count(DISTINCT e) AS entities,
                       count(DISTINCT source) AS persistedSources
                """,
                testRunId=TEST_RUN_ID,
            )
            record = await graph_result.single(strict=True)
            self.assertEqual((0, 0), (record["entities"], record["persistedSources"]))

        await self._cleanup_fixture()

    async def test_chunk_and_page_source_modes_surface_partial_coverage(self) -> None:
        await self._run_mode("Bug003ChunkSource", page=False)
        await self._run_mode("Bug003PageSource", page=True)

    async def test_restart_skip_and_forced_reextraction_are_graph_idempotent(self) -> None:
        source_label = "Test002RestartSource"
        entity_id = f"{RESTART_TEST_RUN_ID}-entity"
        async with self.driver.session(database=DATABASE) as session:
            await session.run(
                f"""
                CREATE (n:{source_label} {{
                    id: $sourceId,
                    type: 'text',
                    text: 'TEST-002 restart and re-extraction sentinel',
                    testRunId: $testRunId
                }})
                """,
                sourceId=f"{RESTART_TEST_RUN_ID}-source",
                testRunId=RESTART_TEST_RUN_ID,
            )

        generation = 1

        async def stub_extract(_extractor, chunk, _schema, _output_model):
            return ChunkExtractionResult(
                chunk_id=chunk.id,
                outcome=ChunkExtractionOutcome.SUCCESS,
                entities=[
                    ExtractedEntity(
                        label="Bug003Sentinel",
                        properties={
                            "sentinelId": entity_id,
                            "testRunId": RESTART_TEST_RUN_ID,
                            "generation": generation,
                        },
                    )
                ],
            )

        async def extract(client, *, force: bool) -> dict:
            result = await client.call_tool(
                "extract_entities",
                {
                    "schema": str(SCHEMA_PATH),
                    "source_label": source_label,
                    "force": force,
                    "property_policy": "overwrite",  # This fixture tests replacing a generation.
                    "batch_size": 1,
                },
            )
            started = json.loads(result.content[0].text)
            if started["job_id"] is None:
                return started
            for _ in range(100):
                status_result = await client.call_tool(
                    "check_extraction_status", {"job_id": started["job_id"]}
                )
                status = json.loads(status_result.content[0].text)
                if status["status"] in {"complete", "failed"}:
                    return status
                await asyncio.sleep(0.02)
            self.fail("TEST-002 extraction did not finish")

        with patch(
            "mcp_neo4j_entity_graph.server.TextExtractor.extract_chunk",
            new=stub_extract,
        ):
            first_server = create_mcp_server(self.driver, database=DATABASE)
            async with Client(first_server) as first_client:
                first = await extract(first_client, force=True)
            self.assertEqual("complete", first["status"], first)

            # A new server has no in-memory job ledger, but the graph remains the
            # durable source of truth for safe skip/retry behavior after restart.
            restarted_server = create_mcp_server(self.driver, database=DATABASE)
            async with Client(restarted_server) as restarted_client:
                old_status_result = await restarted_client.call_tool(
                    "check_extraction_status", {"job_id": first["job_id"]}
                )
                old_status = json.loads(old_status_result.content[0].text)
                self.assertIn("not found", old_status["error"])

                skipped = await extract(restarted_client, force=False)
                self.assertIsNone(skipped["job_id"])
                self.assertEqual(1, skipped["eligible_sources"])
                self.assertEqual(0, skipped["selected_sources"])

                generation = 2
                second = await extract(restarted_client, force=True)
                self.assertEqual("complete", second["status"], second)

        async with self.driver.session(database=DATABASE) as session:
            result = await session.run(
                f"""
                MATCH (e:Bug003Sentinel {{sentinelId: $entityId}})
                      -[r:EXTRACTED_FROM]->(s:{source_label} {{testRunId: $testRunId}})
                RETURN count(DISTINCT e) AS entities,
                       count(DISTINCT r) AS provenance,
                       max(e.generation) AS generation
                """,
                entityId=entity_id,
                testRunId=RESTART_TEST_RUN_ID,
            )
            record = await result.single(strict=True)
        self.assertEqual((1, 1, 2), tuple(record.values()))


if __name__ == "__main__":
    unittest.main()
