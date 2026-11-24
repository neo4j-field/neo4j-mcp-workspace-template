"""BUG-004: real prefilter rejection and plain-index repair on Neo4j 2025.12.1.

Opt in on a disposable database. Embedding output is deterministic; the actual
embed_chunks write/index/repair paths and Neo4j vector retrieval are exercised.
"""
import json
import os
import unittest
from unittest.mock import MagicMock, patch

from fastmcp import Client
from neo4j import AsyncGraphDatabase
from mcp_neo4j_lexical_graph.server import create_mcp_server


LABEL = 'Bug004VectorFixture'
INDEX = LABEL.lower() + '_text_embedding'
FULLTEXT = LABEL.lower() + '_text_fulltext'
DATABASE = os.getenv('NEO4J_DATABASE', 'neo4j')


@unittest.skipUnless(os.getenv('NEO4J_MCP_RUN_VECTOR_FALLBACK') == '1',
                     'requires disposable Neo4j 2025.12.1 and NEO4J_MCP_RUN_VECTOR_FALLBACK=1')
class VectorFallbackIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_embed_falls_back_and_repeat_repairs_missing_index(self):
        driver = AsyncGraphDatabase.driver(os.environ['NEO4J_URI'], auth=(
            os.environ['NEO4J_USERNAME'], os.environ['NEO4J_PASSWORD']))
        try:
            async with driver.session(database=DATABASE) as session:
                await session.run(f'CREATE (c:{LABEL} {{id: "bug004-fallback", text: "coolant valve", documentName: "bug004", type: "text"}})')
            server = create_mcp_server(driver, database=DATABASE, process_pool=MagicMock())

            async def deterministic_embedding(_embedder, pairs, **_kwargs):
                return [(eid, [1.0, 0.0, 0.0]) for eid, _ in pairs]

            async with Client(server) as client:
                with patch('mcp_neo4j_lexical_graph.server.ChunkEmbedder.embed_many', new=deterministic_embedding):
                    first = json.loads((await client.call_tool('embed_chunks', {'node_label': LABEL})).content[0].text)
                self.assertEqual('success', first['status'], first)
                self.assertEqual(1, first['embedded'])
                self.assertEqual('plain', first['vector_index_mode'])
                self.assertIn(first['vector_index_state'], ['ONLINE', 'POPULATING'])
                async with driver.session(database=DATABASE) as session:
                    result = await session.run(f'DROP INDEX {INDEX}')
                    await result.consume()
                second = json.loads((await client.call_tool('embed_chunks', {'node_label': LABEL})).content[0].text)
                self.assertEqual('success', second['status'], second)
                self.assertEqual(0, second['embedded'])
                self.assertEqual('plain', second['vector_index_mode'])
                async with driver.session(database=DATABASE) as session:
                    result = await session.run('CALL db.awaitIndex($name, 30)', name=INDEX)
                    await result.consume()
                    result = await session.run('SHOW VECTOR INDEXES YIELD name, state WHERE name=$name RETURN state', name=INDEX)
                    self.assertEqual('ONLINE', (await result.single())['state'])
                    result = await session.run('CALL db.index.vector.queryNodes($name, 1, [1.0, 0.0, 0.0]) YIELD node, score RETURN node.id AS id, score', name=INDEX)
                    hit = await result.single()
                    self.assertEqual('bug004-fallback', hit['id'])
                    self.assertAlmostEqual(1.0, hit['score'], places=5)
        finally:
            async with driver.session(database=DATABASE) as session:
                for name in [INDEX, FULLTEXT]:
                    result = await session.run(f'DROP INDEX {name} IF EXISTS')
                    await result.consume()
                result = await session.run(f'MATCH (n:{LABEL} {{id: "bug004-fallback"}}) DETACH DELETE n')
                await result.consume()
            await driver.close()
