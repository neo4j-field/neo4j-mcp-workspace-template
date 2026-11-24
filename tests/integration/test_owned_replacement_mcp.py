"""EXT-001: source/scope replacement, shared support, external ownership and rollback."""
import asyncio
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastmcp import Client
from neo4j import AsyncGraphDatabase
from mcp_neo4j_entity_graph.models import ChunkExtractionResult, ExtractionSchema
from mcp_neo4j_entity_graph.schema_generator import generate_extraction_models_code
from mcp_neo4j_entity_graph.server import create_mcp_server

DATABASE = os.getenv('NEO4J_DATABASE', 'neo4j')
LABEL = 'Ext001Source'
ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(os.getenv('NEO4J_MCP_RUN_INTEGRATION') == '1', 'requires disposable Neo4j')
class OwnedReplacementIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.driver = AsyncGraphDatabase.driver(os.environ['NEO4J_URI'], auth=(os.environ['NEO4J_USERNAME'], os.environ['NEO4J_PASSWORD']))
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'schema.py'
        self.outputs = {}
        await self.cleanup()
        await self.query(f'UNWIND ["a", "b"] AS id CREATE (:{LABEL} {{id:id,text:id}})')

    async def query(self, query, **params):
        async with self.driver.session(database=DATABASE) as session:
            return await (await session.run(query, **params)).data()

    async def cleanup(self):
        await self.query('''MATCH (n) WHERE n:Ext001Source OR n:Ext001Item OR n:Ext001Removed
            OR ((n:EntityExtractionRun OR n:EntityExtractionClaim) AND n.sourceLabel=$label)
            DETACH DELETE n''', label=LABEL)

    async def asyncTearDown(self):
        await self.cleanup()
        await self.driver.close()
        self.directory.cleanup()

    def output(self, source='a', *, full=False, empty=False, action=None, obsolete='old', failed=False):
        entities = [] if empty else [{'label':'Ext001Item','properties':{'name':'keep', **({'action':action} if action else {}), **({'obsolete':obsolete} if full else {})}}]
        relationships = []
        if full and not empty:
            entities.append({'label':'Ext001Removed','properties':{'name':'removed'}})
            relationships.append({'type':'EXT001_REL','source_label':'Ext001Item','source_key':'keep','target_label':'Ext001Removed','target_key':'removed'})
        self.outputs[source] = dict(chunk_id=source, entities=entities, relationships=relationships,
                                    outcome='failed' if failed else ('empty' if empty else 'success'),
                                    error='fixture failure' if failed else None)

    async def extract(self, *, sources=None, scope='test', small=False, policy='preserve_existing'):
        entities = [{'label': label, 'description':'fixture', 'key_property':'name',
                     'properties':[{'name':'name','type':'STRING'}, {'name':'action','type':'STRING'}] + ([] if small else [{'name':'obsolete','type':'STRING'}])}
                    for label in (['Ext001Item'] if small else ['Ext001Item','Ext001Removed'])]
        schema = ExtractionSchema.model_validate({'entity_types':entities, 'relationship_types':[] if small else [
            {'type':'EXT001_REL','description':'fixture','source_entity':'Ext001Item','target_entity':'Ext001Removed'}]})
        self.path.write_text(generate_extraction_models_code(schema))
        async def stub(_self, chunk, _schema, _model):
            return ChunkExtractionResult.model_validate(self.outputs[chunk.id])
        async with Client(create_mcp_server(self.driver, database=DATABASE)) as client:
            with patch('mcp_neo4j_entity_graph.server.TextExtractor.extract_chunk', new=stub):
                args = {'schema':str(self.path),'source_label':LABEL,'source_ids':sources or ['a'],
                        'extraction_scope':scope,'property_policy':policy,'force':True,'batch_size':1}
                started = json.loads((await client.call_tool('extract_entities', args)).content[0].text)
                for _ in range(300):
                    status = json.loads((await client.call_tool('check_extraction_status', {'job_id':started['job_id']})).content[0].text)
                    if status['status'] in ['complete','failed']:
                        return status
                    await asyncio.sleep(.01)
                self.fail('replacement timed out')

    async def good(self, **kwargs):
        result = await self.extract(**kwargs)
        self.assertEqual('complete', result['status'], result)
        return result

    async def test_removed_schema_label_relationship_and_property_are_cleaned(self):
        self.output(full=True)
        await self.good()
        original = (await self.query('MATCH (n:Ext001Item) RETURN elementId(n) AS id'))[0]['id']
        self.output()
        await self.good(small=True)
        row = (await self.query('MATCH (n:Ext001Item) RETURN n.obsolete AS obsolete, elementId(n) AS id'))[0]
        self.assertIsNone(row['obsolete'])
        self.assertEqual(original, row['id'])
        self.assertEqual(0, (await self.query('MATCH (n:Ext001Removed) RETURN count(n) AS count'))[0]['count'])
        self.assertEqual(0, (await self.query('MATCH ()-[r:EXT001_REL]->() RETURN count(r) AS count'))[0]['count'])

    async def test_empty_replacement_removes_owned_graph(self):
        self.output(full=True)
        await self.good()
        self.output(empty=True)
        await self.good()
        self.assertEqual(0, (await self.query('MATCH (n) WHERE n:Ext001Item OR n:Ext001Removed RETURN count(n) AS count'))[0]['count'])

    async def test_other_source_support_survives_and_inherits_owned_property(self):
        self.output(action='from a')
        await self.good()
        self.output('b', action='from b')
        await self.good(sources=['b'])
        self.output(empty=True)
        await self.good()
        row = (await self.query('MATCH (n:Ext001Item)-[:EXTRACTED_FROM]->(s:Ext001Source) RETURN n.action AS action, collect(s.id) AS sources'))[0]
        self.assertEqual('from b', row['action'])
        self.assertEqual(['b'], row['sources'])
        self.output('b', empty=True)
        await self.good(sources=['b'])
        self.assertEqual([], await self.query('MATCH (n:Ext001Item) RETURN n'))

    async def test_other_scope_is_preserved(self):
        self.output(action='one')
        await self.good(scope='one')
        self.output(action='two')
        await self.good(scope='two')
        self.output(empty=True)
        await self.good(scope='one')
        row = (await self.query('MATCH (n:Ext001Item)-[r:EXTRACTED_FROM]->() RETURN n.action AS action,count(r) AS links'))[0]
        self.assertEqual({'action':'two','links':1}, row)

    async def test_preexisting_csv_node_and_properties_survive(self):
        await self.query('CREATE (:Ext001Item {name:"keep", action:"CSV", userFlag:"keep"})')
        self.output(full=True, action='PDF')
        await self.good()
        self.output(empty=True)
        await self.good()
        row = (await self.query('MATCH (n:Ext001Item) RETURN n.action AS action,n.userFlag AS flag,n.obsolete AS obsolete'))[0]
        self.assertEqual({'action':'CSV','flag':'keep','obsolete':None}, row)

    def compiler(self):
        spec = importlib.util.spec_from_file_location('ownership_ingest_compiler', ROOT/'mcp-neo4j-ingest/src/mcp_neo4j_ingest/query_compiler.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    async def test_csv_import_after_extraction_protects_same_value(self):
        self.output(action='same')
        await self.good()
        query = self.compiler().compile_node_ingest_query({'label':'Ext001Item','key_property':{'name':'name'},'properties':[{'name':'action'}]})
        await self.query(query, records=[{'name':'keep','action':'same'}])
        self.output(empty=True)
        await self.good()
        row = (await self.query('MATCH (n:Ext001Item) RETURN n.name AS name,n.action AS action'))[0]
        self.assertEqual({'name':'keep','action':'same'}, row)

    async def test_csv_relationship_after_extraction_is_not_deleted(self):
        self.output(full=True)
        await self.good()
        rel = {'type':'EXT001_REL','start_node_label':'Ext001Item','end_node_label':'Ext001Removed'}
        nodes = [{'label':label,'key_property':{'name':'name','source':{'column_name':column}}} for label,column in [('Ext001Item','a'),('Ext001Removed','b')]]
        query = self.compiler().compile_relationship_ingest_query({'nodes':nodes}, rel)
        await self.query(query, records=[{'a':'keep','b':'removed'}])
        self.output(empty=True)
        await self.good()
        self.assertEqual(1, (await self.query('MATCH ()-[r:EXT001_REL]->() RETURN count(r) AS count'))[0]['count'])

    async def test_external_edit_is_retained(self):
        self.output(full=True)
        await self.good()
        await self.query('MATCH (n:Ext001Item) SET n.obsolete="user edit"')
        self.output(empty=True)
        await self.good()
        self.assertEqual('user edit', (await self.query('MATCH (n:Ext001Item) RETURN n.obsolete AS value'))[0]['value'])

    async def test_missing_endpoint_rolls_back_cleanup_and_new_properties(self):
        self.output(full=True)
        await self.good()
        self.output(full=True, obsolete='new')
        self.outputs['a']['relationships'][0]['target_key']='missing'
        result = await self.extract(policy='overwrite')
        self.assertEqual('failed', result['status'])
        row = (await self.query('MATCH (n:Ext001Item)-[r:EXT001_REL]->(:Ext001Removed) RETURN n.obsolete AS value,count(r) AS edges'))[0]
        self.assertEqual({'value':'old','edges':1}, row)

    async def test_model_failure_does_not_publish_partial_replacement(self):
        self.output(full=True)
        await self.good()
        self.output(empty=True)
        self.output('b', failed=True)
        result = await self.extract(sources=['a','b'])
        self.assertEqual('failed', result['status'])
        self.assertEqual(0, result['sources_persisted'])
        self.assertEqual(1, (await self.query('MATCH ()-[r:EXT001_REL]->() RETURN count(r) AS count'))[0]['count'])

    async def test_shared_relationship_and_properties_follow_remaining_source(self):
        self.output(full=True)
        self.outputs['a']['relationships'][0]['properties'] = {'confidence':'a','obsolete':'old'}
        await self.good()
        self.output('b', full=True)
        self.outputs['b']['relationships'][0]['properties'] = {'confidence':'b'}
        await self.good(sources=['b'])
        self.output(empty=True)
        await self.good()
        row = (await self.query('MATCH ()-[r:EXT001_REL]->() RETURN r.confidence AS value,r.obsolete AS obsolete'))[0]
        self.assertEqual({'value':'b','obsolete':None}, row)
        self.output('b', empty=True)
        await self.good(sources=['b'])
        self.assertEqual([], await self.query('MATCH ()-[r:EXT001_REL]->() RETURN r'))

    async def test_external_relationship_edit_is_retained(self):
        self.output(full=True)
        self.outputs['a']['relationships'][0]['properties'] = {'note':'original'}
        await self.good()
        await self.query('MATCH ()-[r:EXT001_REL]->() SET r.note="external"')
        self.output(empty=True)
        await self.good()
        self.assertEqual('external', (await self.query('MATCH ()-[r:EXT001_REL]->() RETURN r.note AS value'))[0]['value'])

    async def test_cancellation_preserves_prior_graph_and_stops_child_work(self):
        self.output(full=True)
        await self.good()
        entered = asyncio.Event()
        stopped = asyncio.Event()
        release = asyncio.Event()
        async def waiting(_self, chunk, _schema, _model):
            entered.set()
            try:
                await release.wait()
                return ChunkExtractionResult(chunk_id=chunk.id, outcome='empty')
            finally:
                stopped.set()
        async with Client(create_mcp_server(self.driver, database=DATABASE)) as client:
            with patch('mcp_neo4j_entity_graph.server.TextExtractor.extract_chunk', new=waiting):
                args = {'schema':str(self.path),'source_label':LABEL,'source_ids':['a'],
                        'extraction_scope':'test','force':True}
                started = json.loads((await client.call_tool('extract_entities', args)).content[0].text)
                try:
                    await asyncio.wait_for(entered.wait(), 3)
                    await client.call_tool('cancel_extraction', {'job_id':started['job_id']})
                    await asyncio.wait_for(stopped.wait(), 3)
                    status = json.loads((await client.call_tool('check_extraction_status', {'job_id':started['job_id']})).content[0].text)
                    self.assertEqual('cancelled', status['status'])
                finally:
                    release.set()
        row = (await self.query('MATCH (n:Ext001Item)-[r:EXT001_REL]->() RETURN n.obsolete AS value,count(r) AS edges'))[0]
        self.assertEqual({'value':'old','edges':1}, row)

    async def test_preexisting_relationship_values_survive_extraction_and_cleanup(self):
        await self.query('CREATE (:Ext001Item {name:"keep"})-[:EXT001_REL {role:"CSV"}]->(:Ext001Removed {name:"removed"})')
        self.output(full=True)
        self.outputs['a']['relationships'][0]['properties'] = {'role':'PDF'}
        await self.good()
        self.assertEqual('CSV', (await self.query('MATCH ()-[r:EXT001_REL]->() RETURN r.role AS role'))[0]['role'])
        self.assertEqual(['role'], (await self.query('MATCH (c:EntityExtractionClaim {sourceLabel:$label}) RETURN c.conflictingProperties AS conflicts', label=LABEL))[0]['conflicts'])
        self.output(empty=True)
        await self.good()
        self.assertEqual('CSV', (await self.query('MATCH ()-[r:EXT001_REL]->() RETURN r.role AS role'))[0]['role'])

    async def test_other_legacy_source_proposals_support_without_granting_ownership(self):
        await self.query('MATCH (b:Ext001Source {id:"b"}) CREATE (:Ext001Item {name:"keep"})-[:EXTRACTED_FROM {proposedPropertiesJson:$proposal}]->(b)', proposal='{"name":"keep"}')
        self.output(full=True)
        await self.good()
        self.output(empty=True)
        await self.good()
        row = (await self.query('MATCH (n:Ext001Item)-[:EXTRACTED_FROM]->(b:Ext001Source {id:"b"}) RETURN n.obsolete AS obsolete,count(b) AS legacyLinks'))[0]
        self.assertEqual({'obsolete':None,'legacyLinks':1}, row)

    async def test_unknown_legacy_property_support_refuses_cleanup_and_rolls_back(self):
        await self.query('MATCH (b:Ext001Source {id:"b"}) CREATE (:Ext001Item {name:"keep"})-[:EXTRACTED_FROM]->(b)')
        self.output(full=True)
        await self.good()
        self.output(empty=True)
        status = await self.extract()
        self.assertEqual('failed', status['status'])
        self.assertIn('Legacy property support', status['error'])
        self.assertEqual('old', (await self.query('MATCH (n:Ext001Item) RETURN n.obsolete AS value'))[0]['value'])
        self.assertEqual(1, (await self.query('MATCH ()-[r:EXT001_REL]->() RETURN count(r) AS count'))[0]['count'])

    async def test_source_mutation_during_extraction_refuses_stale_publication(self):
        self.output(full=True)
        await self.good()
        self.output(full=True, obsolete='new')
        entered = asyncio.Event()
        release = asyncio.Event()
        async def waiting(_self, chunk, _schema, _model):
            entered.set()
            await release.wait()
            return ChunkExtractionResult.model_validate(self.outputs[chunk.id])
        async with Client(create_mcp_server(self.driver, database=DATABASE)) as client:
            with patch('mcp_neo4j_entity_graph.server.TextExtractor.extract_chunk', new=waiting):
                args = {'schema':str(self.path),'source_label':LABEL,'source_ids':['a'],
                        'extraction_scope':'test','force':True}
                started = json.loads((await client.call_tool('extract_entities', args)).content[0].text)
                await asyncio.wait_for(entered.wait(), 3)
                await self.query('MATCH (s:Ext001Source {id:"a"}) SET s.text="changed during model call"')
                release.set()
                for _ in range(300):
                    status = json.loads((await client.call_tool('check_extraction_status', {'job_id':started['job_id']})).content[0].text)
                    if status['status'] in ['complete','failed']:
                        break
                    await asyncio.sleep(.01)
                self.assertEqual('failed', status['status'])
                self.assertIn('Source inputs changed', status['error'])
        self.assertEqual('old', (await self.query('MATCH (n:Ext001Item) RETURN n.obsolete AS value'))[0]['value'])

    async def test_partial_duplicate_records_retain_all_supported_fields(self):
        self.output(full=True)
        self.outputs['a']['entities'].append({'label':'Ext001Item','properties':{'name':'keep','action':'from a'}})
        self.outputs['a']['relationships'][0]['properties']={'obsolete':'edge old'}
        duplicate = {**self.outputs['a']['relationships'][0], 'properties':{'confidence':'from a'}}
        self.outputs['a']['relationships'].append(duplicate)
        await self.good()
        self.output('b', full=True, action='from b')
        await self.good(sources=['b'])
        self.output('b', empty=True)
        await self.good(sources=['b'])
        row = (await self.query('MATCH (n:Ext001Item)-[r:EXT001_REL]->() RETURN n.obsolete AS obsolete,n.action AS action,r.obsolete AS edge,r.confidence AS confidence'))[0]
        self.assertEqual({'obsolete':'old','action':'from a','edge':'edge old','confidence':'from a'}, row)

    async def test_null_withdraws_only_the_prior_owned_assertion(self):
        self.output(full=True)
        await self.good()
        self.output(full=True, obsolete=None)
        await self.good()
        self.assertIsNone((await self.query('MATCH (n:Ext001Item) RETURN n.obsolete AS obsolete'))[0]['obsolete'])
        self.assertEqual(1, (await self.query('MATCH ()-[r:EXT001_REL]->() RETURN count(r) AS count'))[0]['count'])
