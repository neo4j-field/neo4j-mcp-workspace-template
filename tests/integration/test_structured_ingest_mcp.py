"""Opt-in integration test for structured ingestion through the live MCP tool.

Run only against a disposable/empty Neo4j database.  Every fixture element is
owned by TEST_RUN_ID and teardown deletes only elements with that property.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path

from fastmcp import Client
from mcp_neo4j_ingest.server import driver, ingest_mcp, setup


RUN_INTEGRATION = os.getenv("NEO4J_MCP_RUN_INTEGRATION") == "1"
TEST_RUN_ID = "contract-test-20260910"
COMPILER_TEST_RUN_ID = "ingest-001-integration-20260910"
DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/structured"


PEOPLE_QUERY = """
UNWIND $records AS record
MERGE (n:ContractTestPerson {
  testRunId: record.testRunId,
  personId: record.personId
})
SET n.name = record.name
"""

PROJECTS_QUERY = """
UNWIND $records AS record
MERGE (n:ContractTestProject {
  testRunId: record.testRunId,
  projectId: record.projectId
})
SET n.title = record.title
"""

ASSIGNMENTS_QUERY = """
UNWIND $records AS record
MATCH (source:ContractTestPerson {
  testRunId: record.testRunId,
  personId: record.sourceId
})
MATCH (target:ContractTestProject {
  testRunId: record.testRunId,
  projectId: record.targetId
})
MERGE (source)-[relationship:CONTRACT_TEST_ASSIGNED_TO {
  testRunId: record.testRunId
}]->(target)
SET relationship.role = record.role
"""

COMPILER_PERSON = {
    "label": "Ingest001Person",
    "key_property": {
        "name": "personId",
        "type": "STRING",
        "source": {"column_name": "person_id"},
    },
    "properties": [
        {"name": "displayName", "type": "STRING", "source": {"column_name": "display_name"}},
        {"name": "yearsActive", "type": "INTEGER", "source": {"column_name": "years_active"}},
        {"name": "testRunId", "type": "STRING", "source": {"column_name": "test_run_id"}},
    ],
}
COMPILER_PROJECT = {
    "label": "Ingest001Project",
    "key_property": {
        "name": "projectId",
        "type": "STRING",
        "source": {"column_name": "project_id"},
    },
    "properties": [
        {"name": "title", "type": "STRING", "source": {"column_name": "project_title"}},
        {"name": "testRunId", "type": "STRING", "source": {"column_name": "test_run_id"}},
    ],
}
COMPILER_RELATIONSHIP = {
    "type": "INGEST001_ASSIGNED_TO",
    "start_node_label": "Ingest001Person",
    "end_node_label": "Ingest001Project",
    "properties": [
        {"name": "role", "type": "STRING", "source": {"column_name": "assignment_role"}},
        {"name": "testRunId", "type": "STRING", "source": {"column_name": "test_run_id"}},
    ],
}
COMPILER_DATA_MODEL = {
    "nodes": [COMPILER_PERSON, COMPILER_PROJECT],
    "relationships": [COMPILER_RELATIONSHIP],
}


@unittest.skipUnless(
    RUN_INTEGRATION,
    "set NEO4J_MCP_RUN_INTEGRATION=1 to run against the configured Neo4j database",
)
class StructuredIngestMCPIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await setup()
        self.client = Client(ingest_mcp)
        await self.client.__aenter__()
        await self._cleanup_fixture()

    async def asyncTearDown(self) -> None:
        await self._cleanup_fixture()
        await self.client.__aexit__(None, None, None)

    async def _cleanup_fixture(self) -> None:
        async with driver.session(database=DATABASE) as session:
            await session.run(
                "MATCH (n) WHERE n.testRunId IN $testRunIds DETACH DELETE n",
                testRunIds=[TEST_RUN_ID, COMPILER_TEST_RUN_ID],
            )

    async def _ingest(self, filename: str, query: str) -> None:
        result = await self.client.call_tool(
            "ingest_csv_into_neo4j",
            {
                "query": query,
                "params": {"csv_path": str((FIXTURES / filename).resolve())},
            },
        )
        self.assertFalse(result.is_error, result)

    async def _ingest_fixture(self) -> None:
        await self._ingest("contract_people.csv", PEOPLE_QUERY)
        await self._ingest("contract_projects.csv", PROJECTS_QUERY)
        await self._ingest("contract_assignments.csv", ASSIGNMENTS_QUERY)

    async def _compile_node(self, node: dict) -> str:
        result = await self.client.call_tool("compile_node_ingest_query", {"node": node})
        self.assertFalse(result.is_error, result)
        return result.data

    async def test_ingest_is_idempotent_and_preserves_relationship_properties(self) -> None:
        await self._ingest_fixture()
        await self._ingest_fixture()

        async with driver.session(database=DATABASE) as session:
            result = await session.run(
                """
                MATCH (person:ContractTestPerson {testRunId: $testRunId})
                OPTIONAL MATCH (person)-[assignment:CONTRACT_TEST_ASSIGNED_TO {
                  testRunId: $testRunId
                }]->(project:ContractTestProject {testRunId: $testRunId})
                WITH count(DISTINCT person) AS people,
                     count(DISTINCT project) AS projects,
                     count(DISTINCT assignment) AS assignments,
                     collect(DISTINCT assignment.role) AS roles
                MATCH (owned {testRunId: $testRunId})
                RETURN people, projects, assignments, roles,
                       count(owned) AS ownedNodes,
                       count(CASE WHEN NOT (owned)--() THEN 1 END) AS orphans
                """,
                testRunId=TEST_RUN_ID,
            )
            record = await result.single(strict=True)

        self.assertEqual(2, record["people"])
        self.assertEqual(1, record["projects"])
        self.assertEqual(2, record["assignments"])
        self.assertEqual({"architect", "reviewer"}, set(record["roles"]))
        self.assertEqual(3, record["ownedNodes"])
        self.assertEqual(0, record["orphans"])

        person_query = await self._compile_node(COMPILER_PERSON)
        project_query = await self._compile_node(COMPILER_PROJECT)
        relationship_result = await self.client.call_tool(
            "compile_relationship_ingest_query",
            {
                "data_model": COMPILER_DATA_MODEL,
                "relationship": COMPILER_RELATIONSHIP,
            },
        )
        self.assertFalse(relationship_result.is_error, relationship_result)

        await self._ingest("ingest001_people.csv", person_query)
        await self._ingest("ingest001_projects.csv", project_query)
        await self._ingest("ingest001_assignments.csv", relationship_result.data)

        async with driver.session(database=DATABASE) as session:
            result = await session.run(
                """
                MATCH (person:Ingest001Person {testRunId: $testRunId})
                      -[assignment:INGEST001_ASSIGNED_TO {testRunId: $testRunId}]->
                      (project:Ingest001Project {testRunId: $testRunId})
                RETURN count(DISTINCT person) AS people,
                       count(DISTINCT project) AS projects,
                       count(DISTINCT assignment) AS assignments,
                       collect(DISTINCT assignment.role) AS roles,
                       collect(DISTINCT person.yearsActive) AS yearsActive,
                       count(project.role) AS misplacedProjectRoles
                """,
                testRunId=COMPILER_TEST_RUN_ID,
            )
            compiler_record = await result.single(strict=True)

        self.assertEqual(2, compiler_record["people"])
        self.assertEqual(1, compiler_record["projects"])
        self.assertEqual(2, compiler_record["assignments"])
        self.assertEqual({"architect", "reviewer"}, set(compiler_record["roles"]))
        self.assertEqual({7, 11}, set(compiler_record["yearsActive"]))
        self.assertEqual(0, compiler_record["misplacedProjectRoles"])


if __name__ == "__main__":
    unittest.main()
