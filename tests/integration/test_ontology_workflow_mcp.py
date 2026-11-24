"""WF-004 live ontology workflow contract.

Runs the Desktop setup, canonical fixture write, documented read-back queries,
validator, and schema compiler against Neo4j without model/API calls. Mutable
data is tagged with one run id and removed exactly; the retained golden graph is
snapshotted before and after.
"""

from __future__ import annotations

import json
import os
import unittest
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastmcp import Client
from neo4j import AsyncGraphDatabase
from platformdirs import user_cache_dir

from mcp_neo4j_entity_graph.server import create_mcp_server


REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")

RUN_INTEGRATION = os.getenv("NEO4J_MCP_RUN_INTEGRATION") == "1"
DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")
FIXTURE_QUERY = (
    REPO_ROOT / "tests/fixtures/ontology/wf004_ontology.cypher"
).read_text(encoding="utf-8")
VALIDATOR_QUERY = (
    REPO_ROOT / "skills/build-ontology-driven-graph/scripts/validate_ontology.cypher"
).read_text(encoding="utf-8")

ENTITY_SUMMARY_QUERY = """
MATCH (o:Ontology {name: $name})-[:CONTAINS]->(nt:NodeType)
OPTIONAL MATCH (nt)-[:HAS_PROPERTY]->(pd:PropertyDef)
RETURN nt.name AS entity, nt.description AS description,
       collect(pd.name) AS properties
ORDER BY entity
"""

RELATIONSHIP_SUMMARY_QUERY = """
MATCH (o:Ontology {name: $name})-[:CONTAINS]->(rt:RelationshipType)
MATCH (rt)-[:FROM]->(src:NodeType), (rt)-[:TO]->(dst:NodeType)
RETURN rt.name AS relationship, src.name AS source, dst.name AS target,
       rt.description AS description
ORDER BY relationship
"""


@unittest.skipUnless(
    RUN_INTEGRATION,
    "set NEO4J_MCP_RUN_INTEGRATION=1 to run against the configured Neo4j database",
)
class OntologyWorkflowMCPIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        suffix = uuid.uuid4().hex[:10]
        self.test_run_id = f"wf004-ontology-contract-{suffix}"
        self.ontology_name = f"{self.test_run_id}-ontology"
        self.names = {
            "ontologyName": self.ontology_name,
            "testRunId": self.test_run_id,
            "agreementType": f"Wf004Agreement{suffix}",
            "agreementKey": f"wf004AgreementId{suffix}",
            "jurisdictionProperty": f"wf004Jurisdiction{suffix}",
            "partyType": f"Wf004Party{suffix}",
            "partyKey": f"wf004PartyName{suffix}",
            "relationshipType": f"WF004_SIGNED_{suffix.upper()}",
            "relationshipProperty": f"wf004SignedDate{suffix}",
            "aliasMap": f"WF004_JURISDICTIONS_{suffix.upper()}",
            "blocklist": f"WF004_NON_PARTIES_{suffix.upper()}",
        }
        self.driver = AsyncGraphDatabase.driver(
            os.environ["NEO4J_URI"],
            auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
        )
        self.golden_before = await self._golden_snapshot()
        self.server = create_mcp_server(
            self.driver,
            database=DATABASE,
            ontology_database=DATABASE,
        )
        self.client = Client(self.server)
        await self.client.__aenter__()

    async def asyncTearDown(self) -> None:
        await self.client.__aexit__(None, None, None)
        async with self.driver.session(database=DATABASE) as session:
            await session.run(
                "MATCH (n {testRunId: $testRunId}) DETACH DELETE n",
                testRunId=self.test_run_id,
            )
        (
            Path(user_cache_dir("mcp-neo4j-entity-graph"))
            / "schemas"
            / f"{self.ontology_name}.py"
        ).unlink(missing_ok=True)
        self.assertEqual(self.golden_before, await self._golden_snapshot())
        await self.driver.close()

    async def _golden_snapshot(self) -> tuple[int, int]:
        async with self.driver.session(database=DATABASE) as session:
            result = await session.run(
                """
                MATCH (n)
                WHERE any(k IN keys(n) WHERE
                          toString(n[k]) CONTAINS 'golden-e2e-20260910')
                   OR coalesce(n.id, '') STARTS WITH 'golden-e2e-20260910'
                   OR coalesce(n.sourceId, '') STARTS WITH 'golden-e2e-20260910'
                WITH collect(n) AS nodes
                UNWIND nodes AS n
                OPTIONAL MATCH (n)-[r]-()
                RETURN count(DISTINCT n) AS nodes,
                       count(DISTINCT r) AS relationships
                """
            )
            record = await result.single(strict=True)
            return record["nodes"], record["relationships"]

    async def _rows(self, query: str, **params: object) -> list[dict[str, object]]:
        async with self.driver.session(database=DATABASE) as session:
            result = await session.run(query, **params)
            return [record.data() async for record in result]

    async def test_desktop_ontology_setup_write_verify_and_generate(self) -> None:
        setup_result = await self.client.call_tool("setup_ontology_db", {})
        self.assertFalse(setup_result.is_error, setup_result)
        setup = json.loads(setup_result.content[0].text)
        self.assertEqual("success", setup["status"])
        self.assertEqual(DATABASE, setup["database"])

        async with self.driver.session(database=DATABASE) as session:
            result = await session.run(FIXTURE_QUERY, **self.names)
            await result.consume()

        # These are the two exact read-back shapes documented in Desktop Phase 4.
        entities = await self._rows(
            ENTITY_SUMMARY_QUERY, name=self.ontology_name
        )
        relationships = await self._rows(
            RELATIONSHIP_SUMMARY_QUERY, name=self.ontology_name
        )
        self.assertEqual(
            [self.names["agreementType"], self.names["partyType"]],
            [row["entity"] for row in entities],
        )
        self.assertEqual(
            [
                {
                    "relationship": self.names["relationshipType"],
                    "source": self.names["partyType"],
                    "target": self.names["agreementType"],
                    "description": "Connects a party to an agreement they signed",
                }
            ],
            relationships,
        )

        issues = await self._rows(VALIDATOR_QUERY, name=self.ontology_name)
        self.assertEqual([], issues)

        canonical = await self._rows(
            """
            MATCH (o:Ontology {name: $name})-[r]->()
            WITH o, collect(DISTINCT type(r)) AS rootRelationships
            MATCH (o)-[:CONTAINS]->(rt:RelationshipType)
            MATCH (rt)-[:FROM]->(:NodeType), (rt)-[:TO]->(:NodeType)
            RETURN rootRelationships,
                   count(rt) AS relationshipTypes
            """,
            name=self.ontology_name,
        )
        self.assertEqual(1, canonical[0]["relationshipTypes"])
        self.assertEqual(
            {"CONTAINS", "DEFINES"}, set(canonical[0]["rootRelationships"])
        )

        generated_result = await self.client.call_tool(
            "generate_schema_from_ontology",
            {"ontology_name": self.ontology_name},
        )
        self.assertFalse(generated_result.is_error, generated_result)
        generated = json.loads(generated_result.content[0].text)
        self.assertEqual("success", generated["status"])
        self.assertEqual(2, generated["entity_types"])
        self.assertEqual(1, generated["relationship_types"])
        self.assertIn(self.names["agreementType"], generated["schema_content"])
        self.assertIn(self.names["partyType"], generated["schema_content"])
        self.assertIn(self.names["relationshipType"], generated["schema_content"])


if __name__ == "__main__":
    unittest.main()
