"""N4 interoperability through MCP and atomic imports on a disposable database."""

import json
import os
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastmcp import Client
from neo4j import AsyncGraphDatabase
from mcp_neo4j_entity_graph.ontology_spec import (
    import_document,
    parse_document,
    validate_document,
)
from mcp_neo4j_entity_graph.base_extractor import load_extraction_output_model
from mcp_neo4j_entity_graph.server import create_mcp_server

# Shared synthetic fixture is independent of provider APIs and workspace data.
from tests.unit.test_ontology_spec import fixture

DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")


@unittest.skipUnless(
    os.getenv("NEO4J_MCP_RUN_INTEGRATION") == "1", "requires disposable Neo4j"
)
class OntologySpecIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.driver = AsyncGraphDatabase.driver(
            os.environ["NEO4J_URI"],
            auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
        )
        self.directory = tempfile.TemporaryDirectory()
        suffix = uuid4().hex
        base_names = [
            "n4-fixture",
            "n4-second",
            "N4Person",
            "N4Org",
            "N4_WORKS_AT",
            "N4Aliases",
            "N4Blocked",
        ]
        self.test_names = {name: f"{name}_{suffix}" for name in base_names}

        def unique_names(value):
            if isinstance(value, dict):
                return {
                    self.test_names.get(key, key): unique_names(item)
                    for key, item in value.items()
                }
            if isinstance(value, list):
                return [unique_names(item) for item in value]
            if isinstance(value, str):
                return self.test_names.get(value, value)
            return value

        self.document = unique_names(fixture())
        self.server = create_mcp_server(
            self.driver, database=DATABASE, ontology_database=DATABASE
        )
        async with Client(self.server) as client:
            await client.call_tool("setup_ontology_db", {})

    async def query(self, query, **params):
        async with self.driver.session(database=DATABASE) as session:
            return await (await session.run(query, **params)).data()

    async def cleanup(self):
        # Only this synthetic ontology's fixtures, never arbitrary user labels/data.
        await self.query(
            """MATCH (n) WHERE n.name IN $names
            AND (n:Ontology OR n:NodeType OR n:RelationshipType OR n:AliasMap OR n:Blocklist)
            OPTIONAL MATCH (n)-[:HAS_PROPERTY|HAS_ALIAS|HAS_TERM]->(child)
            WITH collect(DISTINCT n) + collect(DISTINCT child) AS nodes
            UNWIND nodes AS item DETACH DELETE item""",
            names=list(self.test_names.values()),
        )

    async def asyncTearDown(self):
        await self.cleanup()
        await self.driver.close()
        self.directory.cleanup()

    async def call(self, name, args):
        async with Client(self.server) as client:
            return (await client.call_tool(name, args)).content[0].text

    async def test_mcp_import_export_generate_and_normalization(self):
        original = self.document
        result = json.loads(
            await self.call("import_ontology_spec", {"content": json.dumps(original)})
        )
        self.assertEqual("success", result["status"])
        exported = parse_document(
            await self.call(
                "export_ontology_spec",
                {"ontology_name": original["id"], "format": "yaml"},
            )
        )
        expected = validate_document(original)
        actual = validate_document(exported)
        # Export canonicalizes spec-only ids but preserves extraction meaning.
        for payload in [expected, actual]:
            for key in ["nodes", "relationships"]:
                payload[key].sort(key=lambda row: row["name"])
                for row in payload[key]:
                    row["properties"].sort(key=lambda prop: prop["name"])
        for key in ["nodes", "relationships", "alias_maps", "blocklists"]:
            self.assertEqual(expected[key], actual[key])
        json_export = json.loads(
            await self.call(
                "export_ontology_spec",
                {"ontology_name": original["id"], "format": "json"},
            )
        )
        self.assertEqual(exported, json_export)
        with patch(
            "mcp_neo4j_entity_graph.server.user_cache_dir",
            return_value=self.directory.name,
        ):
            generated = json.loads(
                await self.call(
                    "generate_schema_from_ontology", {"ontology_name": original["id"]}
                )
            )
        output = load_extraction_output_model(generated["cache_path"])
        entities_field = next(
            name for name in output.model_fields if name.startswith("n4_person")
        )
        entity_type = output.model_fields[entities_field].annotation.__args__[0]
        person = entity_type.model_validate({"name": "  BOB ", "age": 32})
        self.assertEqual("robert", person.name)
        self.assertEqual(2, generated["entity_types"])
        self.assertEqual(1, generated["relationship_types"])

    async def test_collision_fails_before_any_new_ontology_write(self):
        await import_document(self.driver, DATABASE, self.document)
        second = {**self.document, "id": self.test_names["n4-second"]}
        with self.assertRaisesRegex(ValueError, "NodeType name"):
            await import_document(self.driver, DATABASE, second)
        self.assertEqual(
            0,
            (
                await self.query(
                    "MATCH (o:Ontology {name:$name}) RETURN count(o) AS n",
                    name=self.test_names["n4-second"],
                )
            )[0]["n"],
        )
        with self.assertRaisesRegex(ValueError, "Ontology name"):
            await import_document(self.driver, DATABASE, self.document)

    async def test_failure_after_initial_writes_rolls_back_whole_import(self):
        real_driver = self.driver

        class FailingTx:
            def __init__(self, tx):
                self.tx = tx

            async def run(self, query, **params):
                if "CREATE (t)-[:HAS_PROPERTY]" in query:
                    raise RuntimeError("injected property write failure")
                return await self.tx.run(query, **params)

        class FailingSession:
            async def __aenter__(self):
                self.session = real_driver.session(database=DATABASE)
                await self.session.__aenter__()
                return self

            async def __aexit__(self, *args):
                return await self.session.__aexit__(*args)

            async def execute_write(self, callback):
                async def wrapped(tx):
                    return await callback(FailingTx(tx))

                return await self.session.execute_write(wrapped)

        class FailingDriver:
            def session(self, **kwargs):
                return FailingSession()

        with self.assertRaisesRegex(RuntimeError, "injected"):
            await import_document(FailingDriver(), DATABASE, self.document)
        rows = await self.query(
            "MATCH (n) WHERE n.name IN $names RETURN count(n) AS n",
            names=[
                self.test_names[name] for name in ["n4-fixture", "N4Person", "N4Org"]
            ],
        )
        self.assertEqual(0, rows[0]["n"])
