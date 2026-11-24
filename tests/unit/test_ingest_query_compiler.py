"""Regression tests for safe model-to-ingest Cypher compilation."""

from __future__ import annotations

import unittest

from mcp_neo4j_ingest.query_compiler import (
    IngestModelError,
    compile_node_ingest_query,
    compile_relationship_ingest_query,
)


PERSON = {
    "label": "Ingest001Person",
    "key_property": {
        "name": "personId",
        "type": "STRING",
        "source": {"column_name": "person_id"},
    },
    "properties": [
        {
            "name": "displayName",
            "type": "STRING",
            "source": {"column_name": "display_name"},
        },
        {
            "name": "yearsActive",
            "type": "INTEGER",
            "source": {"column_name": "years_active"},
        },
        {
            "name": "testRunId",
            "type": "STRING",
            "source": {"column_name": "test_run_id"},
        },
    ],
}

PROJECT = {
    "label": "Ingest001Project",
    "key_property": {
        "name": "projectId",
        "type": "STRING",
        "source": {"column_name": "project_id"},
    },
    "properties": [
        {
            "name": "title",
            "type": "STRING",
            "source": {"column_name": "project_title"},
        },
        {
            "name": "testRunId",
            "type": "STRING",
            "source": {"column_name": "test_run_id"},
        },
    ],
}

ASSIGNED_TO = {
    "type": "INGEST001_ASSIGNED_TO",
    "start_node_label": "Ingest001Person",
    "end_node_label": "Ingest001Project",
    "properties": [
        {
            "name": "role",
            "type": "STRING",
            "source": {"column_name": "assignment_role"},
        },
        {
            "name": "testRunId",
            "type": "STRING",
            "source": {"column_name": "test_run_id"},
        },
    ],
}

DATA_MODEL = {"nodes": [PERSON, PROJECT], "relationships": [ASSIGNED_TO]}


class NodeQueryCompilerTests(unittest.TestCase):
    def test_uses_declared_source_columns_and_property_type_casts(self) -> None:
        query = compile_node_ingest_query(PERSON)

        self.assertIn("personId: record.person_id", query)
        self.assertIn("node.displayName = record.display_name", query)
        self.assertIn("node.yearsActive = toInteger(record.years_active)", query)
        self.assertNotIn("record.personId", query)
        self.assertNotIn("record.displayName", query)

    def test_rejects_unsafe_model_and_source_identifiers(self) -> None:
        unsafe_cases = [
            {**PERSON, "label": "Person`) MATCH (n) DETACH DELETE n //"},
            {
                **PERSON,
                "key_property": {**PERSON["key_property"], "name": "person-id"},
            },
            {
                **PERSON,
                "key_property": {
                    **PERSON["key_property"],
                    "source": {"column_name": "person id"},
                },
            },
        ]

        for node in unsafe_cases:
            with self.subTest(node=node), self.assertRaises(IngestModelError):
                compile_node_ingest_query(node)


class RelationshipQueryCompilerTests(unittest.TestCase):
    def test_binds_relationship_and_sets_properties_on_it(self) -> None:
        query = compile_relationship_ingest_query(DATA_MODEL, ASSIGNED_TO)

        self.assertIn("personId: record.person_id", query)
        self.assertIn("projectId: record.project_id", query)
        self.assertIn(
            "MERGE (start)-[relationship:INGEST001_ASSIGNED_TO]->(end)", query
        )
        self.assertIn("relationship.role = record.assignment_role", query)
        self.assertNotIn("SET end.", query)
        self.assertNotIn("SET end +=", query)

    def test_rejects_unsafe_relationship_type(self) -> None:
        relationship = {**ASSIGNED_TO, "type": "ASSIGNED_TO]->(x) DETACH DELETE x //"}

        with self.assertRaises(IngestModelError):
            compile_relationship_ingest_query(DATA_MODEL, relationship)


if __name__ == "__main__":
    unittest.main()
