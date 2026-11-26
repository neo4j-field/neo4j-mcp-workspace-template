"""Public lexical MCP with real spawned workers for pageless sources and mixed input.

No extraction/embedding tools are called. All fixtures use per-test UUID names and
cleanup follows only their exact lexical document ownership.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ProcessPoolExecutor
import json
import multiprocessing
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from uuid import uuid4

from docx import Document
from fastmcp import Client
from neo4j import AsyncGraphDatabase

from mcp_neo4j_lexical_graph.graph_reader import delete_document_cascade
from mcp_neo4j_lexical_graph.server import create_mcp_server

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/documents"
PDF = ROOT / "tests/fixtures/desktop/wf001_wf003_smoke.pdf"
DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")


@unittest.skipUnless(
    os.getenv("NEO4J_MCP_RUN_INTEGRATION") == "1", "requires explicitly isolated Neo4j"
)
class DocumentFormatsMCPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.prefix = "formats-api-" + uuid4().hex
        self.directory = tempfile.TemporaryDirectory()
        self.folder = Path(self.directory.name)
        self.driver = AsyncGraphDatabase.driver(
            os.environ["NEO4J_URI"],
            auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
            notifications_min_severity="OFF",
        )
        self.pool = ProcessPoolExecutor(
            max_workers=1, mp_context=multiprocessing.get_context("spawn")
        )
        self.client = Client(
            create_mcp_server(self.driver, database=DATABASE, process_pool=self.pool),
            timeout=180,
        )
        await self.client.__aenter__()

    async def query(self, query, **params):
        async with self.driver.session(database=DATABASE) as session:
            return await (await session.run(query, **params)).data()

    async def asyncTearDown(self):
        try:
            await self.client.__aexit__(None, None, None)
            # This test owns its actual worker pool; no global/default pool leaks.
            await asyncio.to_thread(self.pool.shutdown, wait=True, cancel_futures=True)
            docs = await self.query(
                "MATCH (d:Document) WHERE d.sourceId STARTS WITH $prefix RETURN d.id AS id",
                prefix=self.prefix,
            )
            for row in docs:
                await delete_document_cascade(self.driver, DATABASE, row["id"])
        finally:
            await self.driver.close()
            self.directory.cleanup()

    async def call(self, name, args):
        result = await self.client.call_tool(name, args)
        self.assertFalse(result.is_error, result)
        return json.loads(result.content[0].text)

    def inputs(self, folder, include_pdf=False):
        folder.mkdir()
        paths = {}
        # Same-stem MD and DOCX are intentional: their default source IDs must differ.
        for suffix, source, source_format in [
            (".md", "native.md", "markdown"),
            (".txt", "literal.txt", "text"),
            (".html", "native.html", "html"),
        ]:
            target = folder / (self.prefix + "-reference" + suffix)
            shutil.copy2(FIXTURES / source, target)
            paths[source_format] = target
        word = Document()
        word.add_paragraph("Preface before headings.")
        word.add_heading("Maintenance", level=1)
        word.add_heading("Valve inspection", level=2)
        word.add_paragraph("Inspect coolant valve CV-7.")
        table = word.add_table(rows=2, cols=2)
        for row, values in zip(table.rows, [("Sensor", "Reading"), ("Pressure", "72")]):
            for cell, value in zip(row.cells, values):
                cell.text = value
        target = folder / (self.prefix + "-reference.docx")
        word.save(target)
        paths["docx"] = target
        if include_pdf:
            target = folder / (self.prefix + "-legacy.pdf")
            shutil.copy2(PDF, target)
            paths["pdf"] = target
        return paths

    async def parse(self, path, expected_files):
        started = await self.call(
            "create_lexical_graph",
            {
                "path": str(path),
                "output_dir": str(self.folder / "outputs"),
                "max_parallel": 1,
                "extract_images": False,
            },
        )
        self.assertEqual(expected_files, started["files_total"])
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            status = await self.call(
                "check_processing_status", {"job_id": started["job_id"]}
            )
            if status["status"] in ["complete", "failed", "cancelled"]:
                self.assertEqual("complete", status["status"], status)
                self.assertEqual(0, status["files_failed"], status)
                self.assertEqual(expected_files, status["files_completed"], status)
                return status
            await asyncio.sleep(1)
        self.fail("Actual spawned-worker parse exceeded 180 seconds")

    async def assert_pageless_document(self, source_format, path):
        rows = await self.query(
            "MATCH (d:Document {sourceId:$source}) RETURN properties(d) AS document",
            source=path.name,
        )
        self.assertEqual(1, len(rows), rows)
        doc = rows[0]["document"]
        doc_id = doc["id"]
        self.assertEqual("document", doc["parseMode"])
        self.assertEqual(source_format, doc["sourceFormat"])
        self.assertEqual(0, doc["totalPages"])
        pages = await self.query(
            "MATCH (:Document {id:$id})-[:HAS_PAGE]->(p:Page) RETURN count(p) AS count",
            id=doc_id,
        )
        self.assertEqual(0, pages[0]["count"])
        elements = await self.query(
            "MATCH (:Document {id:$id})-[:HAS_ELEMENT]->(e:Element) RETURN e.text AS text,e.sourceAnchor AS anchor,e.pageNumber AS page ORDER BY e.order",
            id=doc_id,
        )
        self.assertTrue(elements)
        self.assertTrue(all(row["anchor"] and row["page"] is None for row in elements))
        strategies = {
            "text": ["token_window", "by_page"],
            "docx": ["by_section", "structured"],
        }.get(source_format, ["structured"])
        for strategy in strategies:
            with self.subTest(chunking_strategy=strategy):
                chunked = await self.call(
                    "chunk_lexical_graph",
                    {
                        "document_id": doc_id,
                        "strategy": strategy,
                        "chunk_size": 100,
                        "chunk_overlap": 0,
                    },
                )
                chunks = await self.query(
                    "MATCH (c:Chunk)-[:PART_OF]->(:Document {id:$id}) WHERE c.active=true "
                    "RETURN c.text AS text,c.sourceFormat AS format,c.sourceAnchors AS anchors,"
                    "c.documentName AS document_name",
                    id=doc_id,
                )
                self.assertTrue(chunks, chunked)
                self.assertTrue(
                    all(
                        row["format"] == source_format and row["anchors"]
                        for row in chunks
                    ),
                    chunks,
                )
                # Retrieval filters and extraction context must identify the owning
                # source for every strategy, including non-structured fallbacks.
                self.assertTrue(doc["name"])
                self.assertTrue(
                    all(row["document_name"] == doc["name"] for row in chunks),
                    chunks,
                )
        verified = await self.call(
            "verify_lexical_graph",
            {"document_id": doc_id, "output_dir": str(self.folder / "verification")},
        )
        self.assertEqual("pass", verified["status"], verified)
        reconstructed = Path(verified["reconstruction_file"]).read_text()
        self.assertNotIn("## Page 1", reconstructed)
        if source_format == "text":
            self.assertIn(path.read_text(), reconstructed)
            self.assertIn("```text", reconstructed)
            self.assertEqual(path.read_text(), "".join(row["text"] for row in elements))
        else:
            self.assertIn("CV-7", reconstructed)
            self.assertIn("#", reconstructed)
            self.assertIn("72", reconstructed)
        return doc_id

    async def test_default_single_files_spawn_parse_chunk_verify_inventory(self):
        paths = self.inputs(self.folder / "single")
        ids = []
        for source_format, path in paths.items():
            with self.subTest(source_format=source_format):
                await self.parse(path, 1)
                ids.append(await self.assert_pageless_document(source_format, path))
        self.assertEqual(4, len(set(ids)))
        inventory = await self.call("list_documents", {})
        own = [
            doc
            for doc in inventory["documents"]
            if doc["sourceId"].startswith(self.prefix)
        ]
        self.assertEqual(4, len(own))
        self.assertEqual(
            {"markdown", "text", "html", "docx"},
            {doc["versions"][0]["sourceFormat"] for doc in own},
        )
        self.assertTrue(
            all(
                doc["versions"][0]["sourcePageCount"] == 0
                and doc["versions"][0]["pageNodeCount"] == 0
                for doc in own
            )
        )

    async def test_mixed_folder_routes_new_formats_without_changing_pdf_default(self):
        paths = self.inputs(self.folder / "mixed", include_pdf=True)
        await self.parse(self.folder / "mixed", 5)
        for source_format, path in paths.items():
            if source_format != "pdf":
                with self.subTest(source_format=source_format):
                    await self.assert_pageless_document(source_format, path)
        docs = await self.query(
            "MATCH (d:Document) WHERE d.sourceId STARTS WITH $prefix RETURN d.sourceId AS source,d.parseMode AS mode,d.sourceFormat AS format,d.totalPages AS pages",
            prefix=self.prefix,
        )
        self.assertEqual(5, len(docs))
        pdf = next(row for row in docs if row["mode"] == "pymupdf")
        self.assertEqual(paths["pdf"].stem, pdf["source"])
        self.assertGreater(pdf["pages"], 0)
        self.assertIsNone(pdf["format"])
        self.assertIn(paths["markdown"].name, {row["source"] for row in docs})
        self.assertIn(paths["docx"].name, {row["source"] for row in docs})
