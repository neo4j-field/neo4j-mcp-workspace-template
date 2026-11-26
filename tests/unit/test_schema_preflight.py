"""EXT-004 schema errors must fail before source/model/write work."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastmcp import Client

from mcp_neo4j_entity_graph.base_extractor import load_extraction_output_model, parse_extraction_response, schema_from_pydantic_module
from mcp_neo4j_entity_graph.models import ExtractionSchema
from mcp_neo4j_entity_graph.normalizer_templates import NormalizerConfig
from mcp_neo4j_entity_graph.schema_generator import generate_extraction_models_code
from mcp_neo4j_entity_graph.schema_validation import validate_extraction_schema
from mcp_neo4j_entity_graph.server import create_mcp_server


def raw_schema():
    return {'entity_types':[
        {'label':'NumericItem','description':'item','key_property':'number','properties':[{'name':'number','type':'INTEGER'}]},
        {'label':'Target','description':'target','key_property':'name','properties':[{'name':'name','type':'STRING'}]},
    ], 'relationship_types':[{'type':'LINKS_TO','description':'link','source_entity':'NumericItem','target_entity':'Target','properties':[]}]}


def load_source(source):
    directory = tempfile.TemporaryDirectory()
    path = Path(directory.name) / 'schema.py'
    path.write_text(source)
    output = load_extraction_output_model(str(path))
    schema = schema_from_pydantic_module(sys.modules['extraction_models'])
    return directory, output, schema


class SchemaPreflightTests(unittest.IsolatedAsyncioTestCase):
    def test_invalid_raw_models_are_rejected_without_silent_type_fallback(self):
        cases=[]
        value=raw_schema(); value['entity_types'].append(copy.deepcopy(value['entity_types'][0])); cases.append((value,'duplicate'))
        value=raw_schema(); value['relationship_types'].append(copy.deepcopy(value['relationship_types'][0])); cases.append((value,'duplicate'))
        value=raw_schema(); value['entity_types'][0]['properties'].append({'name':'number','type':'INTEGER'}); cases.append((value,'duplicate'))
        value=raw_schema(); value['relationship_types'][0]['target_entity']='Missing'; cases.append((value,'endpoints'))
        value=raw_schema(); value['entity_types'][0]['properties'][0]['type']='DATE'; cases.append((value,'unsupported property type'))
        value=raw_schema(); value['entity_types'][0]['label']='Item`) DELETE n //'; cases.append((value,'unsafe'))
        value=raw_schema(); value['entity_types'][0]['properties'].append({'name':'__extractionCreated','type':'BOOLEAN'}); cases.append((value,'reserved'))
        value=raw_schema(); value['entity_types'][0]['label']='EmbeddingPublicationLock'; cases.append((value,'Reserved entity label'))
        for value, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                generate_extraction_models_code(ExtractionSchema.model_validate(value))

    def test_generated_name_collisions_fail_before_python_output_is_emitted(self):
        raw=raw_schema()
        raw['entity_types']=[{'label':label,'description':'item','key_property':'name','properties':[]} for label in ['FooBar','Foo_Bar']]
        raw['relationship_types']=[]
        with self.assertRaisesRegex(ValueError,'duplicate'):
            generate_extraction_models_code(ExtractionSchema.model_validate(raw))

    def test_native_integer_zero_key_and_required_relationship_property(self):
        raw=raw_schema()
        raw['relationship_types'][0]['properties']=[{'name':'weight','type':'FLOAT','required':True}]
        source=generate_extraction_models_code(ExtractionSchema.model_validate(raw))
        # Explicit bindings survive required property reordering.
        weight=next(line for line in source.splitlines() if line.startswith('    weight:'))
        endpoint=next(line for line in source.splitlines() if line.startswith('    numeric_item_number:'))
        source=source.replace(weight+'\n','').replace(endpoint,weight+'\n'+endpoint)
        directory, output, schema=load_source(source)
        try:
            result=parse_extraction_response(json.dumps({'numeric_items':[{'number':0}], 'targets':[{'name':'CaseSensitive'}], 'links_to':[{'numeric_item_number':0,'target_name':'CaseSensitive','weight':1.25}]}),schema,'source',output)
            self.assertEqual('success',result.outcome.value)
            self.assertEqual(0,result.relationships[0].source_key)
            self.assertIs(type(result.relationships[0].source_key),int)
            self.assertEqual('CaseSensitive',result.relationships[0].target_key)
            self.assertEqual({'weight':1.25},result.relationships[0].properties)
        finally:directory.cleanup()

    def test_boolean_false_key_is_not_dropped_or_stringified(self):
        raw=raw_schema(); raw['entity_types'][0]['properties'][0]['type']='BOOLEAN'
        directory, output, schema=load_source(generate_extraction_models_code(ExtractionSchema.model_validate(raw)))
        try:
            result=parse_extraction_response('{"numeric_items":[{"number":false}],"targets":[{"name":"X"}],"links_to":[{"numeric_item_number":false,"target_name":"X"}]}',schema,'source',output)
            self.assertEqual('success',result.outcome.value)
            self.assertIs(False,result.relationships[0].source_key)
        finally:directory.cleanup()

    def test_file_endpoint_metadata_types_and_constraints_must_match(self):
        source=generate_extraction_models_code(ExtractionSchema.model_validate(raw_schema()))
        variants=[
            (source.replace('_start_key_property: ClassVar[str] = "number"','_start_key_property: ClassVar[str] = "missing"'),'must match'),
            (source.replace('numeric_item_number: int','numeric_item_number: str'),'endpoint type'),
            (source.replace('number: int = Field(...','number: Optional[int] = Field(default=None'),'key must be required'),
            (source.replace('numeric_item_number: int = Field(...','numeric_item_number: int = Field(..., ge=1'),'constraints'),
            (source.replace('number: int','number: list[int]'),'unsupported annotation'),
        ]
        for altered, message in variants:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as directory:
                path=Path(directory)/'schema.py'; path.write_text(altered)
                load_extraction_output_model(str(path))
                with self.assertRaisesRegex(ValueError,message):
                    schema_from_pydantic_module(sys.modules['extraction_models'])

    def test_literal_properties_supported_and_heterogeneous_unions_rejected(self):
        source=generate_extraction_models_code(ExtractionSchema.model_validate(raw_schema()))
        source=source.replace('from typing import ', 'from typing import Literal, ',1).replace('    name: str = Field(...','    name: Literal["X", "Y"] = Field(...').replace('    target_name: str = Field(...','    target_name: Literal["X", "Y"] = Field(...')
        directory, _, schema=load_source(source)
        directory.cleanup()
        self.assertEqual('STRING',schema.entity_types[1].properties[0].type)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'schema.py';path.write_text(source.replace('Literal["X", "Y"]','str | int'))
            load_extraction_output_model(str(path))
            with self.assertRaisesRegex(ValueError,'heterogeneous unions'):
                schema_from_pydantic_module(sys.modules['extraction_models'])

    def test_compose_key_ontology_path_remains_supported_but_missing_keys_fail_visibly(self):
        raw={'entity_types':[{'label':'Record','description':'record','key_property':'name','properties':[{'name':'name','type':'STRING'},{'name':'code','type':'STRING'}]}]}
        normalizers={'Record.__model__':[NormalizerConfig(tag='compose_name_from_fields',name_template='{code}',alias_map_name='name')]}
        directory, output, schema=load_source(generate_extraction_models_code(ExtractionSchema.model_validate(raw),normalizers))
        try:
            valid=parse_extraction_response('{"records":[{"name":null,"code":"abc"}]}',schema,'source',output)
            self.assertEqual('abc',valid.entities[0].properties['name'])
            failed=parse_extraction_response('{"records":[{"name":null,"code":null}]}',schema,'source',output)
            self.assertEqual('failed',failed.outcome.value)
            self.assertIn('missing/empty',failed.error)
        finally:directory.cleanup()

    async def test_invalid_file_fails_before_document_driver_or_model_calls(self):
        class NoGraph:
            def session(self, **_kwargs):raise AssertionError('document database must not be read/written')
        source=generate_extraction_models_code(ExtractionSchema.model_validate(raw_schema())).replace('number: int','number: dict[str, str]')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'schema.py';path.write_text(source)
            with patch('mcp_neo4j_entity_graph.server.TextExtractor.extract_chunk',new=AsyncMock()) as model:
                async with Client(create_mcp_server(NoGraph())) as client:
                    with self.assertRaisesRegex(Exception,'unsupported annotation'):
                        await client.call_tool('extract_entities',{'schema':str(path)})
                model.assert_not_awaited()

    async def test_invalid_ontology_is_rejected_before_cache_write_or_document_work(self):
        class NoGraph:
            def session(self, **_kwargs):raise AssertionError('document database must not be read/written')
        raw=raw_schema();raw['relationship_types'][0]['target_entity']='Missing'
        malformed=ExtractionSchema.model_validate(raw)
        with patch('mcp_neo4j_entity_graph.server.load_ontology',new=AsyncMock(return_value=(malformed,{}))), patch('mcp_neo4j_entity_graph.server.TextExtractor.extract_chunk',new=AsyncMock()) as model:
            async with Client(create_mcp_server(NoGraph())) as client:
                with self.assertRaisesRegex(Exception,'endpoints'):
                    await client.call_tool('extract_entities',{'ontology_name':'invalid-ontology'})
            model.assert_not_awaited()

    def test_descriptions_and_enum_values_are_data_not_python_code(self):
        raw=raw_schema()
        description='quotes """\nraise RuntimeError("must never execute")\n#\rcontrol'
        raw['entity_types'][0]['description']=description
        raw['entity_types'][1]['properties'].append({'name':'category','type':'STRING','description':description})
        values=['normal','quote"value','line\nvalue']
        normalizers={'Target.category':[NormalizerConfig(tag='enum_validate',enum_values=values)]}
        directory, output, schema=load_source(generate_extraction_models_code(ExtractionSchema.model_validate(raw),normalizers))
        try:
            self.assertEqual(description,schema.entity_types[0].description)
            parsed=output.model_validate({'targets':[{'name':'X','category':'quote"value'}]})
            self.assertEqual('quote"value',parsed.targets[0].category)
        finally:directory.cleanup()
        raw['entity_types'][1]['properties'][-1]['type']='INTEGER'
        with self.assertRaisesRegex(ValueError,'enum_validate requires a STRING'):
            generate_extraction_models_code(ExtractionSchema.model_validate(raw),normalizers)

    async def test_ontology_requires_exactly_one_key_property(self):
        from mcp_neo4j_entity_graph.ontology_loader import load_ontology
        class Result:
            async def single(self):return {'name':'ontology'}
        class Session:
            async def __aenter__(self):return self
            async def __aexit__(self,*_):return None
            async def run(self,*_args,**_kwargs):return Result()
        class Driver:
            def session(self,**_kwargs):return Session()
        nodes=[{'name':'Record','properties':[{'name':name,'type':'STRING','is_key':True} for name in ['one','two']]}]
        with patch('mcp_neo4j_entity_graph.ontology_loader._fetch_node_types',new=AsyncMock(return_value=nodes)), patch('mcp_neo4j_entity_graph.ontology_loader._fetch_relationship_types',new=AsyncMock(return_value=[])), patch('mcp_neo4j_entity_graph.ontology_loader._fetch_alias_maps',new=AsyncMock(return_value={})), patch('mcp_neo4j_entity_graph.ontology_loader._fetch_blocklists',new=AsyncMock(return_value={})):
            with self.assertRaisesRegex(ValueError,'exactly one key property'):
                await load_ontology(Driver(),'ontology','ontology')

    def test_missing_duplicate_and_non_list_output_bindings_are_rejected(self):
        source=generate_extraction_models_code(ExtractionSchema.model_validate(raw_schema()))
        target_line=next(line for line in source.splitlines() if line.startswith('    targets:'))
        variants=[source.replace(target_line,''),source.replace('targets: list[TargetEntity]','targets: list[NumericItemEntity]'),source+'\n    ignored: str = "ignored"\n',source.replace('_node_label: ClassVar[str] = "Target"','_node_label: ClassVar[str] = "NumericItem"')]
        for altered in variants:
            with tempfile.TemporaryDirectory() as directory:
                path=Path(directory)/'schema.py';path.write_text(altered)
                load_extraction_output_model(str(path))
                with self.assertRaises(ValueError):
                    schema_from_pydantic_module(sys.modules['extraction_models'])

    def test_obvious_duplicate_declarations_are_rejected_before_execution(self):
        variants=[
            'class Repeated:\n    pass\nclass Repeated:\n    pass\n',
            'class Fields:\n    name: str\n    name: int\n',
        ]
        for source in variants:
            with tempfile.TemporaryDirectory() as directory:
                path=Path(directory)/'schema.py'
                path.write_text(source+'\nraise RuntimeError("must not execute")\n')
                with self.assertRaisesRegex(ValueError,'Duplicate'):
                    load_extraction_output_model(str(path))

    def test_annotation_then_default_and_inherited_fields_are_supported(self):
        source='''from typing import ClassVar
from pydantic import BaseModel, Field
class Fields(BaseModel):
    name: str
    name = Field(...)
class Item(Fields):
    _node_label: ClassVar[str] = "InheritedItem"
    _key_property: ClassVar[str] = "name"
    name: str = Field(...)
class ExtractionOutput(BaseModel):
    items: list[Item] = Field(default_factory=list)
'''
        directory, output, schema=load_source(source)
        try:
            parsed=parse_extraction_response('{"items":[{"name":"KeepCase"}]}',schema,'source',output)
            self.assertEqual('KeepCase',parsed.entities[0].properties['name'])
        finally:directory.cleanup()

    def test_native_invalid_validator_returns_are_not_json_coerced_or_erased(self):
        raw=raw_schema()
        raw['entity_types'][1]['properties'].append({'name':'score','type':'FLOAT'})
        source=generate_extraction_models_code(ExtractionSchema.model_validate(raw))
        temporal=source.replace('from __future__ import annotations','from __future__ import annotations\nfrom datetime import date',1).replace('    name: str = Field(','''    @field_validator("name", mode="after")
    @classmethod
    def invalid_temporal(cls, value):
        return date(2026, 1, 1)

    name: str = Field(''',1)
        nonfinite=source.replace('    score: Optional[float] = Field(','''    @field_validator("score", mode="after")
    @classmethod
    def invalid_number(cls, value):
        return float("nan")

    score: Optional[float] = Field(''',1)
        for altered, payload, message in [(temporal,'{"targets":[{"name":"X"}]}','expected finite STRING'),(nonfinite,'{"targets":[{"name":"X","score":1.0}]}','expected finite FLOAT')]:
            directory, output, schema=load_source(altered)
            try:
                result=parse_extraction_response(payload,schema,'source',output)
                self.assertEqual('failed',result.outcome.value)
                self.assertIn(message,result.error)
            finally:directory.cleanup()

    def test_enum_storage_is_deliberately_unwrapped_to_native_scalar(self):
        source=generate_extraction_models_code(ExtractionSchema.model_validate(raw_schema()))
        source=source.replace('from pydantic import','from enum import Enum\nclass NameValue(str, Enum):\n    X = "CaseSensitive"\n\nfrom pydantic import',1).replace('    name: str = Field(...','    name: NameValue = Field(...').replace('    target_name: str = Field(...','    target_name: NameValue = Field(...')
        directory, output, schema=load_source(source)
        try:
            result=parse_extraction_response('{"numeric_items":[{"number":0}],"targets":[{"name":"CaseSensitive"}],"links_to":[{"numeric_item_number":0,"target_name":"CaseSensitive"}]}',schema,'source',output)
            self.assertEqual('success',result.outcome.value)
            self.assertIs(type(result.entities[1].properties['name']),str)
            self.assertEqual('CaseSensitive',result.relationships[0].target_key)
        finally:directory.cleanup()
