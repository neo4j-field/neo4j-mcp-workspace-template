"""Golden-set scoring detects missing and unsupported graph facts."""

import copy
import json
import unittest
from pathlib import Path

from tests.golden.evaluate import evaluate


REFERENCE = json.loads(Path(__file__).with_name("synthetic_extraction.json").read_text())


class GoldenSetTests(unittest.TestCase):
    def test_exact_reference_scores_one(self):
        report = evaluate(REFERENCE, copy.deepcopy(REFERENCE))
        self.assertEqual(1.0, report["totals"]["entities"]["f1"])
        self.assertEqual(1.0, report["totals"]["relationships"]["f1"])

    def test_missing_relationship_and_false_positive_lower_quality(self):
        candidate = copy.deepcopy(REFERENCE)
        candidate["cases"][0]["relationships"].pop()
        candidate["cases"][1]["relationships"].append({
            "type": "INSPECTED",
            "source": ["Technician", "maya chen"],
            "target": ["Equipment", "px-18"],
        })
        report = evaluate(REFERENCE, candidate)
        self.assertEqual(0.5, report["totals"]["relationships"]["precision"])
        self.assertEqual(0.5, report["totals"]["relationships"]["recall"])
        self.assertEqual(0.0, report["cases"]["maintenance-2"]["relationships"]["f1"])

    def test_missing_case_is_rejected(self):
        candidate = copy.deepcopy(REFERENCE)
        candidate["cases"].pop()
        with self.assertRaisesRegex(ValueError, "case IDs"):
            evaluate(REFERENCE, candidate)


if __name__ == "__main__":
    unittest.main()
