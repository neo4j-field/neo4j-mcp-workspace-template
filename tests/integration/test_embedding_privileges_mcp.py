"""Actual restricted-user onboarding checks in an isolated Enterprise DBMS.

Admin credentials are used only to provision/drop UUID test databases and users.
The MCP tool runs as a fresh restricted user. Provider output is deterministic:
these tests require real Neo4j authorization but no API keys or provider calls.
"""

from __future__ import annotations

import json
import os
import secrets
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastmcp import Client
from neo4j import AsyncGraphDatabase

from mcp_neo4j_lexical_graph.embedding_identity import LOCK_CONSTRAINT
from mcp_neo4j_lexical_graph.server import create_mcp_server

LABEL = "RestrictedEmbeddingFixture"


@unittest.skipUnless(
    os.getenv("NEO4J_MCP_RUN_EMBEDDING_PRIVILEGES") == "1",
    "requires explicitly isolated Enterprise Neo4j 2025.12+ with admin fixture access",
)
class EmbeddingPrivilegesMCPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        suffix = uuid4().hex
        self.database = "embeddingprivs" + suffix
        self.role = "embedding_privileges_" + suffix
        self.username = "embedding_user_" + suffix
        self.password = secrets.token_urlsafe(24)
        self.created_database = False
        self.created_role = False
        self.created_user = False
        self.user_driver = None
        self.provider_calls = []
        self.admin = AsyncGraphDatabase.driver(
            os.environ["NEO4J_URI"],
            auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
            notifications_min_severity="OFF",
        )
        self.addAsyncCleanup(self.cleanup)
        await self.admin_query(f"CREATE DATABASE {self.database} WAIT 30 SECONDS")
        self.created_database = True
        await self.admin_query(f"CREATE ROLE {self.role}")
        self.created_role = True
        await self.admin_query(
            f"CREATE USER {self.username} SET PASSWORD $password CHANGE NOT REQUIRED",
            password=self.password,
        )
        self.created_user = True
        await self.admin_query(f"GRANT ROLE {self.role} TO {self.username}")
        for privilege in [
            f"ACCESS ON DATABASE {self.database}",
            f"MATCH {{*}} ON GRAPH {self.database}",
            f"WRITE ON GRAPH {self.database}",
            f"NAME MANAGEMENT ON DATABASE {self.database}",
            f"CREATE INDEX ON DATABASE {self.database}",
            f"SHOW INDEX ON DATABASE {self.database}",
            f"SHOW CONSTRAINT ON DATABASE {self.database}",
        ]:
            await self.admin_query(f"GRANT {privilege} TO {self.role}")
        await self.graph_query(
            f"CREATE (:{LABEL} {{id:$id, text:'Synthetic onboarding fixture'}})",
            id=suffix,
        )
        self.user_driver = AsyncGraphDatabase.driver(
            os.environ["NEO4J_URI"],
            auth=(self.username, self.password),
            notifications_min_severity="OFF",
        )
        await self.user_driver.verify_connectivity()

    async def admin_query(self, query, **params):
        async with self.admin.session(database="system") as session:
            return await (await session.run(query, **params)).data()

    async def graph_query(self, query, **params):
        async with self.admin.session(database=self.database) as session:
            return await (await session.run(query, **params)).data()

    async def cleanup(self):
        try:
            if self.user_driver is not None:
                await self.user_driver.close()
            if self.created_user:
                await self.admin_query(f"DROP USER {self.username} IF EXISTS")
            if self.created_role:
                await self.admin_query(f"DROP ROLE {self.role} IF EXISTS")
            if self.created_database:
                await self.admin_query(
                    f"DROP DATABASE {self.database} IF EXISTS DESTROY DATA WAIT 30 SECONDS"
                )
        finally:
            await self.admin.close()

    async def embed_as_user(self):
        async def deterministic(_embedder, pairs, **_kwargs):
            self.provider_calls.append(pairs)
            return [(eid, [1.0, 0.0, 0.0]) for eid, _text in pairs]

        server = create_mcp_server(
            self.user_driver, database=self.database, process_pool=MagicMock()
        )
        async with Client(server) as client:
            with patch(
                "mcp_neo4j_lexical_graph.server.ChunkEmbedder.embed_many",
                new=deterministic,
            ):
                result = await client.call_tool(
                    "embed_chunks",
                    {
                        "node_label": LABEL,
                        "context_properties": [],
                        "index_prefilter_properties": [],
                        "dimensions": 3,
                        "create_fulltext_index": False,
                    },
                )
        return json.loads(result.content[0].text)

    async def assert_no_vectors_or_provider_work(self):
        self.assertEqual([], self.provider_calls)
        row = (
            await self.graph_query(
                f"CYPHER 25 MATCH (n:{LABEL}) RETURN n.text_embedding AS embedding, "
                "n.embeddingInputHash AS input_hash"
            )
        )[0]
        self.assertIsNone(row["embedding"])
        self.assertIsNone(row["input_hash"])

    async def test_fresh_user_without_create_constraint_fails_before_provider(self):
        with self.assertRaises(Exception) as caught:
            await self.embed_as_user()
        message = str(caught.exception)
        self.assertIn("constraint", message.lower())
        self.assertIn("No provider request or vector write was made", message)
        self.assertIn("CREATE CONSTRAINT", message)
        self.assertIn("SHOW CONSTRAINT", message)
        self.assertIn("precreate", message)
        self.assertIn("create_constraint", message)
        await self.assert_no_vectors_or_provider_work()

    async def test_admin_precreated_constraint_allows_restricted_runtime(self):
        await self.graph_query(
            f"CREATE CONSTRAINT {LOCK_CONSTRAINT} FOR (n:EmbeddingPublicationLock) "
            "REQUIRE n.indexName IS UNIQUE"
        )
        result = await self.embed_as_user()
        self.assertEqual("success", result["status"])
        self.assertEqual(1, result["embedded"])
        self.assertEqual(1, len(self.provider_calls))

    async def test_missing_show_constraint_fails_before_provider(self):
        await self.admin_query(
            f"GRANT CREATE CONSTRAINT ON DATABASE {self.database} TO {self.role}"
        )
        await self.admin_query(
            f"DENY SHOW CONSTRAINT ON DATABASE {self.database} TO {self.role}"
        )
        with self.assertRaises(Exception) as caught:
            await self.embed_as_user()
        self.assertIn("Show constraints", str(caught.exception))
        self.assertIn("SHOW CONSTRAINT", str(caught.exception))
        self.assertIn(
            "No provider request or vector write was made", str(caught.exception)
        )
        await self.assert_no_vectors_or_provider_work()

    async def test_fresh_user_with_required_privileges_embeds(self):
        await self.admin_query(
            f"GRANT CREATE CONSTRAINT ON DATABASE {self.database} TO {self.role}"
        )
        result = await self.embed_as_user()
        self.assertEqual("success", result["status"])
        self.assertEqual(1, result["embedded"])
        self.assertEqual(1, len(self.provider_calls))
        row = (
            await self.graph_query(
                f"CYPHER 25 MATCH (n:{LABEL}) RETURN size(n.text_embedding) AS dimensions, "
                "n.embeddingInputHash AS input_hash"
            )
        )[0]
        self.assertEqual(3, row["dimensions"])
        self.assertEqual(64, len(row["input_hash"]))
        locks = await self.graph_query(
            "MATCH (n:EmbeddingPublicationLock) RETURN count(n) AS count"
        )
        self.assertEqual(0, locks[0]["count"])
