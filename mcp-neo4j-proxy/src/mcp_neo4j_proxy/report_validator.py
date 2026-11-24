"""Deterministic validation for graph-development Markdown reports."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml


CONTRACT_RESOURCE = "report_contracts.yaml"
ACTIVE_REPORT_TYPES = {"chatbot_report", "analytical_report"}
PLACEHOLDER_RE = re.compile(r"^(?:tbd|todo|n/?a|none|<[^>]+>|\[.+\])$", re.IGNORECASE)
H2_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
H3_RE = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)
FIELD_RE = re.compile(
    r"^\s*[-*]?\s*\*\*(?P<label>[^*]+)\*\*\s*:\s*(?P<value>.+?)\s*$",
    re.MULTILINE,
)


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    report_type: str
    expected_records: int
    records_found: int
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_contracts() -> dict[str, Any]:
    contract_path = files("mcp_neo4j_proxy").joinpath(CONTRACT_RESOURCE)
    data = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    if data.get("version") != 1 or not isinstance(data.get("contracts"), dict):
        raise ValueError("Unsupported or malformed report contract")
    return data["contracts"]


def _is_substantive(value: str) -> bool:
    cleaned = value.strip().strip("`*_-").strip()
    return bool(cleaned) and not PLACEHOLDER_RE.fullmatch(cleaned)


def _split_sections(markdown: str) -> tuple[dict[str, str], list[str]]:
    matches = list(H2_RE.finditer(markdown))
    sections: dict[str, str] = {}
    duplicates: list[str] = []
    for index, match in enumerate(matches):
        name = match.group(1).strip()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        if name in sections:
            duplicates.append(name)
        sections[name] = markdown[match.end() : end].strip()
    return sections, duplicates


def _split_records(section: str) -> list[tuple[str, str]]:
    matches = list(H3_RE.finditer(section))
    records: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(section)
        records.append((match.group(1).strip(), section[match.end() : end].strip()))
    return records


def _labeled_fields(body: str) -> dict[str, str]:
    aliases = {
        "method used": "method",
        "improvement note": "improvement",
    }
    result: dict[str, str] = {}
    for match in FIELD_RE.finditer(body):
        label = match.group("label").strip().lower()
        result[aliases.get(label, label)] = match.group("value").strip()
    return result


def _validate_chatbot_records(
    records: list[tuple[str, str]], errors: list[str]
) -> None:
    required = ("method", "query", "answer", "quality", "improvement")
    for index, (heading, body) in enumerate(records, start=1):
        question = re.sub(r"^Q\d+\s*:\s*", "", heading, flags=re.IGNORECASE).strip()
        if not _is_substantive(question):
            errors.append(f"record {index}: missing substantive question")
        fields = _labeled_fields(body)
        for field in required:
            if field not in fields or not _is_substantive(fields[field]):
                errors.append(f"record {index}: missing substantive {field}")


def _validate_analytical_records(
    records: list[tuple[str, str]], errors: list[str]
) -> None:
    for index, (heading, body) in enumerate(records, start=1):
        use_case = re.sub(r"^Use case\s*:\s*", "", heading, flags=re.IGNORECASE).strip()
        if not _is_substantive(use_case):
            errors.append(f"record {index}: missing substantive use_case")
        cypher = re.search(r"```cypher\s*\n(.+?)```", body, flags=re.DOTALL | re.IGNORECASE)
        if not cypher or not _is_substantive(cypher.group(1)):
            errors.append(f"record {index}: missing substantive cypher")
        fields = _labeled_fields(body)
        for field in ("results", "coverage"):
            if field not in fields or not _is_substantive(fields[field]):
                errors.append(f"record {index}: missing substantive {field}")


def validate_report(
    report_markdown: str,
    report_type: str,
    expected_records: int,
    pdf_data_present: bool = False,
) -> ValidationResult:
    """Validate one report and return every deterministic contract failure."""
    contracts = load_contracts()
    if report_type not in ACTIVE_REPORT_TYPES:
        supported = ", ".join(sorted(ACTIVE_REPORT_TYPES))
        raise ValueError(f"Unknown report type {report_type!r}; expected one of: {supported}")
    if expected_records < 1:
        raise ValueError("expected_records must be at least 1")

    contract = contracts[report_type]
    sections, duplicates = _split_sections(report_markdown)
    errors = [f"duplicate section: {name}" for name in duplicates]

    required_sections = list(contract.get("required_sections", []))
    for conditional in contract.get("conditional_sections", []):
        if conditional.get("when") == "pdf_data_present" and pdf_data_present:
            required_sections.append(conditional["section"])

    for name in required_sections:
        if name not in sections:
            errors.append(f"missing section: {name}")
        elif not _is_substantive(sections[name]):
            errors.append(f"empty or placeholder section: {name}")

    source_data = sections.get("Source Data", "")
    count_pattern = r"^\s*[-*]\s+.+\b\d+\s+(?:records?|rows?|chunks?|pages?|files?)\b"
    if source_data and not re.search(count_pattern, source_data, flags=re.MULTILINE | re.IGNORECASE):
        errors.append("Source Data must list at least one source with a numeric record/chunk count")

    graph_model = sections.get("Graph Data Model", "")
    if graph_model and "```mermaid" not in graph_model.lower():
        errors.append("Graph Data Model must include a Mermaid diagram")

    record_section = contract.get("repeated_record", {}).get("section")
    records = _split_records(sections.get(record_section, "")) if record_section else []
    if len(records) != expected_records:
        errors.append(f"expected {expected_records} repeated records, found {len(records)}")

    if report_type == "chatbot_report":
        _validate_chatbot_records(records, errors)
    elif report_type == "analytical_report":
        _validate_analytical_records(records, errors)

    return ValidationResult(
        valid=not errors,
        report_type=report_type,
        expected_records=expected_records,
        records_found=len(records),
        errors=errors,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="Markdown report to validate")
    parser.add_argument("--type", required=True, dest="report_type")
    parser.add_argument("--expected-records", required=True, type=int)
    parser.add_argument("--pdf-data-present", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = validate_report(
            args.report.read_text(encoding="utf-8"),
            args.report_type,
            args.expected_records,
            args.pdf_data_present,
        )
    except (OSError, ValueError, yaml.YAMLError) as error:
        print(json.dumps({"valid": False, "errors": [str(error)]}, indent=2))
        return 2
    print(json.dumps(result.to_dict(), indent=2))
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
