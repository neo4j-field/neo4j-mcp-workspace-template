"""Exercise fixture schemas against the real workspace validators and compilers."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

from tests.synthetic.schemas import (data_model, extraction_data_model, extraction_source, ingest_plan, ontology_spec, write_schemas)

ROOT=Path(__file__).resolve().parents[2]
for package in ['mcp-neo4j-entity-graph','mcp-neo4j-ingest']:
    sys.path.insert(0,str(ROOT/package/'src'))
from mcp_neo4j_entity_graph.ontology_spec import validate_document, parse_document
from mcp_neo4j_entity_graph.base_extractor import schema_from_pydantic_module
from mcp_neo4j_ingest.query_compiler import compile_node_ingest_query, compile_relationship_ingest_query


class SyntheticSchemaTests(unittest.TestCase):
    def test_normative_ontology_and_generated_python_static_contract(self):
        payload=validate_document(ontology_spec())
        self.assertEqual(4,len(payload['nodes']))
        self.assertEqual(4,len(payload['relationships']))
        self.assertIn('FixtureFacilityAliases',payload['alias_maps'])
        module=type(sys)('synthetic_fixture_schema')
        sys.modules[module.__name__]=module
        try:
            exec(compile(extraction_source(),'<synthetic-schema>','exec'),module.__dict__)
            schema=schema_from_pydantic_module(module)
            self.assertEqual(4,len(schema.entity_types))
            self.assertEqual(4,len(schema.relationship_types))
            self.assertEqual('fixture pump 00001',module.FixtureProductEntity(name='  FIXTURE PUMP 00001 ').name)
            self.assertNotEqual(module.FixtureSensorEntity(code='CV-7').code,module.FixtureSensorEntity(code='cv-7').code)
            self.assertNotIn('commissioned',extraction_source())
        finally:sys.modules.pop(module.__name__,None)

    def test_ingest_plan_honors_own_file_and_endpoint_column_mappings(self):
        plan=ingest_plan()
        for entry in plan['nodes']:
            query=compile_node_ingest_query(entry['node'])
            self.assertIn('record.code' if entry['node']['label']=='FixtureSensor' else 'record.name',query)
        for entry in plan['relationships']:
            query=compile_relationship_ingest_query(entry['endpoint_data_model'],entry['relationship'])
            self.assertIn('record.procedure_name' if entry['relationship']['type']=='FIXTURE_USES_PROCEDURE' else 'record.facility_name',query)
            self.assertIn('MERGE (start)-[relationship:',query)
        product=next(e['node'] for e in plan['nodes'] if e['node']['label']=='FixtureProduct')
        query=compile_node_ingest_query(product)
        self.assertIn('date(record.commissioned)',query)
        self.assertIn('toFloat(record.allocation)',query)
        self.assertIn('node.productCode = record.product_code',query)
        self.assertIn('toBoolean(record.active)',query)

    def test_positive_and_negative_artifacts_are_separate_and_equivalent(self):
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder); artifacts=write_schemas({'products':[{'name':'fixture pump 00001'}]},output)
            for name in artifacts.values():self.assertTrue((output/name).exists(),name)
            self.assertEqual(parse_document((output/artifacts['ontology_json']).read_text()),parse_document((output/artifacts['ontology_yaml']).read_text()))
            with self.assertRaises(ValueError):validate_document(json.loads((output/'negative/invalid_ontology.json').read_text()))
            with self.assertRaises(UnicodeDecodeError):(output/'negative/invalid_utf8.txt').read_text(encoding='utf-8')
            self.assertIn('structured_guard',json.loads((output/'lifecycle/expected.json').read_text()))

    def test_ontology_generated_validators_apply_aliases_blocklists_and_case(self):
        from mcp_neo4j_entity_graph.models import ExtractionSchema
        from mcp_neo4j_entity_graph.ontology_loader import _build_normalizer_config
        from mcp_neo4j_entity_graph.schema_generator import generate_extraction_models_code
        payload=validate_document(ontology_spec())
        schema=ExtractionSchema.model_validate({'entity_types':[dict(label=n['name'],description=n['description'],key_property=next(p['name'] for p in n['properties'] if p['is_key']),properties=n['properties']) for n in payload['nodes']],
            'relationship_types':[dict(type=r['name'],description=r['description'],source_entity=r['from'],target_entity=r['to'],properties=r['properties']) for r in payload['relationships']]})
        normalizers={}
        for node in payload['nodes']:
            for prop in node['properties']:
                chain=[_build_normalizer_config(tag,prop,payload['alias_maps'],{k:frozenset(v) for k,v in payload['blocklists'].items()}) for tag in prop.get('normalizers',[])]
                if chain:normalizers[node['name']+'.'+prop['name']]=chain
        module=type(sys)('synthetic_ontology_schema');sys.modules[module.__name__]=module
        try:
            exec(compile(generate_extraction_models_code(schema,normalizers),'<synthetic-ontology>','exec'),module.__dict__)
            classes={getattr(v,'_node_label',None):v for v in vars(module).values() if isinstance(v,type)}
            self.assertEqual('fixture facility 01',classes['FixtureFacility'](name='  North Works  ').name)
            self.assertEqual('__SKIP__',classes['FixtureFacility'](name='Unknown Facility').name)
            self.assertEqual('CV-7',classes['FixtureSensor'](code=' CV-7 ').code)
            self.assertEqual('cv-7',classes['FixtureSensor'](code=' cv-7 ').code)
        finally:sys.modules.pop(module.__name__,None)
