"""Fulltext failures/rebuild are observable through the public embedding tool."""
import json
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from fastmcp import Client
from neo4j import AsyncGraphDatabase
from mcp_neo4j_lexical_graph.server import create_mcp_server, _ensure_fulltext_index
from mcp_neo4j_lexical_graph.embedding_identity import embedding_space, input_hash


@unittest.skipUnless(os.getenv('NEO4J_MCP_RUN_INTEGRATION')=='1','requires disposable Neo4j')
class FulltextFailureIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_conflict_fails_before_provider_and_cache_only_repair(self):
        driver=AsyncGraphDatabase.driver(os.environ['NEO4J_URI'],auth=(os.environ['NEO4J_USERNAME'],os.environ['NEO4J_PASSWORD']))
        database=os.getenv('NEO4J_DATABASE','neo4j');label='Index'+uuid4().hex
        index=label.lower()+'_text_fulltext';vector=label.lower()+'_text_embedding'
        space=embedding_space('text-embedding-3-small',3)
        try:
            async with driver.session(database=database) as s:
                await (await s.run(f'CREATE (n:{label} {{text:"coolant valve", text_embedding:[1.0,0.0,0.0], embeddingDimensions:3, embeddingSpace:$space, embeddingModel:$model, embeddingProvider:$provider, embeddingInputHash:$hash}})',space=space.fingerprint,model=space.model,provider=space.provider,hash=input_hash('coolant valve'))).consume()
                await (await s.run(f'CREATE FULLTEXT INDEX {index} FOR (n:{label}) ON EACH [n.wrong]')).consume()
            async with Client(create_mcp_server(driver,database=database,process_pool=MagicMock())) as client:
                args=dict(node_label=label,model='text-embedding-3-small',dimensions=3)
                with patch('mcp_neo4j_lexical_graph.server.ChunkEmbedder.embed_many',AsyncMock()) as provider:
                    result=await client.call_tool('embed_chunks',args,raise_on_error=False)
                    self.assertTrue(result.is_error);self.assertIn('incompatible definition',str(result))
                    provider.assert_not_awaited()
                    async with driver.session(database=database) as s:
                        await (await s.run(f'DROP INDEX {index}')).consume()
                    result=await client.call_tool('embed_chunks',args)
                    payload=json.loads(result.content[0].text)
                    self.assertEqual(0,payload['embedded']);self.assertEqual(index,payload['fulltext_index']['name'])
                    provider.assert_not_awaited()
            async with driver.session(database=database) as s:
                await (await s.run('CALL db.awaitIndexes(60)')).consume()
                result=await s.run('CALL db.index.fulltext.queryNodes($index,"coolant") YIELD node RETURN node.text AS text',index=index)
                self.assertEqual('coolant valve',(await result.single())['text'])
        finally:
            async with driver.session(database=database) as s:
                await (await s.run(f'MATCH (n:{label}) DETACH DELETE n')).consume()
                for name in [index,vector]:
                    await (await s.run(f'DROP INDEX {name} IF EXISTS')).consume()
            await driver.close()
