"""Deterministic unit coverage for BUG-002 relationship persistence."""

from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from fastmcp import Client

from mcp_neo4j_entity_graph.models import (
    ChunkExtractionResult,
    ExtractedEntity,
    ExtractedRelationship,
)
from mcp_neo4j_entity_graph.server import create_mcp_server


TEST_RUN_ID = "bug002-unit-regression"
PERSON_ID = f"{TEST_RUN_ID}-person"
PROJECT_ID = f"{TEST_RUN_ID}-project"
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "fixtures/entity/bug002_schema.py"


class _FakeResult:
    def __init__(self, *, rows=None, record=None):
        self._rows = rows or []
        self._record = record

    async def data(self):
        return self._rows

    async def single(self):
        return self._record


class _FakeSession:
    def __init__(self, graph):
        self.graph = graph

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def run(self, query, **params):
        if "eligible_sources" in query:
            return _FakeResult(record={"eligible_sources": 2})

        if "MATCH (n:Bug002Source)" in query:
            return _FakeResult(
                rows=[
                    {
                        "id": f"{TEST_RUN_ID}-relationship-chunk",
                        "text": "Person is assigned to project.",
                        "type": "text",
                        "isPage": False,
                    },
                    {
                        "id": f"{TEST_RUN_ID}-target-chunk",
                        "text": "Project details.",
                        "type": "text",
                        "isPage": False,
                    },
                ]
            )

        if "$entities" in query:
            if "MERGE (e:Bug002Person" in query:
                label = "Bug002Person"
            elif "MERGE (e:Bug002Project" in query:
                label = "Bug002Project"
            else:
                raise AssertionError(query)
            for entity in params["entities"]:
                self.graph["nodes"].add((label, entity["key_value"]))
            return _FakeResult(
                record={
                    "entities_created": len(params["entities"]),
                    "rels_created": len(params["entities"]),
                }
            )

        if "$relationships" in query:
            created = 0
            for relationship in params["relationships"]:
                source = (relationship["source_label"], relationship["source_key_value"])
                target = (relationship["target_label"], relationship["target_key_value"])
                if source in self.graph["nodes"] and target in self.graph["nodes"]:
                    self.graph["relationships"].add(
                        (source, relationship["type"], target)
                    )
                    created += 1
            return _FakeResult(record={"created": created})

        if "sources_persisted" in query:
            return _FakeResult(
                record={"sources_persisted": len(params["source_ids"])}
            )

        raise AssertionError(query)


class _FakeDriver:
    def __init__(self):
        self.graph = {"nodes": set(), "relationships": set()}

    def session(self, **_kwargs):
        return _FakeSession(self.graph)


class EntityRelationshipPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def _stub_extract(self, chunk, _schema, _output_model):
        if chunk.id.endswith("relationship-chunk"):
            return ChunkExtractionResult(
                chunk_id=chunk.id,
                entities=[
                    ExtractedEntity(
                        label="Bug002Person", properties={"personId": PERSON_ID}
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

        await asyncio.sleep(0.01)
        return ChunkExtractionResult(
            chunk_id=chunk.id,
            entities=[
                ExtractedEntity(
                    label="Bug002Project", properties={"projectId": PROJECT_ID}
                )
            ],
        )

    async def test_relationship_waits_for_entities_from_later_batches(self) -> None:
        driver = _FakeDriver()
        server = create_mcp_server(driver)

        with patch(
            "mcp_neo4j_entity_graph.server.TextExtractor.extract_chunk",
            new=self._stub_extract,
        ):
            async with Client(server) as client:
                result = await client.call_tool(
                    "extract_entities",
                    {
                        "schema": str(SCHEMA_PATH),
                        "source_label": "Bug002Source",
                        "force": True,
                        "batch_size": 1,
                        "text_parallel": 2,
                    },
                )
                started = json.loads(result.content[0].text)

                for _ in range(100):
                    status_result = await client.call_tool(
                        "check_extraction_status", {"job_id": started["job_id"]}
                    )
                    status = json.loads(status_result.content[0].text)
                    if status["status"] in {"complete", "failed"}:
                        break
                    await asyncio.sleep(0.005)
                else:
                    self.fail("BUG-002 unit extraction job did not finish")

        self.assertEqual("complete", status["status"], status)
        self.assertEqual(1, status["relationships_created"])
        self.assertEqual(
            {
                (
                    ("Bug002Person", PERSON_ID),
                    "BUG002_ASSIGNED_TO",
                    ("Bug002Project", PROJECT_ID),
                )
            },
            driver.graph["relationships"],
        )


if __name__ == "__main__":
    unittest.main()
