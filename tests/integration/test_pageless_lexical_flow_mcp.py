"""Real pageless lexical persistence/chunking with exact UUID ownership cleanup."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

from neo4j import AsyncGraphDatabase

from mcp_neo4j_lexical_graph.models import (
    ParsedDocument,
    ParsedElement,
    ParsedPage,
    ParsedSection,
)
from mcp_neo4j_lexical_graph.graph_writer import write_parsed_document
from mcp_neo4j_lexical_graph.graph_reader import (
    delete_document_cascade,
    get_document,
    get_elements_for_document,
    get_pages_for_document,
    get_sections_for_document,
)
from mcp_neo4j_lexical_graph.chunkers.token_window import TokenWindowChunker
from mcp_neo4j_lexical_graph.chunkers.by_page import ByPageChunker
from mcp_neo4j_lexical_graph.chunkers.by_section import BySectionChunker
from mcp_neo4j_lexical_graph.chunkers.structured import StructuredChunker

DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")


@unittest.skipUnless(
    os.getenv("NEO4J_MCP_RUN_INTEGRATION") == "1", "requires isolated Neo4j"
)
class PagelessLexicalFlowIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.driver = AsyncGraphDatabase.driver(
            os.environ["NEO4J_URI"],
            auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
            notifications_min_severity="OFF",
        )
        self.documents = []

    async def query(self, query, **params):
        async with self.driver.session(database=DATABASE) as session:
            return await (await session.run(query, **params)).data()

    async def asyncTearDown(self):
        try:
            for document_id in self.documents:
                await delete_document_cascade(self.driver, DATABASE, document_id)
        finally:
            await self.driver.close()

    def fixture(self, source_format="markdown"):
        source = "pageless-" + uuid4().hex
        doc_id = source + "_v1"
        self.documents.append(doc_id)
        return ParsedDocument(
            id=doc_id,
            source_id=source,
            name="Maintenance",
            source="/synthetic/maintenance." + source_format,
            parse_mode="document",
            source_format=source_format,
            elements=[
                ParsedElement(
                    id=doc_id + "_e0",
                    type="heading",
                    text="Maintenance",
                    level=1,
                    source_anchor="line:1",
                ),
                ParsedElement(
                    id=doc_id + "_e1",
                    type="heading",
                    text="Valve inspection",
                    level=2,
                    source_anchor="line:3",
                ),
                ParsedElement(
                    id=doc_id + "_e2",
                    type="paragraph",
                    text="Inspect coolant valve CV-7. café 🚀",
                    source_anchor="line:5",
                ),
            ],
            sections=[
                ParsedSection(
                    id=doc_id + "_sec_0",
                    title="Maintenance",
                    level=1,
                    element_ids=[doc_id + "_e0"],
                    subsection_ids=[doc_id + "_sec_1"],
                ),
                ParsedSection(
                    id=doc_id + "_sec_1",
                    title="Valve inspection",
                    level=2,
                    element_ids=[doc_id + "_e1", doc_id + "_e2"],
                ),
            ],
        )

    async def test_all_pageless_formats_roundtrip_order_locators_and_no_pages(self):
        for source_format in ["markdown", "text", "html", "docx"]:
            with self.subTest(source_format=source_format):
                doc = self.fixture(source_format)
                written = await write_parsed_document(self.driver, DATABASE, doc)
                self.assertEqual(0, written["sourcePageCount"])
                self.assertEqual(0, written["pageNodeCount"])
                actual = await get_document(self.driver, DATABASE, doc.id)
                self.assertEqual(source_format, actual["sourceFormat"])
                self.assertEqual(0, actual["totalPages"])
                self.assertEqual(
                    [], await get_pages_for_document(self.driver, DATABASE, doc.id)
                )
                elements = await get_elements_for_document(
                    self.driver, DATABASE, doc.id
                )
                self.assertEqual(
                    [e.text for e in doc.elements], [e["text"] for e in elements]
                )
                self.assertEqual(
                    [e.source_anchor for e in doc.elements],
                    [e["sourceAnchor"] for e in elements],
                )
                self.assertTrue(all(e["pageNumber"] is None for e in elements))
                ranges = await self.query(
                    "MATCH (:Document {id:$id})-[:HAS_SECTION]->(s:Section) RETURN s.pageStart AS start,s.pageEnd AS end",
                    id=doc.id,
                )
                self.assertTrue(
                    all(row["start"] is None and row["end"] is None for row in ranges)
                )
                direct = await self.query(
                    "MATCH (:Document {id:$id})-[:HAS_ELEMENT]->(e:Element) RETURN count(e) AS count",
                    id=doc.id,
                )
                self.assertEqual(3, direct[0]["count"])

    async def test_all_chunkers_and_section_hierarchy_on_real_pageless_graph(self):
        doc = self.fixture()
        await write_parsed_document(self.driver, DATABASE, doc)
        sections = await get_sections_for_document(self.driver, DATABASE, doc.id)
        self.assertEqual(
            ["Maintenance", "Valve inspection"], [s["title"] for s in sections]
        )
        for chunker in [
            TokenWindowChunker(),
            ByPageChunker(),
            BySectionChunker(),
            StructuredChunker(),
        ]:
            with self.subTest(strategy=type(chunker).__name__):
                chunks = await chunker.create_chunks(self.driver, DATABASE, doc.id)
                self.assertTrue(chunks)
                self.assertIn("CV-7", " ".join(c.text for c in chunks))
                self.assertTrue(all(c.source_format == "markdown" for c in chunks))
                self.assertIn("line:5", [a for c in chunks for a in c.source_anchors])
                if isinstance(chunker, (BySectionChunker, StructuredChunker)):
                    self.assertTrue(
                        any(
                            "Maintenance > Valve inspection" in c.section_context
                            for c in chunks
                        )
                    )

    async def test_pdf_compatibility_and_hybrid_membership_deduplicate(self):
        doc = self.fixture()
        doc.parse_mode = "docling"
        doc.source_format = None
        doc.pages = [
            ParsedPage(page_number=0, element_ids=[e.id for e in doc.elements])
        ]
        for element in doc.elements:
            element.page_number = 0
            element.source_anchor = None
        await write_parsed_document(self.driver, DATABASE, doc)
        await self.query(
            "MATCH (d:Document {id:$id})-[:HAS_PAGE]->(:Page)-[:HAS_ELEMENT]->(e:Element) CREATE (d)-[:HAS_ELEMENT]->(e)",
            id=doc.id,
        )
        elements = await get_elements_for_document(self.driver, DATABASE, doc.id)
        self.assertEqual(3, len(elements))
        self.assertTrue(all(e["pageNumber"] == 0 for e in elements))
        self.assertTrue(all(e["sourceFormat"] is None for e in elements))
        pages = await get_pages_for_document(self.driver, DATABASE, doc.id)
        self.assertEqual(1, len(pages))
        self.assertEqual(0, pages[0]["pageNumber"])

    async def test_real_parsers_persist_original_text_and_chunk_all_new_formats(self):
        from docx import Document
        from mcp_neo4j_lexical_graph.parsers.structured_document import (
            StructuredDocumentParser,
        )

        fixtures = Path(__file__).resolve().parents[1] / "fixtures/documents"
        with tempfile.TemporaryDirectory() as folder:
            word_path = Path(folder) / "maintenance.docx"
            word = Document()
            word.add_paragraph("Preface before headings.")
            word.add_heading("Maintenance", level=1)
            word.add_heading("Valve inspection", level=2)
            word.add_paragraph("Inspect coolant valve CV-7.")
            word.save(word_path)
            paths = [
                fixtures / "native.md",
                fixtures / "literal.txt",
                fixtures / "native.html",
                word_path,
            ]
            for path in paths:
                with self.subTest(source=path.suffix):
                    source_id = "parsed-pageless-" + uuid4().hex
                    with patch(
                        "requests.sessions.Session.request",
                        side_effect=AssertionError("No remote resources"),
                    ):
                        parsed = StructuredDocumentParser().parse(str(path), source_id)
                    self.documents.append(parsed.id)
                    await write_parsed_document(self.driver, DATABASE, parsed)
                    elements = await get_elements_for_document(
                        self.driver, DATABASE, parsed.id
                    )
                    self.assertEqual(
                        [element.text for element in parsed.elements],
                        [row["text"] for row in elements],
                    )
                    self.assertEqual(
                        [element.source_anchor for element in parsed.elements],
                        [row["sourceAnchor"] for row in elements],
                    )
                    self.assertTrue(all(row["pageNumber"] is None for row in elements))
                    self.assertEqual(
                        [],
                        await get_pages_for_document(self.driver, DATABASE, parsed.id),
                    )
                    if path.suffix == ".txt":
                        self.assertEqual(
                            path.read_text(), "".join(row["text"] for row in elements)
                        )
                    chunks = await ByPageChunker().create_chunks(
                        self.driver, DATABASE, parsed.id
                    )
                    self.assertTrue(chunks)
                    self.assertTrue(
                        all(
                            chunk.source_format == parsed.source_format
                            for chunk in chunks
                        )
                    )
                    self.assertTrue(all(chunk.source_anchors for chunk in chunks))

    async def test_optional_image_fields_survive_pageless_document_membership(self):
        doc = self.fixture("docx")
        doc.elements.append(
            ParsedElement(
                id=doc.id + "_image",
                type="image",
                text="Valve diagram",
                source_anchor="paragraph:4",
                image_base64="eA==",
                image_mime_type="image/png",
            )
        )
        await write_parsed_document(self.driver, DATABASE, doc)
        image = (await get_elements_for_document(self.driver, DATABASE, doc.id))[-1]
        self.assertEqual("eA==", image["imageBase64"])
        self.assertEqual("image/png", image["imageMimeType"])
        self.assertIsNone(image["pageNumber"])
