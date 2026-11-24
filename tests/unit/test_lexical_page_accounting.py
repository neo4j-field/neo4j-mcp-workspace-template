"""LEX-001 regression tests for source pages versus graph Page nodes."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import fitz
from fastmcp import Client

from mcp_neo4j_lexical_graph.job_manager import JobInfo
from mcp_neo4j_lexical_graph.server import create_mcp_server
from mcp_neo4j_lexical_graph.worker import parse_single_pdf


FIXTURE = (
    Path(__file__).parents[1]
    / "fixtures"
    / "lexical"
    / "page_accounting_cases.json"
)


class LexicalPageAccountingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.cases = json.loads(FIXTURE.read_text())

    async def test_list_documents_exposes_both_unambiguous_counts_for_all_parsers(self) -> None:
        server = create_mcp_server(MagicMock(), process_pool=MagicMock())
        with patch(
            "mcp_neo4j_lexical_graph.server.list_all_documents",
            AsyncMock(return_value=self.cases),
        ):
            async with Client(server) as client:
                result = await client.call_tool("list_documents", {})

        self.assertFalse(result.is_error, result)
        payload = json.loads(result.content[0].text)
        versions = {
            version["parseMode"]: version
            for document in payload["documents"]
            for version in document["versions"]
        }
        self.assertEqual(
            (2, 0),
            (versions["pymupdf"]["sourcePageCount"], versions["pymupdf"]["pageNodeCount"]),
        )
        self.assertEqual(
            (2, 2),
            (versions["docling"]["sourcePageCount"], versions["docling"]["pageNodeCount"]),
        )
        self.assertEqual(
            (2, 2),
            (versions["page_image"]["sourcePageCount"], versions["page_image"]["pageNodeCount"]),
        )
        for version in versions.values():
            self.assertNotIn("pages", version)

    def test_status_names_source_page_progress_explicitly(self) -> None:
        status = JobInfo(
            id="lex001-job",
            path="/fixtures/two-pages.pdf",
            parse_mode="pymupdf",
            source_pages_expected=2,
            current_file_source_page_count=2,
            source_pages_processed=1,
        ).to_status_dict()

        self.assertEqual(2, status["sourcePagesExpected"])
        self.assertEqual(1, status["sourcePagesProcessed"])
        self.assertEqual(2, status["currentFileSourcePageCount"])
        self.assertNotIn("total_pages_expected", status)
        self.assertNotIn("total_pages_processed", status)
        self.assertNotIn("current_file_pages", status)

    def test_real_pymupdf_fixture_preserves_physical_page_count(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lex001-pymupdf-") as tmp_dir:
            pdf_path = Path(tmp_dir) / "two-pages.pdf"
            pdf = fitz.open()
            for page_number in (1, 2):
                page = pdf.new_page()
                page.insert_text((72, 72), f"LEX-001 page {page_number}")
            pdf.save(pdf_path)
            pdf.close()

            parsed = parse_single_pdf(
                str(pdf_path),
                source_id="lex001-pymupdf",
                version=1,
                parse_mode="pymupdf",
                extract_images=False,
                extract_tables=False,
            )

        self.assertEqual(2, parsed["total_pages"])
        self.assertEqual(2, parsed["doc_props"]["totalPages"])


if __name__ == "__main__":
    unittest.main()
