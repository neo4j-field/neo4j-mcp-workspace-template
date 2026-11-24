"""Contract tests joining MCP server implementations to published skills.

These tests intentionally use only the Python standard library.  They are the
fast, dependency-free release gate for documentation/tool drift; runtime MCP
smoke tests belong in the integration layer that follows.
"""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
LEXICAL_SERVER = REPO_ROOT / "mcp-neo4j-lexical-graph/src/mcp_neo4j_lexical_graph/server.py"
ENTITY_SERVER = REPO_ROOT / "mcp-neo4j-entity-graph/src/mcp_neo4j_entity_graph/server.py"
ONTOLOGY_LOADER = REPO_ROOT / "mcp-neo4j-entity-graph/src/mcp_neo4j_entity_graph/ontology_loader.py"
ONTOLOGY_FIXTURE = REPO_ROOT / "tests/fixtures/ontology/wf004_ontology.cypher"
ONTOLOGY_VALIDATOR = (
    REPO_ROOT / "skills/build-ontology-driven-graph/scripts/validate_ontology.cypher"
)
CODING_AGENT_SKILL = REPO_ROOT / ".agents/skills/develop-neo4j-graph/SKILL.md"
DESKTOP_SKILL = REPO_ROOT / "skills/build-ontology-driven-graph/SKILL.md"
DESKTOP_SKILL_ROOT = DESKTOP_SKILL.parent
STRUCTURED_DATA_GUIDE = (
    REPO_ROOT / ".agents/skills/develop-neo4j-graph/references/HANDLE_STRUCTURED_DATA.md"
)
REPORT_CONTRACT = (
    REPO_ROOT / "mcp-neo4j-proxy/src/mcp_neo4j_proxy/report_contracts.yaml"
)
PROXY_SERVER = REPO_ROOT / "mcp-neo4j-proxy/src/mcp_neo4j_proxy/server.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _function_parameters(path: Path, function_name: str) -> set[str]:
    """Return parameter names for a function, including nested MCP tools."""
    tree = ast.parse(_read(path), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            return {argument.arg for argument in node.args.args}
    raise AssertionError(f"Could not find {function_name!r} in {path}")


def _desktop_skill_corpus() -> str:
    return "\n".join(_read(path) for path in sorted(DESKTOP_SKILL_ROOT.rglob("*.md")))


def _documented_keyword_arguments(markdown: str, tool_name: str) -> list[set[str]]:
    """Extract keyword arguments from documented Python-like tool calls."""
    matches = list(re.finditer(rf"{re.escape(tool_name)}\((.*?)\)", markdown, flags=re.DOTALL))
    if not matches:
        raise AssertionError(f"No documented {tool_name} call found")
    calls = []
    for match in matches:
        call = ast.parse(f"{tool_name}({match.group(1)})", mode="eval").body
        if not isinstance(call, ast.Call):
            raise AssertionError(f"Documented {tool_name} example is not a call")
        calls.append({keyword.arg for keyword in call.keywords if keyword.arg is not None})
    return calls


class WorkflowContractTests(unittest.TestCase):
    def test_desktop_lexical_call_matches_server_parameters(self) -> None:
        """WF-001: Desktop must use the lexical server's actual required names."""
        server_parameters = _function_parameters(LEXICAL_SERVER, "create_lexical_graph")
        documented_calls = _documented_keyword_arguments(
            _desktop_skill_corpus(), "create_lexical_graph"
        )

        for documented_parameters in documented_calls:
            with self.subTest(parameters=documented_parameters):
                self.assertEqual(set(), documented_parameters - server_parameters)
                self.assertTrue(
                    {"path", "output_dir"}.issubset(documented_parameters),
                    "Desktop lexical ingestion must supply the required path and output_dir",
                )

    def test_extraction_schema_is_python_end_to_end(self) -> None:
        """WF-002: converter output and extractor input must both be .py files."""
        skill = _read(CODING_AGENT_SKILL)
        converter_parameters = _function_parameters(ENTITY_SERVER, "convert_schema")
        extractor_parameters = _function_parameters(ENTITY_SERVER, "extract_entities")

        self.assertIn("output_path", converter_parameters)
        self.assertIn("schema", extractor_parameters)
        self.assertNotIn("<topic>_schema.json", skill)
        self.assertIn("outputs/schemas/<topic>_schema.py", skill)
        self.assertIn("Pydantic `.py` schema", skill)

    def test_desktop_uses_canonical_embedding_property(self) -> None:
        """WF-003: verification must check the property written by embed_chunks."""
        lexical_source = _read(LEXICAL_SERVER)
        desktop_skill = _desktop_skill_corpus()

        self.assertIn('embedding_prop = "text_embedding"', lexical_source)
        self.assertIn("count(c.text_embedding) AS embedded", desktop_skill)
        self.assertNotIn("count(c.embedding) AS embedded", desktop_skill)

    def test_desktop_uses_ontology_ownership_relationship(self) -> None:
        """WF-004: all Desktop ontology artifacts use the loader's contract."""
        loader_source = _read(ONTOLOGY_LOADER)
        desktop_corpus = _desktop_skill_corpus()
        fixture = _read(ONTOLOGY_FIXTURE)
        validator = _read(ONTOLOGY_VALIDATOR)

        self.assertIn("[:CONTAINS]->(rt:RelationshipType)", loader_source)
        self.assertIn("[:CONTAINS]->(nt:NodeType)", loader_source)
        self.assertNotIn(":HAS_NODE_TYPE", desktop_corpus)
        self.assertNotIn(":HAS_RELATIONSHIP_TYPE", desktop_corpus)
        self.assertIn("[:CONTAINS]->(nt:NodeType)", desktop_corpus)
        self.assertIn("[:CONTAINS]->(rt:RelationshipType)", desktop_corpus)

        for relationship_type in {
            "CONTAINS",
            "DEFINES",
            "HAS_PROPERTY",
            "FROM",
            "TO",
            "USES_ALIAS_MAP",
            "USES_BLOCKLIST",
            "HAS_ALIAS",
            "HAS_TERM",
        }:
            with self.subTest(relationship_type=relationship_type):
                self.assertIn(f"[:{relationship_type}]", fixture)

        self.assertIn("[:CONTAINS]->(nt:NodeType)", validator)
        self.assertIn("[:CONTAINS]->(rt:RelationshipType)", validator)
        self.assertIn("[:FROM]->(:NodeType)", validator)
        self.assertIn("[:TO]->(:NodeType)", validator)

    def test_structured_ingestion_uses_owned_safe_compiler(self) -> None:
        """Contain both pinned modeling-server ingest-query defects."""
        guide = _read(STRUCTURED_DATA_GUIDE)

        self.assertIn("compile_node_ingest_query(node=...)", guide)
        self.assertIn("compile_relationship_ingest_query(data_model=..., relationship=...)", guide)
        self.assertIn("declared `source.column_name`", guide)
        self.assertIn("MERGE (start)-[relationship:ASSIGNED_TO]->(end)", guide)
        self.assertIn("SET relationship.role = record.role", guide)
        self.assertIn("never generates the known-bad upstream shape", guide)

    def test_report_contract_has_one_packaged_source_of_truth(self) -> None:
        self.assertTrue(REPORT_CONTRACT.is_file())
        self.assertFalse((REPO_ROOT / "tests/skill-evals/report-contracts.yaml").exists())

    def test_both_skills_require_deterministic_report_validation(self) -> None:
        coding_skill = _read(CODING_AGENT_SKILL)
        desktop_skill = _read(DESKTOP_SKILL)
        coding_skill_normalized = " ".join(coding_skill.lower().split())
        desktop_skill_normalized = " ".join(desktop_skill.lower().split())

        self.assertIn("neo4j-validate-report", coding_skill)
        self.assertIn("do not claim completion until it passes", coding_skill_normalized)
        self.assertIn("validate_workflow_report", desktop_skill)
        self.assertIn(
            "do not claim completion until it returns `valid: true`",
            desktop_skill_normalized,
        )

    def test_desktop_proxy_exposes_report_validator(self) -> None:
        parameters = _function_parameters(PROXY_SERVER, "validate_workflow_report")
        self.assertEqual(
            {"report_markdown", "report_type", "expected_records", "pdf_data_present"},
            parameters,
        )
        self.assertIn("@app.tool", _read(PROXY_SERVER))


if __name__ == "__main__":
    unittest.main()
