"""Atomic replacement against Neo4j, including concurrent-reader observations."""

import asyncio
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

from neo4j import AsyncGraphDatabase

from mcp_neo4j_lexical_graph import graph_writer
from mcp_neo4j_lexical_graph.graph_reader import delete_document_cascade
from mcp_neo4j_lexical_graph.models import ParsedDocument, ParsedElement


@unittest.skipUnless(os.getenv("NEO4J_MCP_RUN_INTEGRATION") == "1", "requires isolated Neo4j")
class DocumentVersionPublicationIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.database = os.getenv("NEO4J_DATABASE", "neo4j")
        self.driver = AsyncGraphDatabase.driver(
            os.environ["NEO4J_URI"],
            auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
            notifications_min_severity="OFF",
        )
        self.source_id = "atomic-" + uuid4().hex
        self.ids = [self.source_id + "_v1", self.source_id + "_v2"]

    async def asyncTearDown(self):
        try:
            for doc_id in self.ids:
                await delete_document_cascade(self.driver, self.database, doc_id)
        finally:
            await self.driver.close()

    def document(self, version):
        doc_id = self.ids[version - 1]
        return ParsedDocument(
            id=doc_id, source_id=self.source_id, version=version,
            name="Atomic fixture", source="/synthetic/atomic.md",
            parse_mode="document", source_format="markdown",
            elements=[ParsedElement(id=doc_id + "_e1", type="paragraph", text="Complete body")],
        )

    async def query(self, query, **params):
        async with self.driver.session(database=self.database) as session:
            return await (await session.run(query, **params)).data()

    async def versions(self):
        return await self.query(
            "MATCH (d:Document {sourceId:$source}) RETURN d.id AS id,d.active AS active ORDER BY d.id",
            source=self.source_id,
        )

    async def test_failed_mid_graph_replacement_preserves_old_active_and_rolls_back_all_new_nodes(self):
        await graph_writer.write_parsed_document(self.driver, self.database, self.document(1))
        original = graph_writer._batch_write
        observed = []

        async def fail_after_elements(driver, database, query, records):
            await original(driver, database, query, records)
            if "CREATE (e:Element)" in query:
                observed.extend(await self.versions())
                raise RuntimeError("injected after element batch")

        with patch.object(graph_writer, "_batch_write", fail_after_elements):
            with self.assertRaisesRegex(RuntimeError, "injected"):
                await graph_writer.write_parsed_document(self.driver, self.database, self.document(2))
        expected = [{"id": self.ids[0], "active": True}]
        self.assertEqual(expected, observed)
        self.assertEqual(expected, await self.versions())
        self.assertEqual([{"count": 0}], await self.query(
            "MATCH (n) WHERE n.id STARTS WITH $prefix RETURN count(n) AS count", prefix=self.ids[1]
        ))

    async def test_successful_replacement_publishes_complete_graph_and_switches_only_at_commit(self):
        await graph_writer.write_parsed_document(self.driver, self.database, self.document(1))
        original = graph_writer._activate_document
        observed = []

        async def observe_before_activation(transaction, source_id, document_id):
            observed.extend(await self.versions())
            await original(transaction, source_id, document_id)
            self.assertEqual([{"id": self.ids[0], "active": True}], await self.versions())

        with patch.object(graph_writer, "_activate_document", observe_before_activation):
            await graph_writer.write_parsed_document(self.driver, self.database, self.document(2))
        self.assertEqual([{"id": self.ids[0], "active": True}], observed)
        self.assertEqual([
            {"id": self.ids[0], "active": False}, {"id": self.ids[1], "active": True}
        ], await self.versions())
        self.assertEqual([{"count": 1}], await self.query(
            "MATCH (:Document {id:$id})-[:HAS_ELEMENT]->(e:Element) RETURN count(e) AS count", id=self.ids[1]
        ))

    async def test_cancelled_first_ingestion_publishes_nothing(self):
        original = graph_writer._batch_write

        async def cancel_after_elements(driver, database, query, records):
            await original(driver, database, query, records)
            if "CREATE (e:Element)" in query:
                raise asyncio.CancelledError()

        with patch.object(graph_writer, "_batch_write", cancel_after_elements):
            with self.assertRaises(asyncio.CancelledError):
                await graph_writer.write_parsed_document(self.driver, self.database, self.document(1))
        self.assertEqual([], await self.versions())

    async def test_invalid_manual_chunk_set_keeps_current_document_and_chunks(self):
        for version in (1, 2):
            await graph_writer.write_parsed_document(self.driver, self.database, self.document(version))
        await self.query(
            "MATCH (d:Document {id:$id}) CREATE (:Chunk {id:$chunk,chunkSetVersion:1,active:true})-[:PART_OF]->(d)",
            id=self.ids[1], chunk=self.ids[1] + "_chunk",
        )
        with self.assertRaisesRegex(ValueError, "active versions were preserved"):
            await graph_writer.activate_document_version(self.driver, self.database, self.ids[0], 99)
        self.assertEqual([
            {"id": self.ids[0], "active": False}, {"id": self.ids[1], "active": True}
        ], await self.versions())
        self.assertEqual([{"active": True}], await self.query(
            "MATCH (c:Chunk {id:$id}) RETURN c.active AS active", id=self.ids[1] + "_chunk"
        ))
        count = await graph_writer.activate_document_version(self.driver, self.database, self.ids[1], 1)
        self.assertEqual(1, count)

    async def test_concurrent_same_version_writers_cannot_publish_duplicate_or_partial_graphs(self):
        await graph_writer.write_parsed_document(self.driver, self.database, self.document(1))
        results = await asyncio.gather(*(
            graph_writer.write_parsed_document(self.driver, self.database, self.document(2))
            for _ in range(2)
        ), return_exceptions=True)
        self.assertEqual(1, sum(isinstance(result, Exception) for result in results))
        self.assertEqual(1, sum(isinstance(result, dict) for result in results))
        self.assertEqual([
            {"id": self.ids[0], "active": False}, {"id": self.ids[1], "active": True}
        ], await self.versions())
        self.assertEqual([{"count": 1}], await self.query(
            "MATCH (:Document {id:$id})-[:HAS_ELEMENT]->(e:Element) RETURN count(e) AS count",
            id=self.ids[1],
        ))

    async def test_pymupdf_replacement_failure_rolls_back_complete_new_graph(self):
        from mcp_neo4j_lexical_graph import server
        await graph_writer.write_parsed_document(self.driver, self.database, self.document(1))
        doc_id = self.ids[1]
        worker_result = {
            "parse_mode": "pymupdf", "doc_id": doc_id, "source_id": self.source_id,
            "version": 2, "total_pages": 1, "element_records": [], "chunks": [],
            "fig_counter": 0, "tbl_counter": 0,
            "doc_props": {"id": doc_id, "sourceId": self.source_id, "version": 2, "active": True},
        }
        original = server._write_pymupdf_result

        async def fail_after_write(*args):
            await original(*args)
            raise RuntimeError("injected pymupdf failure")

        with patch.object(server, "_write_pymupdf_result", fail_after_write):
            with self.assertRaisesRegex(RuntimeError, "injected pymupdf"):
                await server._write_worker_result_to_neo4j(
                    self.driver, self.database, worker_result, self.source_id, 2
                )
        self.assertEqual([{"id": self.ids[0], "active": True}], await self.versions())
