"""Pageless sources retain order/locators without fabricated PDF pages."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from mcp_neo4j_lexical_graph.models import ParsedDocument, ParsedElement, ParsedSection
from mcp_neo4j_lexical_graph.graph_reader import get_elements_for_document
from mcp_neo4j_lexical_graph.graph_writer import write_parsed_document
from mcp_neo4j_lexical_graph.chunkers.token_window import TokenWindowChunker
from mcp_neo4j_lexical_graph.chunkers.by_page import ByPageChunker
from mcp_neo4j_lexical_graph.chunkers.by_section import BySectionChunker
from mcp_neo4j_lexical_graph.chunkers.structured import StructuredChunker


def pageless_document(source_format="markdown"):
    return ParsedDocument(
        id="pageless_v1",
        source_id="pageless",
        name="Maintenance",
        source="/fixture/maintenance.md",
        parse_mode="document",
        source_format=source_format,
        elements=[
            ParsedElement(
                id="heading",
                type="heading",
                text="Maintenance",
                level=1,
                source_anchor="line:1",
            ),
            ParsedElement(
                id="body",
                type="paragraph",
                text="Inspect coolant valve CV-7. café 🚀",
                source_anchor="line:3",
            ),
        ],
        sections=[
            ParsedSection(
                id="section",
                title="Maintenance",
                level=1,
                element_ids=["heading", "body"],
            )
        ],
    )


def element_rows(source_format="markdown"):
    return [
        {
            "id": "heading",
            "type": "heading",
            "text": "Maintenance",
            "level": 1,
            "pageNumber": None,
            "order": 0,
            "sourceAnchor": "line:1",
            "sourceFormat": source_format,
        },
        {
            "id": "body",
            "type": "paragraph",
            "text": "Inspect coolant valve CV-7. café 🚀",
            "pageNumber": None,
            "order": 1,
            "sourceAnchor": "line:3",
            "sourceFormat": source_format,
        },
    ]


class PagelessLexicalFlowTests(unittest.IsolatedAsyncioTestCase):
    def test_optional_pages_preserve_pdf_compatibility(self):
        doc = pageless_document()
        self.assertEqual([], doc.pages)
        self.assertIsNone(doc.elements[0].page_number)
        pdf_element = ParsedElement(
            id="pdf", type="paragraph", page_number=0, text="PDF"
        )
        self.assertEqual(0, pdf_element.page_number)
        self.assertIsNone(pdf_element.source_anchor)
        self.assertIsNone(
            ParsedDocument(
                id="pdf",
                source_id="pdf",
                name="PDF",
                source="/f.pdf",
                parse_mode="docling",
            ).source_format
        )

    async def test_writer_direct_membership_order_and_no_fake_pages(self):
        for source_format in ["markdown", "text", "html", "docx"]:
            with self.subTest(source_format=source_format):
                driver = MagicMock()
                session = AsyncMock()
                driver.session.return_value.__aenter__.return_value = session
                async def execute_write(operation):
                    return await operation(session)

                session.execute_write.side_effect = execute_write
                result = await write_parsed_document(
                    driver, "test", pageless_document(source_format)
                )
                self.assertEqual(0, result["sourcePageCount"])
                self.assertEqual(0, result["pageNodeCount"])
                calls = session.run.call_args_list
                props = next(
                    call.kwargs["props"] for call in calls if "props" in call.kwargs
                )
                self.assertEqual(source_format, props["sourceFormat"])
                self.assertEqual(0, props["totalPages"])
                element_call = next(
                    call for call in calls if "CREATE (e:Element)" in call.args[0]
                )
                self.assertIn("MATCH (d:Document", element_call.args[0])
                for record in element_call.kwargs["records"]:
                    self.assertNotIn("pageId", record)
                    self.assertIsNone(record["pageNumber"])
                    self.assertTrue(record["sourceAnchor"])
                section_record = next(
                    call.kwargs["records"][0]
                    for call in calls
                    if "CREATE (s:Section)" in call.args[0]
                )
                self.assertIsNone(section_record["pageStart"])
                self.assertIsNone(section_record["pageEnd"])
                self.assertTrue(
                    any(
                        "NEXT_ELEMENT" in call.args[0]
                        and call.kwargs.get("pairs")
                        == [{"fromId": "heading", "toId": "body"}]
                        for call in calls
                    )
                )

    async def test_reader_deduplicates_pageless_membership_and_orders_null_pages(self):
        rows = [
            {**element_rows()[1], "nextId": None},
            {**element_rows()[0], "nextId": "body"},
            {**element_rows()[1], "nextId": None},
            {
                "id": "orphan",
                "type": "paragraph",
                "text": "last",
                "pageNumber": None,
                "order": 2,
                "nextId": None,
            },
        ]
        driver = MagicMock()
        session = AsyncMock()
        result = AsyncMock()
        driver.session.return_value.__aenter__.return_value = session
        session.run.return_value = result
        result.data.return_value = rows
        actual = await get_elements_for_document(driver, "test", "pageless_v1")
        self.assertEqual(["heading", "body", "orphan"], [row["id"] for row in actual])
        self.assertEqual("line:3", actual[1]["sourceAnchor"])
        self.assertIn("WITH DISTINCT d, e", session.run.call_args.args[0])

    async def test_all_strategies_chunk_pageless_text_and_preserve_source_locators(
        self,
    ):
        rows = element_rows()
        sections = [
            {
                "id": "section",
                "title": "Maintenance",
                "level": 1,
                "elementIds": ["heading", "body"],
            }
        ]
        for cls, module in [
            (TokenWindowChunker, "token_window"),
            (ByPageChunker, "by_page"),
            (BySectionChunker, "by_section"),
            (StructuredChunker, "structured"),
        ]:
            with self.subTest(strategy=module):
                prefix = "mcp_neo4j_lexical_graph.chunkers."
                with (
                    patch(
                        prefix + module + ".get_elements_for_document",
                        AsyncMock(return_value=rows),
                    ),
                    patch(
                        prefix + "token_window.get_elements_for_document",
                        AsyncMock(return_value=rows),
                    ),
                    patch(
                        prefix + "by_page.get_pages_for_document",
                        AsyncMock(return_value=[]),
                    ),
                    patch(
                        prefix + "by_section.get_sections_for_document",
                        AsyncMock(return_value=sections),
                    ),
                    patch(
                        prefix + "structured.get_sections_for_document",
                        AsyncMock(return_value=sections),
                    ),
                    patch(
                        prefix + "structured.get_document",
                        AsyncMock(return_value={"name": "Maintenance"}),
                    ),
                    patch.object(
                        StructuredChunker, "_get_captions", AsyncMock(return_value={})
                    ),
                ):
                    chunks = await cls().create_chunks(
                        MagicMock(), "test", "pageless_v1"
                    )
                self.assertTrue(chunks)
                self.assertIn("CV-7", " ".join(chunk.text for chunk in chunks))
                self.assertTrue(
                    all(chunk.source_format == "markdown" for chunk in chunks)
                )
                self.assertIn(
                    "line:3",
                    [anchor for chunk in chunks for anchor in chunk.source_anchors],
                )
                self.assertIn(
                    "body", [eid for chunk in chunks for eid in chunk.element_ids]
                )

    async def test_token_windows_map_only_contributing_unicode_elements(self):
        rows = [
            {
                "id": "first",
                "type": "paragraph",
                "text": "café 🚀 " * 40,
                "sourceFormat": "text",
                "sourceAnchor": "line:1",
            },
            {
                "id": "last",
                "type": "paragraph",
                "text": "finish valve CV-7",
                "sourceFormat": "text",
                "sourceAnchor": "line:2",
            },
        ]
        with patch(
            "mcp_neo4j_lexical_graph.chunkers.token_window.get_elements_for_document",
            AsyncMock(return_value=rows),
        ):
            chunks = await TokenWindowChunker(
                chunk_size=16, chunk_overlap=0
            ).create_chunks(MagicMock(), "test", "doc")
        self.assertGreater(len(chunks), 2)
        self.assertEqual(["first"], chunks[0].element_ids)
        self.assertEqual(["line:1"], chunks[0].source_anchors)
        self.assertIn("last", chunks[-1].element_ids)
        self.assertIn("line:2", chunks[-1].source_anchors)
        self.assertEqual(
            "\n\n".join(row["text"] for row in rows),
            "".join(chunk.text for chunk in chunks),
        )
        self.assertNotIn("\ufffd", "".join(chunk.text for chunk in chunks))
