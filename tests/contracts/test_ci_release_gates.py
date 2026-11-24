"""Release-gate contracts for TEST-001.

These intentionally inspect workflow source with the standard library so a
broken test dependency cannot prevent the release gate itself from being
checked.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_ROOT = REPO_ROOT / ".github/workflows"
TEST_SUITE = WORKFLOW_ROOT / "test-contracts.yml"
PUBLISH_WORKFLOWS = tuple(sorted(WORKFLOW_ROOT.glob("publish-*.yml")))


class CIReleaseGateContractTests(unittest.TestCase):
    def test_reusable_suite_contains_every_required_job(self) -> None:
        workflow = TEST_SUITE.read_text(encoding="utf-8")

        self.assertIn("workflow_call:", workflow)
        self.assertRegex(workflow, r"(?m)^  unit-and-contract:$")
        self.assertRegex(workflow, r"(?m)^  neo4j-integration:$")
        self.assertRegex(workflow, r"(?m)^  desktop-smoke:$")
        self.assertIn("test_lexical_chunk_rebuild", workflow)
        self.assertIn("test_lexical_parser_modes", workflow)
        self.assertIn("test_structured_ingest_mcp", workflow)
        self.assertIn("test_entity_extraction_coverage_mcp", workflow)
        self.assertIn("test_desktop_lexical_smoke_mcp", workflow)

    def test_every_publish_job_requires_the_reusable_suite(self) -> None:
        self.assertTrue(PUBLISH_WORKFLOWS, "no publish workflows found")

        for path in PUBLISH_WORKFLOWS:
            with self.subTest(workflow=path.name):
                workflow = path.read_text(encoding="utf-8")
                self.assertRegex(
                    workflow,
                    re.compile(
                        r"(?ms)^  test-suite:\n"
                        r"    uses: \./\.github/workflows/test-contracts\.yml\s*$"
                    ),
                )
                self.assertRegex(
                    workflow,
                    re.compile(
                        r"(?ms)^  publish:\n"
                        r"    needs: test-suite\s*$"
                    ),
                )


if __name__ == "__main__":
    unittest.main()
