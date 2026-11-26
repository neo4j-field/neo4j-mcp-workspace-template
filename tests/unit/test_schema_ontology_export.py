"""Python-to-ontology export preserves supported identity semantics, rejects loss."""
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest

from tests.synthetic.schemas import extraction_source
from mcp_neo4j_entity_graph.models import ExtractionSchema
from mcp_neo4j_entity_graph.ontology_loader import _build_normalizer_config
from mcp_neo4j_entity_graph.ontology_spec import parse_document, serialize_document, validate_document
from mcp_neo4j_entity_graph.schema_generator import generate_extraction_models_code
from mcp_neo4j_entity_graph.schema_ontology_export import export_schema_document


class SchemaOntologyExportTests(unittest.TestCase):
    def export(self, source):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'maintenance.py'
            path.write_text(source)
            return export_schema_document(str(path))

    def test_normative_json_yaml_and_executable_roundtrip(self):
        document = self.export(extraction_source())
        self.assertEqual(document, parse_document(serialize_document(document, 'yaml')))
        self.assertEqual(document, parse_document(serialize_document(document, 'json')))
        payload = validate_document(document)
        self.assertEqual(4, len(payload['nodes']))
        self.assertEqual(4, len(payload['relationships']))
        schema = ExtractionSchema.model_validate(dict(
            entity_types=[dict(label=n['name'], description=n['description'], key_property=next(p['name'] for p in n['properties'] if p['is_key']), properties=n['properties']) for n in payload['nodes']],
            relationship_types=[dict(type=r['name'], description=r['description'], source_entity=r['from'], target_entity=r['to'], properties=r['properties']) for r in payload['relationships']]))
        normalizers = {}
        for node in payload['nodes']:
            for prop in node['properties']:
                chain = [_build_normalizer_config(t, prop, {}, {}) for t in prop.get('normalizers', [])]
                if chain:
                    normalizers[node['name'] + '.' + prop['name']] = chain
        module = types.ModuleType('ontology_export_roundtrip')
        sys.modules[module.__name__] = module
        try:
            exec(compile(generate_extraction_models_code(schema, normalizers), '<roundtrip>', 'exec'), module.__dict__)
            original = sys.modules['extraction_models']
            labels = {c._node_label: c for c in vars(module).values() if isinstance(c, type) and hasattr(c, '_node_label')}
            for label, key, values in [
                ('FixtureProduct', 'name', ['  FIXTURE  PUMP\t001 \n', '\u2003A  B\u2003']),
                ('FixtureSensor', 'code', ['  CV-7 ', ' cv-7 ', ' A  B ']),
            ]:
                old = next(c for c in vars(original).values() if isinstance(c, type) and getattr(c, '_node_label', None) == label)
                for value in values:
                    self.assertEqual(getattr(old(**{key: value}), key), getattr(labels[label](**{key: value}), key))
            product = document['nodes']['FixtureProduct']['properties']
            self.assertTrue(product['name']['key'])
            self.assertTrue(product['name']['must_exist'])
            self.assertEqual('FLOAT', product['allocation']['type'])
            self.assertNotIn('must_exist', product['allocation'])
            self.assertEqual('FixtureProduct', document['relationships']['FIXTURE_USES_PROCEDURE']['from']['node'])
            self.assertEqual('INTEGER', document['relationships']['FIXTURE_USES_PROCEDURE']['properties']['priority']['type'])
        finally:
            sys.modules.pop(module.__name__, None)

    def test_generated_before_validator(self):
        source = extraction_source()
        source = source.replace("@field_validator('name')", "@field_validator('name', mode='before')")
        source = source.replace('return value.strip().lower()', 'if isinstance(value, str):\n            return value.strip().lower()\n        return value')
        self.assertEqual(4, len(self.export(source)['nodes']))

    def test_unknown_semantics_are_actionable(self):
        source = extraction_source()
        cases = [
            source.replace('value.strip().lower()', 'value.replace("x", "y").lower()', 1),
            source.replace('from pydantic import', 'from pydantic import model_validator,', 1).replace('class FixtureProductEntity(BaseModel):', 'class FixtureProductEntity(BaseModel):\n    @model_validator(mode="after")\n    def custom(self):\n        return self\n'),
            source.replace('Optional[float] = None', 'Optional[float] = 1.5', 1),
            source.replace('Optional[float] = None', 'Optional[float] = Field(None, ge=0)', 1),
            source.replace('Optional[float] = None', 'Optional[float] = Field(None, alias="other")', 1),
            source.replace('Optional[float] = None', 'Optional[float] = Field(...)', 1),
            source.replace('class FixtureProductEntity(BaseModel):', 'class FixtureProductEntity(BaseModel):\n    model_config = {"str_to_lower": True}\n'),
        ]
        for changed in cases:
            self.assertNotEqual(source, changed)
            with self.subTest(changed=changed[:100]), self.assertRaisesRegex(ValueError, 'Export supports'):
                self.export(changed)

    def test_endpoint_normalizer_mismatch(self):
        source = extraction_source()
        # Alter the first relationship's endpoint normalizer only.
        offset = source.index('class FixtureMadeAtRel')
        changed = source[:offset] + source[offset:].replace('value.strip().lower()', 'value.strip()', 1)
        with self.assertRaisesRegex(ValueError, 'endpoint normalizer differs'):
            self.export(changed)

    def test_relative_path_rejected(self):
        with self.assertRaisesRegex(ValueError, 'absolute'):
            export_schema_document('schema.py')

    def test_native_scalar_keys_and_required_properties(self):
        for storage_type in ['INTEGER', 'FLOAT', 'BOOLEAN']:
            with self.subTest(storage_type=storage_type):
                schema = ExtractionSchema.model_validate(dict(entity_types=[dict(label='Record', description='Record metadata', key_property='id', properties=[dict(name='id', type=storage_type, required=True), dict(name='status', type='STRING', required=True, description='Lifecycle')])], relationship_types=[dict(type='NEXT', source_entity='Record', target_entity='Record', description='Order', properties=[])]))
                document = self.export(generate_extraction_models_code(schema))
                props = document['nodes']['Record']['properties']
                self.assertEqual(storage_type, props['id']['type'])
                self.assertTrue(props['id']['key'])
                self.assertTrue(props['status']['must_exist'])
                self.assertEqual('Lifecycle', props['status']['description'])


class SchemaOntologyExportToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_tool_exports_without_database_access(self):
        from fastmcp import Client
        from mcp_neo4j_entity_graph.server import create_mcp_server
        class NoGraph:
            def session(self, **kwargs):
                raise AssertionError('export must not access graph or ontology databases')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'maintenance.py'
            path.write_text(extraction_source())
            async with Client(create_mcp_server(NoGraph())) as client:
                result = await client.call_tool('export_extraction_schema_ontology', dict(schema_path=str(path), format='json'))
                document = json.loads(result.content[0].text)
                self.assertEqual(4, len(document['nodes']))
                with self.assertRaisesRegex(Exception, 'absolute'):
                    await client.call_tool('export_extraction_schema_ontology', dict(schema_path='relative.py'))
