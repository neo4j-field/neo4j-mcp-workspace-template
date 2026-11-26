"""Public ingestion routes documents without fake PDF counts or source-ID collisions."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastmcp import Client
from mcp_neo4j_lexical_graph.input_formats import mode_for_path, default_source_id
from mcp_neo4j_lexical_graph.server import create_mcp_server


class InputRoutingTests(unittest.IsolatedAsyncioTestCase):
    def test_extension_dispatch_and_same_stem_identity(self):
        for suffix in (
            ".md",
            ".markdown",
            ".TXT",
            ".text",
            ".html",
            ".HTM",
            ".xhtml",
            ".docx",
        ):
            self.assertEqual("document", mode_for_path("manual" + suffix))
            self.assertEqual("document", mode_for_path("manual" + suffix, "docling"))
        self.assertEqual("manual", default_source_id("manual.pdf"))
        self.assertNotEqual(
            default_source_id("manual.md"), default_source_id("manual.docx")
        )
        self.assertNotEqual(
            default_source_id("manual.MD"), default_source_id("manual.md")
        )
        for mode in ("pymupdf", "docling", "page_image"):
            self.assertEqual(mode, mode_for_path("manual.PDF", mode))
        for name, mode in [
            ("bad.xlsx", "pymupdf"),
            ("manual.md", "page_image"),
            ("manual.pdf", "vlm_blocks"),
            ("manual.pdf", "document"),
            ("manual.md", "unknown"),
        ]:
            with self.subTest(name=name, mode=mode), self.assertRaises(ValueError):
                mode_for_path(name, mode)

    async def test_removed_experimental_surface_is_unavailable(self):
        driver = MagicMock()
        server = create_mcp_server(driver, process_pool=MagicMock())
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "manual.pdf"
            source.write_bytes(b"placeholder")
            async with Client(server) as client:
                tools = await client.list_tools()
                ingestion = next(tool for tool in tools if tool.name == "create_lexical_graph")
                for removed in ("max_vlm_parallel", "vlm_prompt", "text_preview_length"):
                    self.assertNotIn(removed, ingestion.inputSchema["properties"])
                self.assertNotIn("vlm_blocks", str(ingestion.inputSchema))
                self.assertNotIn("extract_toc", ingestion.inputSchema["properties"])
                with self.assertRaisesRegex(Exception, "Unknown parse_mode"):
                    await client.call_tool("create_lexical_graph", {
                        "path": str(source), "output_dir": directory, "parse_mode": "vlm_blocks",
                    })
        driver.session.assert_not_called()

    async def test_public_default_routes_pageless_without_pdf_preflight(self):
        driver = MagicMock()
        server = create_mcp_server(driver, process_pool=MagicMock())
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "manual.md"
            source.write_text("# Heading\nEvidence")

            async def no_work(**_kwargs):
                return None

            with (
                patch(
                    "mcp_neo4j_lexical_graph.worker.count_pdf_pages",
                    side_effect=AssertionError("Must not read as PDF"),
                ),
                patch("mcp_neo4j_lexical_graph.server._run_job", side_effect=no_work),
            ):
                async with Client(server) as client:
                    result = await client.call_tool(
                        "create_lexical_graph",
                        {"path": str(source), "output_dir": directory},
                    )
            value = json.loads(result.content[0].text)
            self.assertEqual("document", value["parse_mode"])
            self.assertEqual(["markdown"], value["source_formats"])
            self.assertEqual(0, value["sourcePageCount"])
            self.assertEqual(1, value["pageless_files"])
            self.assertIsNone(value["estimated_minutes"])
        driver.session.assert_not_called()

    async def test_mixed_folder_uses_supported_suffixes_once_case_insensitively(self):
        server = create_mcp_server(MagicMock(), process_pool=MagicMock())
        captured = {}

        async def no_work(**kwargs):
            captured.update(kwargs)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for filename in (
                "guide.md",
                "plain.TXT",
                "page.HTML",
                "word.docx",
                "paper.PDF",
                "ignore.csv",
            ):
                (root / filename).write_text("fixture")
            with (
                patch(
                    "mcp_neo4j_lexical_graph.worker.count_pdf_pages", return_value=2
                ) as pdf_count,
                patch("mcp_neo4j_lexical_graph.server._run_job", side_effect=no_work),
            ):
                async with Client(server) as client:
                    value = json.loads(
                        (
                            await client.call_tool(
                                "create_lexical_graph",
                                {"path": directory, "output_dir": str(root / "out")},
                            )
                        )
                        .content[0]
                        .text
                    )
            self.assertEqual(5, value["files_total"])
            self.assertEqual("mixed", value["parse_mode"])
            self.assertEqual(4, value["pageless_files"])
            self.assertEqual(2, value["sourcePageCount"])
            self.assertEqual(1, pdf_count.call_count)
            self.assertEqual(5, len(captured["file_page_counts"]))

    async def test_mixed_folder_rejects_colliding_legacy_pdf_source_before_job(self):
        server = create_mcp_server(MagicMock(), process_pool=MagicMock())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.md").write_text("# Heading")
            (root / "a.md.pdf").write_text("fixture")
            with patch("mcp_neo4j_lexical_graph.server._run_job") as work:
                async with Client(server) as client:
                    with self.assertRaisesRegex(Exception, "Source ID collision"):
                        await client.call_tool(
                            "create_lexical_graph",
                            {"path": directory, "output_dir": str(root / "out")},
                        )
            work.assert_not_called()

    def test_version_remap_preserves_literal_source_payloads(self):
        from mcp_neo4j_lexical_graph.server import _remap_version_in_result

        original = "literal.txt_v1"
        worker = {
            "parse_mode": "document",
            "parsed_doc": {
                "id": original,
                "source_id": "literal.txt",
                "version": 1,
                "source": "/source/" + original,
                "metadata": {"note": original, "version": 1},
                "parse_params": {"literal": original},
                "pages": [],
                "elements": [
                    {
                        "id": original + "_elem_0",
                        "text": original,
                        "source_anchor": original,
                        "caption_target_id": original + "_elem_1",
                    },
                    {"id": original + "_elem_1", "text": "image"},
                ],
                "sections": [
                    {
                        "id": original + "_sec_0",
                        "title": original,
                        "element_ids": [original + "_elem_0"],
                        "subsection_ids": [original + "_sec_1"],
                    }
                ],
            },
        }
        changed = _remap_version_in_result(worker, "literal.txt", 1, 2)["parsed_doc"]
        self.assertEqual("literal.txt_v2", changed["id"])
        self.assertEqual(2, changed["version"])
        self.assertEqual(original, worker["parsed_doc"]["id"])
        self.assertEqual(original, changed["elements"][0]["text"])
        self.assertEqual(original, changed["elements"][0]["source_anchor"])
        self.assertEqual({"note": original, "version": 1}, changed["metadata"])
        self.assertEqual(original, changed["parse_params"]["literal"])
        self.assertEqual("/source/" + original, changed["source"])
        self.assertEqual(original, changed["sections"][0]["title"])
        self.assertEqual(
            ["literal.txt_v2_elem_0"], changed["sections"][0]["element_ids"]
        )
        self.assertEqual(
            "literal.txt_v2_elem_1", changed["elements"][0]["caption_target_id"]
        )

    def test_pdf_version_remap_updates_only_known_asset_placeholders(self):
        from mcp_neo4j_lexical_graph.server import _remap_version_in_result

        worker = {
            "parse_mode": "pymupdf",
            "doc_id": "guide_v1_v1",
            "version": 1,
            "doc_props": {"id": "guide_v1_v1", "version": 1},
            "element_records": [{"id": "guide_v1_v1_fig_0"}],
            "chunks": [
                {
                    "id": "guide_v1_v1_chunk_0",
                    "text": "Literal guide_v1_v1 [IMAGE: guide_v1_v1_fig_0] [IMAGE: unrelated_v1]",
                    "hasElementIds": ["guide_v1_v1_fig_0"],
                }
            ],
        }
        changed = _remap_version_in_result(worker, "guide_v1", 1, 2)
        self.assertEqual("guide_v1_v2", changed["doc_id"])
        self.assertEqual(
            "Literal guide_v1_v1 [IMAGE: guide_v1_v2_fig_0] [IMAGE: unrelated_v1]",
            changed["chunks"][0]["text"],
        )
        self.assertEqual(["guide_v1_v2_fig_0"], changed["chunks"][0]["hasElementIds"])
