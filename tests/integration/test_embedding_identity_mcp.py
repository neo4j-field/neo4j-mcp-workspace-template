"""EMB-001 with deterministic provider output and real Neo4j 2025.12+ vectors.

Uses only an explicitly configured disposable database. No provider call is made.
"""
import asyncio
from contextlib import nullcontext
import json
import os
import unittest
from unittest.mock import MagicMock, patch

from fastmcp import Client
from neo4j import AsyncGraphDatabase
from mcp_neo4j_lexical_graph.server import create_mcp_server

LABEL = 'EmbeddingIdentityFixture'
INDEX = LABEL.lower() + '_text_embedding'
FULLTEXT = LABEL.lower() + '_text_fulltext'
OTHER_INDEX = 'embedding_identity_other'
DATABASE = os.getenv('NEO4J_DATABASE', 'neo4j')


@unittest.skipUnless(os.getenv('NEO4J_MCP_RUN_EMBEDDING_IDENTITY') == '1', 'requires disposable Neo4j 2025.12+ vector support')
class EmbeddingIdentityMCPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.driver = AsyncGraphDatabase.driver(os.environ['NEO4J_URI'], auth=(os.environ['NEO4J_USERNAME'], os.environ['NEO4J_PASSWORD']))
        self.calls = []
        self.vector_dims = 3
        self.partial = False
        self.mutate = False
        self.mutate_space = False
        self.attach_index = False
        self.barrier = None
        self.shared_provider_patch = None
        self.chunk = False
        await self.cleanup()
        await self.query(f'CREATE (:{LABEL} {{id:"a", text:"raw", documentName:"doc", sectionContext:"section"}})')

    async def query(self, query, **params):
        async with self.driver.session(database=DATABASE) as session:
            return await (await session.run(query, **params)).data()

    async def cleanup(self):
        for name in [INDEX, FULLTEXT, OTHER_INDEX] + (['chunk_text_embedding', 'chunk_text_fulltext'] if self.chunk else []):
            await self.query(f'DROP INDEX {name} IF EXISTS')
        await self.query(f'MATCH (n:{LABEL}) DETACH DELETE n')

    async def asyncTearDown(self):
        try:
            count = (await self.query('MATCH (n:EmbeddingPublicationLock) WHERE n.indexName IN $names RETURN count(n) AS count', names=[INDEX,'chunk_text_embedding']))[0]['count']
            self.assertEqual(0, count, 'temporary publication locks must not survive commit or rollback')
        finally:
            await self.cleanup()
            await self.driver.close()

    async def embed(self, **kwargs):
        async def deterministic(embedder, pairs, **_kwargs):
            self.calls.append({'pairs':pairs, 'model':embedder.model, 'dimensions':embedder.dimensions})
            if self.barrier is not None:
                await self.barrier.wait()
            if self.mutate:
                await self.query(f'MATCH (n:{LABEL} {{id:"a"}}) SET n.text="raced source"')
            if self.mutate_space:
                await self.query(f'MATCH (n:{LABEL} {{id:"b"}}) SET n.embeddingSpace="externally changed"')
            if self.attach_index:
                await self.query(f'MATCH (n:{LABEL} {{id:"a"}}) SET n:EmbeddingOtherLabel')
                await self.query(f"CYPHER 25 CREATE VECTOR INDEX {OTHER_INDEX} FOR (n:EmbeddingOtherLabel) ON n.text_embedding OPTIONS {{indexConfig: {{`vector.dimensions`:3,`vector.similarity_function`:'cosine'}}}}")
            pairs = pairs[:-1] if self.partial else pairs
            return [(eid, [1.0] + [0.0] * (self.vector_dims - 1)) for eid, _ in pairs]
        async with Client(create_mcp_server(self.driver, database=DATABASE, process_pool=MagicMock())) as client:
            provider_patch = patch('mcp_neo4j_lexical_graph.server.ChunkEmbedder.embed_many', new=deterministic)
            if self.barrier is not None:
                if self.shared_provider_patch is None:
                    self.shared_provider_patch = provider_patch
                    self.shared_provider_patch.start()
                provider_patch = nullcontext()
            with provider_patch:
                result = await client.call_tool('embed_chunks', {'node_label':LABEL, **kwargs})
        return json.loads(result.content[0].text)

    async def row(self):
        return (await self.query(f'CYPHER 25 MATCH (n:{LABEL} {{id:"a"}}) RETURN n.embeddingModel AS model,n.embeddingProvider AS provider,n.embeddingDimensions AS dims,n.embeddingInputHash AS hash,n.embeddingSpace AS space,size(n.text_embedding) AS vector_dims'))[0]

    async def test_legacy_vector_regenerates_then_matching_cache_repairs_index(self):
        await self.query(f'CYPHER 25 MATCH (n:{LABEL}) SET n.text_embedding=vector([1.0,0.0,0.0],3,FLOAT32)')
        first = await self.embed()
        self.assertEqual(1, first['embedded'])
        row = await self.row()
        self.assertEqual('text-embedding-3-small', row['model'])
        self.assertEqual('openai', row['provider'])
        self.assertEqual(3, row['dims'])
        self.assertEqual(64, len(row['hash']))
        await self.query(f'DROP INDEX {INDEX}')
        second = await self.embed()
        self.assertEqual(0, second['embedded'])
        self.assertEqual('plain', second['vector_index_mode'])
        self.assertEqual(1, len(self.calls))
        await self.query('CALL db.awaitIndex($name,30)', name=INDEX)
        hit = (await self.query('CALL db.index.vector.queryNodes($name,1,[1.0,0.0,0.0]) YIELD node,score RETURN node.id AS id,score', name=INDEX))[0]
        self.assertEqual('a', hit['id'])
        self.assertAlmostEqual(1, hit['score'])

    async def test_exact_context_fallback_and_actual_visual_input_invalidate(self):
        await self.embed()
        self.assertEqual('doc section raw', self.calls[-1]['pairs'][0][1])
        await self.query(f'MATCH (n:{LABEL}) SET n.sectionContext="new section"')
        await self.embed()
        self.assertEqual('doc new section raw', self.calls[-1]['pairs'][0][1])
        await self.query(f'MATCH (n:{LABEL}) SET n.textDescription="visual summary"')
        await self.embed(text_property='textDescription', text_property_fallback='text')
        self.assertEqual('doc new section visual summary', self.calls[-1]['pairs'][0][1])
        await self.query(f'MATCH (n:{LABEL}) SET n.text="changed unused raw"')
        skipped = await self.embed(text_property='textDescription', text_property_fallback='text')
        self.assertEqual(0, skipped['embedded'])
        self.assertEqual(3, len(self.calls))
        await self.query(f'MATCH (n:{LABEL}) REMOVE n.textDescription')
        await self.embed(text_property='textDescription', text_property_fallback='text')
        self.assertEqual('doc new section changed unused raw', self.calls[-1]['pairs'][0][1])

    async def test_document_scoped_model_change_refuses_mixed_space_before_provider(self):
        await self.query(f'CREATE (:{LABEL} {{id:"b",text:"other",documentName:"other"}})')
        await self.embed()
        with self.assertRaisesRegex(Exception, 'mix'):
            await self.embed(document_id='doc', model='text-embedding-3-large')
        self.assertEqual(1, len(self.calls))
        self.assertEqual('text-embedding-3-small', (await self.row())['model'])
        refreshed = await self.embed(model='text-embedding-3-large')
        self.assertEqual(2, refreshed['embedded'])
        self.assertEqual('text-embedding-3-large', (await self.row())['model'])

    async def test_existing_index_dimensions_refuse_without_vector_writes(self):
        await self.embed()
        previous = await self.row()
        with self.assertRaisesRegex(Exception, 'Existing vector index'):
            await self.embed(dimensions=4)
        self.assertEqual(1, len(self.calls), 'explicit dimension mismatch needs no billable probe')
        self.vector_dims = 4
        with self.assertRaisesRegex(Exception, 'Existing vector index'):
            await self.embed(model='text-embedding-3-large')
        self.assertEqual(previous, await self.row())

    async def test_partial_provider_response_does_not_publish(self):
        self.partial = True
        with self.assertRaisesRegex(Exception, 'every selected node'):
            await self.embed()
        self.assertIsNone((await self.row())['hash'])
        self.assertIsNone((await self.row())['vector_dims'])

    async def test_source_mutation_rolls_back_vector_and_metadata_refresh(self):
        await self.embed()
        previous = await self.row()
        await self.query(f'MATCH (n:{LABEL}) SET n.text="new pending text"')
        self.mutate = True
        with self.assertRaisesRegex(Exception, 'source input changed'):
            await self.embed()
        self.assertEqual(previous, await self.row())

    async def test_missing_constraint_privilege_fails_before_provider(self):
        with patch('mcp_neo4j_lexical_graph.server.ensure_publication_constraint', side_effect=RuntimeError('constraint privilege denied')):
            with self.assertRaisesRegex(Exception, 'constraint privilege denied'):
                await self.embed()
        self.assertEqual([], self.calls)
        self.assertIsNone((await self.row())['hash'])

    async def test_overlapping_label_is_not_a_separate_vector_store(self):
        await self.embed()
        await self.query(f'MATCH (n:{LABEL}) SET n:EmbeddingOtherLabel')
        await self.query(f"CYPHER 25 CREATE VECTOR INDEX {OTHER_INDEX} FOR (n:EmbeddingOtherLabel) ON n.text_embedding OPTIONS {{indexConfig: {{`vector.dimensions`:3,`vector.similarity_function`:'cosine'}}}}")
        with self.assertRaisesRegex(Exception, 'another text_embedding'):
            await self.embed(model='text-embedding-3-large')
        self.assertEqual(1, len(self.calls))
        await self.query(f'MATCH (n:{LABEL}) SET n.text="same space new input"')
        self.assertEqual(1, (await self.embed())['embedded'])

    async def test_auto_visual_description_and_inactive_space_migration(self):
        other = (await self.query(f'MATCH (n:Chunk) WHERE NOT n:{LABEL} RETURN count(n) AS count'))[0]['count']
        if other:
            self.skipTest('requires isolated Chunk label/index')
        self.chunk = True
        await self.query(f'MATCH (n:{LABEL}) SET n:Chunk,n.active=true,n.textDescription="visual summary",n.type="image"')
        await self.query(f'CREATE (:Chunk:{LABEL} {{id:"b",text:"inactive",active:false}})')
        result = await self.embed(node_label='Chunk', include_inactive=True)
        self.assertTrue(result['auto_detected_fallback'])
        self.assertTrue(any('visual summary' in text for _, text in self.calls[0]['pairs']))
        with self.assertRaisesRegex(Exception, 'mix'):
            await self.embed(node_label='Chunk', model='text-embedding-3-large')
        count = len(self.calls)
        result = await self.embed(node_label='Chunk', model='text-embedding-3-large', include_inactive=True)
        self.assertEqual(2, result['embedded'])
        self.assertEqual(count+1, len(self.calls))

    async def test_provider_work_cannot_hide_a_new_overlapping_label_index(self):
        await self.embed()
        previous = await self.row()
        self.attach_index = True
        with self.assertRaisesRegex(Exception, 'another text_embedding'):
            await self.embed(model='text-embedding-3-large')
        self.assertEqual(previous, await self.row())

    async def test_preserved_vector_space_is_rechecked_under_publication_lock(self):
        await self.query(f'CREATE (:{LABEL} {{id:"b",text:"other",documentName:"other"}})')
        await self.embed()
        previous = await self.row()
        await self.query(f'MATCH (n:{LABEL} {{id:"a"}}) SET n.text="pending update"')
        self.mutate_space = True
        with self.assertRaisesRegex(Exception, 'mix'):
            await self.embed(document_id='doc')
        self.assertEqual(previous, await self.row())

    async def test_mismatched_cached_dimension_metadata_regenerates(self):
        await self.embed()
        await self.query(f'MATCH (n:{LABEL}) SET n.embeddingDimensions=99')
        self.assertEqual(1, (await self.embed())['embedded'])
        self.assertEqual(2, len(self.calls))
        self.assertEqual(3, (await self.row())['dims'])

    async def test_removed_input_is_not_reported_as_a_valid_cached_noop(self):
        await self.embed()
        previous = await self.row()
        await self.query(f'MATCH (n:{LABEL}) REMOVE n.text')
        with self.assertRaisesRegex(Exception, 'no usable embedding input'):
            await self.embed()
        self.assertEqual(1, len(self.calls))
        self.assertEqual(previous, await self.row())

    async def test_concurrent_document_spaces_cannot_publish_a_mixed_index(self):
        await self.query(f'CREATE (:{LABEL} {{id:"b",text:"other",documentName:"other"}})')
        self.barrier = asyncio.Event()
        tasks = [asyncio.create_task(self.embed(document_id='doc')),
                 asyncio.create_task(self.embed(document_id='other', model='text-embedding-3-large'))]
        try:
            for _ in range(300):
                if len(self.calls) == 2:
                    break
                await asyncio.sleep(.01)
            self.assertEqual(2, len(self.calls))
            self.barrier.set()
            results = await asyncio.gather(*tasks, return_exceptions=True)
            self.assertEqual(1, sum(isinstance(r, dict) for r in results), results)
            self.assertEqual(1, sum(isinstance(r, Exception) for r in results), results)
            error = next(r for r in results if isinstance(r, Exception))
            self.assertIn('mix', str(error))
            rows = await self.query(f'MATCH (n:{LABEL}) WHERE n.text_embedding IS NOT NULL RETURN n.embeddingModel AS model')
            self.assertEqual(1, len(rows))
        finally:
            self.barrier.set()
            await asyncio.gather(*tasks, return_exceptions=True)
            if self.shared_provider_patch is not None:
                self.shared_provider_patch.stop()
                self.shared_provider_patch = None

    async def test_foreign_committed_lock_data_is_not_claimed_or_deleted(self):
        await self.query('CREATE (:EmbeddingPublicationLock {indexName:$name, foreign:"keep"})', name=INDEX)
        try:
            with self.assertRaisesRegex(Exception, 'already contains committed data'):
                await self.embed()
            row = (await self.query('MATCH (n:EmbeddingPublicationLock {indexName:$name}) RETURN n.foreign AS value,n.generation AS generation', name=INDEX))[0]
            self.assertEqual({'value':'keep','generation':None}, row)
            self.assertIsNone((await self.row())['hash'])
        finally:
            await self.query('MATCH (n:EmbeddingPublicationLock {indexName:$name,foreign:"keep"}) DELETE n', name=INDEX)
