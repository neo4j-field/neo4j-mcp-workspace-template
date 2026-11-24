"""Real Neo4j entity merge conflicts; no provider calls, isolated fixture data."""
import asyncio
import json
import tempfile
from pathlib import Path
from typing import get_args

from mcp_neo4j_entity_graph.base_extractor import _parse_typed_response
from unittest.mock import patch

from tests.integration import test_entity_relationship_persistence_mcp as fixture


class BridgePropertyPolicyIntegrationTests(fixture.EntityRelationshipPersistenceMCPIntegrationTests):
    async def _stub_extract(self, chunk, schema, output_model):
        result = await super()._stub_extract(chunk, schema, output_model)
        for entity in result.entities:
            if entity.label == 'Bug002Person':
                entity.properties.update(action='PDF action', newFact='PDF only', nullable=None)
        return result

    async def _write_csv(self):
        async with self.driver.session(database=fixture.DATABASE) as session:
            await session.run(
                'MERGE (p:Bug002Person {personId: $key}) SET p.action = "CSV action", p.nullable = "keep"',
                key=fixture.PERSON_ID,
            )

    async def _extract(self, policy=None, schema_path=None, extractor=None):
        args = {'schema': str(schema_path or fixture.SCHEMA_PATH), 'source_label': fixture.SOURCE_LABEL,
                'force': True, 'batch_size': 1}
        if policy:
            args['property_policy'] = policy
        with patch('mcp_neo4j_entity_graph.server.TextExtractor.extract_chunk', new=extractor or self._stub_extract):
            started = json.loads((await self.client.call_tool('extract_entities', args)).content[0].text)
            for _ in range(200):
                status = json.loads((await self.client.call_tool('check_extraction_status', {'job_id': started['job_id']})).content[0].text)
                if status['status'] in ('complete', 'failed'):
                    break
                await asyncio.sleep(.01)
            self.assertEqual('complete', status['status'], status)
        async with self.driver.session(database=fixture.DATABASE) as session:
            result = await session.run('''MATCH (p:Bug002Person {personId: $key})-[r:EXTRACTED_FROM]->()
                RETURN p.action AS action, p.newFact AS newFact, p.nullable AS nullable,
                       r.proposedPropertiesJson AS proposed, r.conflictingProperties AS conflicts,
                       r.propertyPolicy AS policy''', key=fixture.PERSON_ID)
            return dict(await result.single())

    async def test_csv_first_preserves_value_and_records_conflict_by_default(self):
        await self._write_csv()
        row = await self._extract()
        self.assertEqual('CSV action', row['action'])
        self.assertEqual('PDF only', row['newFact'])
        self.assertEqual('keep', row['nullable'])
        self.assertEqual(['action'], row['conflicts'])
        self.assertEqual('PDF action', json.loads(row['proposed'])['action'])
        self.assertEqual('preserve_existing', row['policy'])

    async def test_explicit_overwrite_and_null_does_not_delete(self):
        await self._write_csv()
        row = await self._extract('overwrite')
        self.assertEqual('PDF action', row['action'])
        self.assertEqual('keep', row['nullable'])
        self.assertEqual(['action'], row['conflicts'])
        self.assertEqual('overwrite', row['policy'])

    async def test_csv_after_extraction_survives_subsequent_extraction(self):
        row = await self._extract()
        self.assertEqual('PDF action', row['action'])
        await self._write_csv()
        row = await self._extract()
        self.assertEqual('CSV action', row['action'])
        self.assertEqual(['action'], row['conflicts'])

    async def test_generated_normalization_merges_csv_nodes_and_relationship_endpoints(self):
        await self._write_csv()
        async with self.driver.session(database=fixture.DATABASE) as session:
            await session.run('MERGE (:Bug002Project {projectId: $key})', key=fixture.PROJECT_ID)
        model = {
            'nodes': [
                {'label': label, 'key_property': {'name': key, 'type': 'STRING'}}
                for label, key in [('Bug002Person', 'personId'), ('Bug002Project', 'projectId')]
            ],
            'relationships': [{'type': 'BUG002_ASSIGNED_TO',
                               'start_node_label': 'Bug002Person', 'end_node_label': 'Bug002Project'}],
        }

        async def generated_extract(_extractor, chunk, schema, output_model):
            if chunk.id.endswith('target-chunk'):
                return _parse_typed_response('{}', schema, chunk.id, output_model)
            payload = {}
            for field, spec in output_model.model_fields.items():
                item = get_args(spec.annotation)[0]
                if getattr(item, '_node_label', None) == 'Bug002Person':
                    values = {'personId': ' ' + fixture.PERSON_ID.upper() + ' '}
                elif getattr(item, '_node_label', None) == 'Bug002Project':
                    values = {'projectId': ' ' + fixture.PROJECT_ID.upper() + ' '}
                else:
                    values = dict(zip(item.model_fields, [
                        ' ' + fixture.PERSON_ID.upper() + ' ',
                        ' ' + fixture.PROJECT_ID.upper() + ' ',
                    ]))
                payload[field] = [values]
            return _parse_typed_response(json.dumps(payload), schema, chunk.id, output_model)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'normalized.py'
            await self.client.call_tool('convert_schema', {
                'modeling_output': json.dumps(model), 'output_path': str(path),
                'key_normalization': {'Bug002Person': 'strip_lower', 'Bug002Project': 'strip_lower'},
            })
            await self._extract(schema_path=path, extractor=generated_extract)
        async with self.driver.session(database=fixture.DATABASE) as session:
            result = await session.run('''MATCH (p:Bug002Person)-[r:BUG002_ASSIGNED_TO]->(q:Bug002Project)
                RETURN collect(DISTINCT p.personId) AS people, collect(DISTINCT q.projectId) AS projects,
                       count(r) AS relationships''')
            row = await result.single()
            self.assertEqual([fixture.PERSON_ID], row['people'])
            self.assertEqual([fixture.PROJECT_ID], row['projects'])
            self.assertEqual(1, row['relationships'])
            result = await session.run('MATCH (n) WHERE n:Bug002Person OR n:Bug002Project RETURN count(n) AS nodes')
            self.assertEqual(2, (await result.single())['nodes'])
