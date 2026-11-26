"""EXT-004: typed numeric/boolean endpoints persist with real Cypher matching."""
import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastmcp import Client
from neo4j import AsyncGraphDatabase
from mcp_neo4j_entity_graph.base_extractor import parse_extraction_response
from mcp_neo4j_entity_graph.models import ExtractionSchema
from mcp_neo4j_entity_graph.schema_generator import generate_extraction_models_code
from mcp_neo4j_entity_graph.server import create_mcp_server

LABEL='Ext004Source'
DATABASE=os.getenv('NEO4J_DATABASE','neo4j')


@unittest.skipUnless(os.getenv('NEO4J_MCP_RUN_INTEGRATION')=='1','requires disposable Neo4j')
class SchemaPreflightIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.driver=AsyncGraphDatabase.driver(os.environ['NEO4J_URI'],auth=(os.environ['NEO4J_USERNAME'],os.environ['NEO4J_PASSWORD']))
        self.directory=tempfile.TemporaryDirectory()
        self.path=Path(self.directory.name)/'schema.py'
        await self.cleanup()
        await self.query(f'CREATE (:{LABEL} {{id:"ext004-source",text:"typed endpoint fixture"}})')
        types=[('Ext004Int','number','INTEGER'),('Ext004Flag','flag','BOOLEAN'),('Ext004Target','name','STRING')]
        raw={'entity_types':[{'label':label,'description':'fixture','key_property':key,'properties':[{'name':key,'type':kind}]} for label,key,kind in types], 'relationship_types':[{'type':kind,'description':'fixture','source_entity':source,'target_entity':'Ext004Target'} for kind,source in [('EXT004_INT_LINK','Ext004Int'),('EXT004_FLAG_LINK','Ext004Flag')]]}
        self.source=generate_extraction_models_code(ExtractionSchema.model_validate(raw))
        self.path.write_text(self.source)
        self.payload={'ext004_ints':[{'number':0}],'ext004_flags':[{'flag':False}],'ext004_targets':[{'name':'CaseSensitive'}], 'ext004_int_link':[{'ext004_int_number':0,'ext004_target_name':'CaseSensitive'}], 'ext004_flag_link':[{'ext004_flag_flag':False,'ext004_target_name':'CaseSensitive'}]}

    async def query(self,query,**params):
        async with self.driver.session(database=DATABASE) as session:
            return await (await session.run(query,**params)).data()

    async def cleanup(self):
        await self.query('''MATCH (n) WHERE n:Ext004Source OR n:Ext004Int OR n:Ext004Flag OR n:Ext004Target
            OR ((n:EntityExtractionRun OR n:EntityExtractionClaim) AND n.sourceLabel=$label) DETACH DELETE n''',label=LABEL)

    async def asyncTearDown(self):
        await self.cleanup()
        await self.driver.close()
        self.directory.cleanup()

    async def extract(self):
        async def typed(_self,chunk,schema,output_model):
            return parse_extraction_response(json.dumps(self.payload),schema,chunk.id,output_model)
        async with Client(create_mcp_server(self.driver,database=DATABASE)) as client:
            with patch('mcp_neo4j_entity_graph.server.TextExtractor.extract_chunk',new=typed):
                started=json.loads((await client.call_tool('extract_entities',{'schema':str(self.path),'source_label':LABEL,'source_ids':['ext004-source'],'extraction_scope':'ext004-fixture','force':True})).content[0].text)
                for _ in range(200):
                    status=json.loads((await client.call_tool('check_extraction_status',{'job_id':started['job_id']})).content[0].text)
                    if status['status'] in ['complete','failed']:return status
                    await asyncio.sleep(.01)
                self.fail('schema fixture timed out')

    async def test_numeric_zero_and_boolean_false_match_native_entity_keys(self):
        status=await self.extract()
        self.assertEqual('complete',status['status'],status)
        self.assertEqual(2,status['relationships_created'])
        row=(await self.query('''MATCH (i:Ext004Int)-[:EXT004_INT_LINK]->(t:Ext004Target)<-[:EXT004_FLAG_LINK]-(b:Ext004Flag)
            RETURN i.number AS number,b.flag AS flag,t.name AS name'''))[0]
        self.assertEqual({'number':0,'flag':False,'name':'CaseSensitive'},row)
        self.assertIs(type(row['number']),int)
        self.assertIs(type(row['flag']),bool)

    async def test_bad_validator_return_fails_without_replacing_prior_owned_graph(self):
        self.assertEqual('complete',(await self.extract())['status'])
        altered=self.source.replace('    number: int = Field(','''    @field_validator("number", mode="after")
    @classmethod
    def corrupt_key(cls, value):
        return str(value)

    number: int = Field(''',1)
        self.path.write_text(altered)
        failed=await self.extract()
        self.assertEqual('failed',failed['status'])
        self.assertIn('expected finite INTEGER',str(failed['failure_details']))
        row=(await self.query('MATCH (:Ext004Int)-[r:EXT004_INT_LINK]->() RETURN count(r) AS count'))[0]
        self.assertEqual(1,row['count'])
