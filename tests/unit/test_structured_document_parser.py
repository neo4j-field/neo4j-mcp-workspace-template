"""Real lightweight Docling non-PDF conversions; no PDF models or remote content."""

import base64
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from docx import Document
from PIL import Image, ImageDraw
from mcp_neo4j_lexical_graph.parsers.structured_document import StructuredDocumentParser

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/documents"


class StructuredDocumentParserTests(unittest.TestCase):
    def setUp(self):
        self.parser = StructuredDocumentParser()

    def assert_pageless(self, parsed, source_format):
        self.assertEqual("document", parsed.parse_mode)
        self.assertEqual(source_format, parsed.source_format)
        self.assertEqual([], parsed.pages)
        self.assertTrue(
            all(
                e.page_number is None and e.coordinates is None for e in parsed.elements
            )
        )
        self.assertTrue(all(e.source_anchor for e in parsed.elements))

    def test_txt_is_literal_with_real_line_anchors(self):
        path = FIXTURES / "literal.txt"
        parsed = self.parser.parse(
            str(path), "literal", metadata={"customer name": "Acme"}
        )
        self.assert_pageless(parsed, "text")
        self.assertEqual([], parsed.sections)
        self.assertEqual({"paragraph"}, {e.type for e in parsed.elements})
        self.assertEqual(path.read_text(), "".join(e.text for e in parsed.elements))
        self.assertEqual("lines:1-3", parsed.elements[0].source_anchor)
        self.assertEqual("Acme", parsed.metadata["customer_name"])
        self.assertEqual(str(path.resolve()), parsed.source)

    def test_real_markdown_and_html_native_hierarchy_tables_and_unfetched_refs(self):
        for suffix, source_format in (("md", "markdown"), ("html", "html")):
            with (
                self.subTest(suffix=suffix),
                patch(
                    "requests.sessions.Session.request",
                    side_effect=AssertionError("No network"),
                ) as request,
                patch(
                    "docling.backend.utils.image_resource_loader.ImageResourceLoader.fetch_remote",
                    side_effect=AssertionError("No remote images"),
                ) as remote_image,
            ):
                parsed = self.parser.parse(str(FIXTURES / f"native.{suffix}"), "native")
                request.assert_not_called()
                remote_image.assert_not_called()
            self.assert_pageless(parsed, source_format)
            headings = [
                s
                for s in parsed.sections
                if s.title in {"Operations", "Cooling", "Measurements"}
            ]
            self.assertEqual([1, 2, 3], [s.level for s in headings])
            self.assertIn(headings[1].id, headings[0].subsection_ids)
            self.assertIn(headings[2].id, headings[1].subsection_ids)
            self.assertIn("list_item", {e.type for e in parsed.elements})
            tables = [e for e in parsed.elements if e.type == "table"]
            self.assertEqual(1, len(tables))
            self.assertIn("72", tables[0].text)
            self.assertIn("<table", tables[0].text_as_html)
            self.assertTrue(
                any(
                    "https://example.invalid/diagram.png" in (e.text or "")
                    for e in parsed.elements
                )
            )
            self.assertTrue(all(e.image_base64 is None for e in parsed.elements))
            if suffix == "html":
                image_id = next(e.id for e in parsed.elements if e.type == "image")
                self.assertTrue(
                    any(
                        e.caption_target_id == image_id
                        for e in parsed.elements
                        if e.type == "caption"
                    )
                )
            self.assertFalse(
                any(
                    "SCRIPT_MUST_NOT_EXECUTE" in (e.text or "") for e in parsed.elements
                )
            )
            # The unheaded preface remains content, not a fabricated section.
            self.assertTrue(
                any(
                    "Preface before headings" in (e.text or "") for e in parsed.elements
                )
            )

    def test_real_docx_preserves_headings_lists_table_and_embedded_image(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "reference.docx"
            document = Document()
            document.add_paragraph("Preface before headings.")
            document.add_heading("Operations", level=1)
            document.add_heading("Cooling", level=2)
            document.add_paragraph("Inspect valve CV-7", style="List Bullet")
            table = document.add_table(rows=2, cols=2)
            for row, values in zip(
                table.rows, (("Sensor", "Value"), ("Pressure", "72"))
            ):
                for cell, value in zip(row.cells, values):
                    cell.text = value
            image = Image.new("RGB", (96, 96), "white")
            ImageDraw.Draw(image).line((0, 0, 95, 95), fill="red", width=8)
            image_stream = BytesIO()
            image.save(image_stream, format="PNG")
            image_stream.seek(0)
            document.add_picture(image_stream)
            document.save(path)
            with patch(
                "requests.sessions.Session.request",
                side_effect=AssertionError("No network"),
            ):
                parsed = self.parser.parse(str(path), "word")
        self.assert_pageless(parsed, "docx")
        self.assertEqual([1, 2], [s.level for s in parsed.sections])
        self.assertIn(parsed.sections[1].id, parsed.sections[0].subsection_ids)
        self.assertIn("list_item", {e.type for e in parsed.elements})
        self.assertTrue(
            any(e.type == "table" and "72" in e.text for e in parsed.elements)
        )
        pictures = [e for e in parsed.elements if e.type == "image"]
        self.assertEqual(1, len(pictures))
        self.assertTrue(
            base64.b64decode(pictures[0].image_base64).startswith(b"\x89PNG")
        )

    def test_extraction_flags_and_alias_extensions(self):
        parsed = self.parser.parse(
            str(FIXTURES / "native.md"),
            "flags",
            extract_images=False,
            extract_tables=False,
            extract_sections=False,
        )
        self.assertEqual([], parsed.sections)
        self.assertNotIn("image", {e.type for e in parsed.elements})
        self.assertNotIn("table", {e.type for e in parsed.elements})
        with tempfile.TemporaryDirectory() as folder:
            for suffix, original in (
                (".markdown", "native.md"),
                (".htm", "native.html"),
                (".xhtml", "native.html"),
                (".text", "literal.txt"),
            ):
                with self.subTest(suffix=suffix):
                    path = Path(folder) / ("alias" + suffix)
                    path.write_bytes((FIXTURES / original).read_bytes())
                    parsed = self.parser.parse(str(path), "alias")
                    self.assertTrue(parsed.elements)

    def test_invalid_mixed_encoding_is_actionable_and_metadata_fails_before_conversion(
        self,
    ):
        with tempfile.TemporaryDirectory() as folder:
            for suffix in (".txt", ".md", ".html"):
                path = Path(folder) / ("damaged" + suffix)
                path.write_bytes("valid café ".encode() + b"\xffdamaged")
                with (
                    self.subTest(suffix=suffix),
                    self.assertRaisesRegex(ValueError, "UTF-8"),
                ):
                    self.parser.parse(str(path), "invalid")
        with patch.object(
            self.parser, "_convert", side_effect=AssertionError("No conversion")
        ):
            with self.assertRaisesRegex(ValueError, "reserved"):
                self.parser.parse(
                    str(FIXTURES / "native.md"), "invalid", metadata={"active": False}
                )

    def test_true_xhtml_preserves_unicode_and_native_heading_levels(self):
        source = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Source</title></head>
<body><h1>Operations</h1><h2>Cooling</h2><p>Inspect café equipment: 東京.</p></body></html>"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.XHTML"
            path.write_text(source, encoding="utf-8")
            parsed = self.parser.parse(str(path), "xhtml")
        self.assert_pageless(parsed, "html")
        self.assertEqual(
            [1, 2],
            [
                section.level
                for section in parsed.sections
                if section.title in {"Operations", "Cooling"}
            ],
        )
        text = "\n".join(element.text or "" for element in parsed.elements)
        self.assertIn("café", text)
        self.assertIn("東京", text)
