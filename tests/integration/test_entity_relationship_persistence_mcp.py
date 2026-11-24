"""Live BUG-002 regression: relationships survive cross-batch endpoint ordering.

The extractor is stubbed deterministically, so this test spends no model/API calls.
All mutable graph data uses a unique label/key namespace and is removed exactly.
"""

from __future__ import annotations

import asyncio
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from fastmcp import Client
from neo4j import AsyncGraphDatabase
from platformdirs import user_cache_dir

from mcp_neo4j_entity_graph.models import (
    ChunkExtractionResult,
    ExtractedEntity,
    ExtractedRelationship,
)
from mcp_neo4j_entity_graph.server import create_mcp_server


RUN_INTEGRATION = os.getenv("NEO4J_MCP_RUN_INTEGRATION") == "1"
DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")
TEST_RUN_ID = "bug002-live-regression-20260910"
SOURCE_LABEL = "Bug002Source"
ONTOLOGY_NAME = f"{TEST_RUN_ID}-ontology"
PERSON_ID = f"{TEST_RUN_ID}-person"
PROJECT_ID = f"{TEST_RUN_ID}-project"
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "fixtures/entity/bug002_schema.py"


@unittest.skipUnless(
    RUN_INTEGRATION,
    "set NEO4J_MCP_RUN_INTEGRATION=1 to run against the configured Neo4j database",
)
class EntityRelationshipPersistenceMCPIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.driver = AsyncGraphDatabase.driver(
            os.environ["NEO4J_URI"],
            auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
        )
        await self._cleanup_fixture()
        self.golden_before = await self._golden_snapshot()
        await self._create_fixture()
        self.server = create_mcp_server(
            self.driver,
            database=DATABASE,
            ontology_database=DATABASE,
        )
        self.client = Client(self.server)
        await self.client.__aenter__()

    async def asyncTearDown(self) -> None:
        await self.client.__aexit__(None, None, None)
        await self._cleanup_fixture()
        (
            Path(user_cache_dir("mcp-neo4j-entity-graph"))
            / "schemas"
            / f"{ONTOLOGY_NAME}.py"
        ).unlink(missing_ok=True)
        self.assertEqual(self.golden_before, await self._golden_snapshot())
        await self.driver.close()

    async def _cleanup_fixture(self) -> None:
        async with self.driver.session(database=DATABASE) as session:
            await session.run(
                "MATCH (claim:EntityExtractionClaim) WHERE claim.sourceLabel IN $labels DETACH DELETE claim",
                labels=['Bug002Source'],
            )
            await session.run(
                "MATCH (run:EntityExtractionRun) WHERE run.sourceLabel IN $labels DETACH DELETE run",
                labels=['Bug002Source'],
            )
            await session.run(
                """
                MATCH (n)
                WHERE n.testRunId = $testRunId
                   OR n.personId = $personId
                   OR n.projectId = $projectId
                DETACH DELETE n
                """,
                testRunId=TEST_RUN_ID,
                personId=PERSON_ID,
                projectId=PROJECT_ID,
            )

    async def _golden_snapshot(self) -> tuple[int, int]:
        async with self.driver.session(database=DATABASE) as session:
            result = await session.run(
                """
                MATCH (n)
                WHERE any(k IN keys(n) WHERE toStringOrNull(n[k]) CONTAINS 'golden-e2e-20260910')
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

    async def _create_fixture(self) -> None:
        async with self.driver.session(database=DATABASE) as session:
            await session.run(
                f"""
                CREATE (:{SOURCE_LABEL} {{
                    id: $relationshipChunkId,
                    type: 'text',
                    text: 'Person is assigned to project.',
                    testRunId: $testRunId
                }})
                CREATE (:{SOURCE_LABEL} {{
                    id: $targetChunkId,
                    type: 'text',
                    text: 'Project details.',
                    testRunId: $testRunId
                }})
                CREATE (ontology:Ontology {{
                    name: $ontologyName,
                    description: 'BUG-002 ontology-path fixture',
                    testRunId: $testRunId
                }})
                CREATE (personType:NodeType {{
                    name: 'Bug002Person',
                    description: 'BUG-002 person',
                    testRunId: $testRunId
                }})
                CREATE (personKey:PropertyDef {{
                    name: 'personId', type: 'STRING', required: true,
                    is_key: true, normalizer: 'whitespace', testRunId: $testRunId
                }})
                CREATE (projectType:NodeType {{
                    name: 'Bug002Project',
                    description: 'BUG-002 project',
                    testRunId: $testRunId
                }})
                CREATE (projectKey:PropertyDef {{
                    name: 'projectId', type: 'STRING', required: true,
                    is_key: true, normalizer: 'whitespace', testRunId: $testRunId
                }})
                CREATE (relationshipType:RelationshipType {{
                    name: 'BUG002_ASSIGNED_TO',
                    description: 'BUG-002 person assigned to project',
                    testRunId: $testRunId
                }})
                CREATE (ontology)-[:CONTAINS]->(personType)
                CREATE (ontology)-[:CONTAINS]->(projectType)
                CREATE (ontology)-[:CONTAINS]->(relationshipType)
                CREATE (personType)-[:HAS_PROPERTY]->(personKey)
                CREATE (projectType)-[:HAS_PROPERTY]->(projectKey)
                CREATE (relationshipType)-[:FROM]->(personType)
                CREATE (relationshipType)-[:TO]->(projectType)
                """,
                relationshipChunkId=f"{TEST_RUN_ID}-relationship-chunk",
                targetChunkId=f"{TEST_RUN_ID}-target-chunk",
                ontologyName=ONTOLOGY_NAME,
                testRunId=TEST_RUN_ID,
            )

    async def _stub_extract(self, chunk, _schema, _output_model):
        if chunk.id.endswith("relationship-chunk"):
            return ChunkExtractionResult(
                chunk_id=chunk.id,
                entities=[
                    ExtractedEntity(
                        label="Bug002Person",
                        properties={"personId": PERSON_ID, "testRunId": TEST_RUN_ID},
                    )
                ],
                relationships=[
                    ExtractedRelationship(
                        type="BUG002_ASSIGNED_TO",
                        source_label="Bug002Person",
                        source_key=PERSON_ID,
                        target_label="Bug002Project",
                        target_key=PROJECT_ID,
                    )
                ],
            )

        await asyncio.sleep(0.05)
        return ChunkExtractionResult(
            chunk_id=chunk.id,
            entities=[
                ExtractedEntity(
                    label="Bug002Project",
                    properties={"projectId": PROJECT_ID, "testRunId": TEST_RUN_ID},
                )
            ],
        )

    async def _run_extraction(self, schema_args: dict[str, str]) -> dict[str, object]:
        with patch(
            "mcp_neo4j_entity_graph.server.TextExtractor.extract_chunk",
            new=self._stub_extract,
        ):
            result = await self.client.call_tool(
                "extract_entities",
                {
                    **schema_args,
                    "source_label": SOURCE_LABEL,
                    "force": True,
                    "batch_size": 1,
                    "text_parallel": 2,
                },
            )
            self.assertFalse(result.is_error, result)
            started = json.loads(result.content[0].text)

            for _ in range(100):
                status_result = await self.client.call_tool(
                    "check_extraction_status", {"job_id": started["job_id"]}
                )
                status = json.loads(status_result.content[0].text)
                if status["status"] in {"complete", "failed"}:
                    break
                await asyncio.sleep(0.02)
            else:
                self.fail("BUG-002 extraction job did not finish")

        return status

    async def _assert_relationship_created(self, status: dict[str, object]) -> None:

        self.assertEqual("complete", status["status"], status)
        self.assertEqual(1, status["relationships_created"], status)

        async with self.driver.session(database=DATABASE) as session:
            graph_result = await session.run(
                """
                MATCH (:Bug002Person {personId: $personId})
                      -[r:BUG002_ASSIGNED_TO]->
                      (:Bug002Project {projectId: $projectId})
                RETURN count(r) AS relationships
                """,
                personId=PERSON_ID,
                projectId=PROJECT_ID,
            )
            record = await graph_result.single(strict=True)

        self.assertEqual(1, record["relationships"])

    async def test_file_schema_relationship_survives_later_endpoint_batch(self) -> None:
        status = await self._run_extraction({"schema": str(SCHEMA_PATH)})
        await self._assert_relationship_created(status)

    async def test_ontology_schema_relationship_survives_later_endpoint_batch(self) -> None:
        status = await self._run_extraction({"ontology_name": ONTOLOGY_NAME})
        await self._assert_relationship_created(status)


if __name__ == "__main__":
    unittest.main()
