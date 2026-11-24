"""Compare extracted graph facts with a human-authored synthetic reference.

Candidate JSON uses the same `cases` shape as synthetic_extraction.json. Each case
needs an `id`, `entities`, and `relationships`; source text is optional. This
evaluator contains no model call and never lets a candidate supply its own truth.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _entity(value: dict) -> tuple[str, str]:
    return (value["label"].strip().casefold(), value["key"].strip().casefold())


def _relationship(value: dict) -> tuple[str, tuple[str, str], tuple[str, str]]:
    return (
        value["type"].strip().upper(),
        (value["source"][0].strip().casefold(), value["source"][1].strip().casefold()),
        (value["target"][0].strip().casefold(), value["target"][1].strip().casefold()),
    )


def _score(expected: set, observed: set) -> dict[str, float | int]:
    matched = len(expected & observed)
    precision = matched / len(observed) if observed else (1.0 if not expected else 0.0)
    recall = matched / len(expected) if expected else (1.0 if not observed else 0.0)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "expected": len(expected), "observed": len(observed), "matched": matched,
        "precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4),
    }


def evaluate(reference: dict, candidate: dict) -> dict:
    expected_cases = {item["id"]: item for item in reference["cases"]}
    observed_cases = {item["id"]: item for item in candidate["cases"]}
    if len(expected_cases) != len(reference["cases"]) or len(observed_cases) != len(candidate["cases"]):
        raise ValueError("Case IDs must be unique")
    if expected_cases.keys() != observed_cases.keys():
        raise ValueError("Candidate case IDs must match the reference")

    totals = {"entities": [set(), set()], "relationships": [set(), set()]}
    cases = {}
    for case_id, expected in expected_cases.items():
        observed = observed_cases[case_id]
        case_scores = {}
        for kind, normalizer in (("entities", _entity), ("relationships", _relationship)):
            gold = {normalizer(item) for item in expected[kind]}
            found = {normalizer(item) for item in observed[kind]}
            case_scores[kind] = _score(gold, found)
            totals[kind][0].update((case_id, value) for value in gold)
            totals[kind][1].update((case_id, value) for value in found)
        cases[case_id] = case_scores
    return {
        "reference": reference["name"],
        "cases": cases,
        "totals": {kind: _score(*pairs) for kind, pairs in totals.items()},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--reference", type=Path, default=Path(__file__).with_name("synthetic_extraction.json"))
    parser.add_argument("--baseline", type=Path, help="Prior candidate for quality deltas")
    args = parser.parse_args()
    reference = json.loads(args.reference.read_text())
    current = evaluate(reference, json.loads(args.candidate.read_text()))
    if args.baseline:
        baseline = evaluate(reference, json.loads(args.baseline.read_text()))
        current["delta_vs_baseline"] = {
            kind: {
                metric: round(current["totals"][kind][metric] - baseline["totals"][kind][metric], 4)
                for metric in ("precision", "recall", "f1")
            }
            for kind in ("entities", "relationships")
        }
    print(json.dumps(current, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
