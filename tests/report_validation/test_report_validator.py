"""Tests for deterministic workflow-report completion checks."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PROXY_SRC = REPO_ROOT / "mcp-neo4j-proxy/src"
FIXTURES = REPO_ROOT / "tests/fixtures/reports"
sys.path.insert(0, str(PROXY_SRC))

from mcp_neo4j_proxy.report_validator import load_contracts, validate_report  # noqa: E402


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class ReportValidatorTests(unittest.TestCase):
    def test_contract_resource_loads(self) -> None:
        contracts = load_contracts()
        self.assertIn("chatbot_report", contracts)
        self.assertIn("analytical_report", contracts)
        self.assertNotIn("graph_quality_report", contracts)

    def test_valid_chatbot_report(self) -> None:
        result = validate_report(
            _fixture("valid_chatbot.md"),
            report_type="chatbot_report",
            expected_records=2,
        )
        self.assertTrue(result.valid, result.errors)
        self.assertEqual(2, result.records_found)

    def test_valid_analytical_pdf_report(self) -> None:
        result = validate_report(
            _fixture("valid_analytical_pdf.md"),
            report_type="analytical_report",
            expected_records=1,
            pdf_data_present=True,
        )
        self.assertTrue(result.valid, result.errors)

    def test_incomplete_report_lists_all_actionable_errors(self) -> None:
        result = validate_report(
            _fixture("invalid_chatbot.md"),
            report_type="chatbot_report",
            expected_records=2,
            pdf_data_present=True,
        )
        self.assertFalse(result.valid)
        self.assertIn("missing section: Recommended Next Steps", result.errors)
        self.assertIn("missing section: Extraction Quality", result.errors)
        self.assertIn("Graph Data Model must include a Mermaid diagram", result.errors)
        self.assertIn("expected 2 repeated records, found 1", result.errors)
        self.assertIn("record 1: missing substantive query", result.errors)
        self.assertIn("record 1: missing substantive improvement", result.errors)

    def test_tolerates_numbered_headings_and_plain_field_labels(self) -> None:
        report = _fixture("valid_chatbot.md")
        report = report.replace("## Source Data", "## 1. Source Data")
        report = report.replace("## Use Case", "## USE CASE")
        report = report.replace("## Graph Data Model", "## Graph data model")
        report = report.replace("- **Method**:", "- Method:")

        result = validate_report(
            report,
            report_type="chatbot_report",
            expected_records=2,
        )

        self.assertTrue(result.valid, result.errors)

    def test_record_count_must_be_positive(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least 1"):
            validate_report(
                _fixture("valid_chatbot.md"),
                report_type="chatbot_report",
                expected_records=0,
            )

    def test_deferred_report_type_is_not_claimed_as_supported(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown report type"):
            validate_report(
                _fixture("valid_chatbot.md"),
                report_type="graph_quality_report",
                expected_records=1,
            )


if __name__ == "__main__":
    unittest.main()
