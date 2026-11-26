"""Document metadata cannot rewrite lexical identity in any parse path."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastmcp import Client
from fastmcp.exceptions import ToolError
from mcp_neo4j_lexical_graph.metadata import normalize_document_metadata
from mcp_neo4j_lexical_graph.models import ParsedDocument
from mcp_neo4j_lexical_graph.graph_writer import write_parsed_document
from mcp_neo4j_lexical_graph.server import create_mcp_server
from mcp_neo4j_lexical_graph.worker import parse_single_pdf

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/desktop/wf001_wf003_smoke.pdf"


class MetadataTests(unittest.TestCase):
    def test_custom_metadata_preserved_and_consistently_normalized(self):
        self.assertEqual(
            {"customer_name": "Acme", "poc_tag": "demo"},
            normalize_document_metadata({"customer name": "Acme", "poc-tag": "demo"}),
        )

    def test_reserved_and_normalized_collision_rejected(self):
        for metadata in (
            {"id": "other"},
            {"active": False},
            {"sourceId": "other"},
            {"parseParams": "override"},
            {"--extractionCreated": True},
            {"my-key": 1, "my key": 2},
            [],
        ):
            with self.subTest(metadata=metadata), self.assertRaises(ValueError):
                normalize_document_metadata(metadata)

    def test_worker_rejects_before_any_parser_across_modes(self):
        for mode in ("pymupdf", "docling", "page_image"):
            with (
                self.subTest(mode=mode),
                self.assertRaisesRegex(ValueError, "reserved"),
            ):
                parse_single_pdf(
                    str(FIXTURE), "metadata", 1, parse_mode=mode, metadata={"id": "bad"}
                )

    def test_custom_metadata_survives_real_fast_parser_paths(self):
        for mode in ("pymupdf", "page_image"):
            with self.subTest(mode=mode):
                result = parse_single_pdf(
                    str(FIXTURE),
                    "metadata",
                    1,
                    parse_mode=mode,
                    metadata={"customer name": "Acme"},
                )
                props = (
                    result["doc_props"]
                    if mode == "pymupdf"
                    else result["parsed_doc"]["metadata"]
                )
                self.assertEqual("Acme", props["customer_name"])


class MetadataBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_writer_rejects_before_constraints_or_graph_writes(self):
        doc = ParsedDocument(
            id="doc",
            source_id="source",
            name="Fixture",
            source=str(FIXTURE),
            parse_mode="docling",
            metadata={"version": 99},
        )
        driver = MagicMock()
        with patch(
            "mcp_neo4j_lexical_graph.graph_writer.ensure_constraints", AsyncMock()
        ) as constraints:
            with self.assertRaisesRegex(ValueError, "reserved"):
                await write_parsed_document(driver, "bug_check", doc)
        constraints.assert_not_awaited()
        driver.session.assert_not_called()

    async def test_mcp_rejects_metadata_before_background_work_for_all_modes(self):
        driver, pool = MagicMock(), MagicMock()
        server = create_mcp_server(driver, database="bug_check", process_pool=pool)
        with (
            tempfile.TemporaryDirectory() as output,
            patch(
                "mcp_neo4j_lexical_graph.server.get_existing_versions", AsyncMock()
            ) as versions,
        ):
            async with Client(server) as client:
                for mode in ("pymupdf", "docling", "page_image"):
                    with (
                        self.subTest(mode=mode),
                        self.assertRaisesRegex(ToolError, "reserved"),
                    ):
                        await client.call_tool(
                            "create_lexical_graph",
                            {
                                "path": str(FIXTURE),
                                "parse_mode": mode,
                                "metadata_json": '{"active":false}',
                                "output_dir": output,
                            },
                        )
        versions.assert_not_awaited()
        pool.submit.assert_not_called()
        driver.session.assert_not_called()
