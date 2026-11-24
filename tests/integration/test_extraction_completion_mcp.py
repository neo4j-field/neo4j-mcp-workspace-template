"""EXT-002 durable completion must match inputs, schema and configuration."""
import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastmcp import Client
from neo4j import AsyncGraphDatabase
from mcp_neo4j_entity_graph.models import ChunkExtractionResult, ChunkExtractionOutcome, ExtractedEntity, ExtractedRelationship
from mcp_neo4j_entity_graph.server import create_mcp_server

LABEL = 'Ext002Source'
DATABASE = os.getenv('NEO4J_DATABASE', 'neo4j')
SCHEMA = Path(__file__).resolve().parents[1] / 'fixtures/entity/bug003_schema.py'


@unittest.skipUnless(os.getenv('NEO4J_MCP_RUN_INTEGRATION') == '1', 'requires disposable Neo4j')
class ExtractionCompletionIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.driver = AsyncGraphDatabase.driver(os.environ['NEO4J_URI'], auth=(
            os.environ['NEO4J_USERNAME'], os.environ['NEO4J_PASSWORD']))
        self.outcome = ChunkExtractionOutcome.SUCCESS
        self.calls = 0
        self.bad_relationship = False
        await self.cleanup()
        async with self.driver.session(database=DATABASE) as session:
            await session.run(f'CREATE (:{LABEL} {{id: "ext002-source", text: "original text"}})')

    async def cleanup(self):
        async with self.driver.session(database=DATABASE) as session:
            for query in [f'MATCH (n:{LABEL}) DETACH DELETE n',
                          'MATCH (n:Bug003Sentinel {sentinelId: "ext002-entity"}) DETACH DELETE n',
                          'MATCH (n:EntityExtractionRun {sourceLabel: $label}) DETACH DELETE n',
                          'MATCH (n:EntityExtractionClaim {sourceLabel: $label}) DETACH DELETE n']:
                result = await session.run(query, label=LABEL)
                await result.consume()

    async def asyncTearDown(self):
        await self.cleanup()
        await self.driver.close()

    async def extract(self, **kwargs):
        async def stub(_extractor, chunk, _schema, _output):
            self.calls += 1
            return ChunkExtractionResult(
                chunk_id=chunk.id, outcome=self.outcome,
                error='fixture failure' if self.outcome == ChunkExtractionOutcome.FAILED else None,
                relationships=[ExtractedRelationship(
                    type='EXT002_MISSING_ENDPOINT', source_label='Bug003Sentinel',
                    source_key='ext002-entity', target_label='Bug003Sentinel', target_key='missing',
                )] if self.bad_relationship else [],
                entities=[ExtractedEntity(label='Bug003Sentinel', properties={
                    'sentinelId': 'ext002-entity'})] if self.outcome == ChunkExtractionOutcome.SUCCESS else [],
            )
        # A fresh server for every call proves graph completion survives restart.
        async with Client(create_mcp_server(self.driver, database=DATABASE)) as client:
            with patch('mcp_neo4j_entity_graph.server.TextExtractor.extract_chunk', new=stub):
                params = {'schema': str(SCHEMA), 'source_label': LABEL, **kwargs}
                started = json.loads((await client.call_tool('extract_entities', params)).content[0].text)
                if started['job_id'] is None:
                    return started
                for _ in range(200):
                    status = json.loads((await client.call_tool('check_extraction_status', {'job_id': started['job_id']})).content[0].text)
                    if status['status'] in ('complete', 'failed'):
                        return status
                    await asyncio.sleep(.01)
                self.fail('completion fixture timed out')

    async def test_empty_success_skips_after_restart_without_provenance(self):
        self.outcome = ChunkExtractionOutcome.EMPTY
        self.assertEqual('complete', (await self.extract())['status'])
        self.assertIsNone((await self.extract())['job_id'])
        self.assertEqual(1, self.calls)

    async def test_legacy_partial_provenance_is_not_completion(self):
        async with self.driver.session(database=DATABASE) as session:
            await session.run(f'MATCH (s:{LABEL}) CREATE (:Bug003Sentinel {{sentinelId: "ext002-entity"}})-[:EXTRACTED_FROM]->(s)')
        with self.assertRaisesRegex(Exception, 'Legacy EXTRACTED_FROM'):
            await self.extract()
        self.assertEqual(0, self.calls)

    async def test_changed_content_schema_model_and_policy_reselect(self):
        self.assertEqual('complete', (await self.extract())['status'])
        self.assertIsNone((await self.extract())['job_id'])
        async with self.driver.session(database=DATABASE) as session:
            await session.run(f'MATCH (s:{LABEL}) SET s.text="changed text"')
        self.assertEqual('complete', (await self.extract())['status'])
        self.assertEqual('complete', (await self.extract(model='different-configured-model'))['status'])
        self.assertEqual('complete', (await self.extract(property_policy='overwrite'))['status'])
        with tempfile.TemporaryDirectory() as directory:
            schema = Path(directory) / 'schema.py'
            schema.write_text(SCHEMA.read_text() + '\n# changed schema version\n')
            self.assertEqual('complete', (await self.extract(schema=str(schema)))['status'])
            self.assertIsNone((await self.extract(schema=str(schema)))['job_id'])
        self.assertEqual(5, self.calls)

    async def test_failed_forced_attempt_invalidates_old_completion(self):
        self.assertEqual('complete', (await self.extract())['status'])
        self.outcome = ChunkExtractionOutcome.FAILED
        self.assertEqual('failed', (await self.extract(force=True))['status'])
        self.outcome = ChunkExtractionOutcome.SUCCESS
        self.assertEqual('complete', (await self.extract())['status'])
        self.assertEqual(3, self.calls)

    async def test_failed_relationship_persistence_does_not_publish_completion(self):
        self.bad_relationship = True
        failed = await self.extract()
        self.assertEqual('failed', failed['status'])
        self.assertIn('Relationship persistence mismatch', failed['error'])
        self.bad_relationship = False
        self.assertEqual('complete', (await self.extract())['status'])
        self.assertEqual(2, self.calls)
