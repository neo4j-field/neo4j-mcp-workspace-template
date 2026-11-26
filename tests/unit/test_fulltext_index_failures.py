"""Required fulltext DDL must fail visibly, including deferred driver errors."""
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from fastmcp import Client
from mcp_neo4j_lexical_graph.server import _ensure_fulltext_index, create_mcp_server


class FulltextIndexTests(unittest.IsolatedAsyncioTestCase):
    def driver(self, record=None, deferred_error=None):
        ddl = MagicMock(consume=AsyncMock(side_effect=deferred_error))
        result = MagicMock(single=AsyncMock(return_value=record))
        session = MagicMock(run=AsyncMock(side_effect=[ddl, result]))
        driver = MagicMock()
        driver.session.return_value.__aenter__ = AsyncMock(return_value=session)
        driver.session.return_value.__aexit__ = AsyncMock(return_value=False)
        return driver

    async def test_population_is_reported_and_wrong_or_failed_definition_refused(self):
        good = dict(entityType='NODE', labelsOrTypes=['Chunk'], properties=['text'], state='POPULATING')
        result = await _ensure_fulltext_index(self.driver(good), 'neo4j', 'chunk_text_fulltext', 'Chunk', ['text'])
        self.assertEqual('POPULATING', result['state'])
        for record in [None, {**good, 'state':'FAILED', 'failureMessage':'disk failure'},
                       {**good, 'properties':['wrong']}, {**good, 'labelsOrTypes':['Other']},
                       {**good, 'entityType':'RELATIONSHIP'}]:
            with self.assertRaises(RuntimeError):
                await _ensure_fulltext_index(self.driver(record), 'neo4j', 'chunk_text_fulltext', 'Chunk', ['text'])

    async def test_lazy_ddl_failure_propagates(self):
        with self.assertRaisesRegex(RuntimeError, 'permission denied'):
            await _ensure_fulltext_index(self.driver(deferred_error=RuntimeError('permission denied')), 'neo4j', 'x', 'Chunk', ['text'])

    async def test_public_failure_occurs_before_provider(self):
        server = create_mcp_server(MagicMock(), database='neo4j', process_pool=MagicMock())
        with patch('mcp_neo4j_lexical_graph.server._ensure_fulltext_index', AsyncMock(side_effect=RuntimeError('permission denied'))), patch('mcp_neo4j_lexical_graph.server.ChunkEmbedder.embed_many', AsyncMock()) as provider:
            async with Client(server) as client:
                result = await client.call_tool('embed_chunks', {'text_property':'custom'}, raise_on_error=False)
        self.assertTrue(result.is_error)
        self.assertIn('permission denied', str(result))
        provider.assert_not_awaited()
