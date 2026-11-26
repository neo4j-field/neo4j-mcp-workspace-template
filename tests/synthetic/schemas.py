"""Portable synthetic schema artifacts; generation itself needs only stdlib + YAML."""
from __future__ import annotations

import copy
import json
from pathlib import Path

SCHEMA_URI = 'https://neo4j.com/docs/ontology-graph-spec/1.1.0/schema.json'
EXTENSION = 'neo4j-mcp-workspace-template'
KEY_NORMALIZATION = {'FixtureFacility':'strip_lower','FixtureProcedure':'strip_lower','FixtureProduct':'strip_lower','FixtureSensor':'strip'}


def _prop(name, type='STRING', column=None):
    return {'name':name,'type':type,'source':{'column_name':column or name}}


def data_model():
    nodes = [
        {'label':'FixtureFacility','description':'Synthetic maintenance facility','key_property':_prop('name'),
         'properties':[_prop('region'),_prop('capacity','INTEGER'),_prop('active','BOOLEAN')]},
        {'label':'FixtureProcedure','description':'A named synthetic maintenance procedure','key_property':_prop('name'),
         'properties':[_prop('action'),_prop('duration_minutes','INTEGER'),_prop('approved','BOOLEAN')]},
        {'label':'FixtureProduct','description':'A named synthetic pump product','key_property':_prop('name'),
         'properties':[_prop('productCode',column='product_code'),_prop('priority','INTEGER'),_prop('active','BOOLEAN'),_prop('commissioned','DATE'),_prop('notes'),_prop('allocation','FLOAT')]},
        {'label':'FixtureSensor','description':'A case-sensitive sensor code; CV-7 and cv-7 are different sensors','key_property':_prop('code'),
         'properties':[_prop('reading','FLOAT'),_prop('calibrated','BOOLEAN')]},
    ]
    relationships = [
        {'type':'FIXTURE_MADE_AT','start_node_label':'FixtureProduct','end_node_label':'FixtureFacility','properties':[_prop('allocation','FLOAT')]},
        {'type':'FIXTURE_USES_PROCEDURE','start_node_label':'FixtureProduct','end_node_label':'FixtureProcedure','properties':[_prop('priority','INTEGER')]},
        {'type':'FIXTURE_OWNED_BY','start_node_label':'FixtureProcedure','end_node_label':'FixtureFacility','properties':[]},
        {'type':'FIXTURE_SENSOR_AT','start_node_label':'FixtureSensor','end_node_label':'FixtureFacility','properties':[]},
    ]
    return {'nodes':nodes,'relationships':relationships}


def extraction_data_model():
    """Extraction is scalar-only; DATE remains exclusively structured CSV data."""
    model = data_model()
    for node in model['nodes']:
        node['properties'] = [p for p in node['properties'] if p['name'] != 'commissioned']
    return model


def ingest_plan():
    """Each relationship has its own endpoint column mapping for its source CSV."""
    model = data_model()
    node_files = {'FixtureFacility':'facilities.csv','FixtureProcedure':'procedures.csv','FixtureProduct':'products.csv','FixtureSensor':'sensors.csv'}
    nodes = [{'csv':'csv/'+node_files[n['label']], 'node':n} for n in model['nodes']]
    relationships = []
    for relation in model['relationships']:
        endpoint_model = copy.deepcopy(model)
        for node in endpoint_model['nodes']:
            if node['label'] == relation['end_node_label']:
                node['key_property']['source']['column_name'] = 'facility_name' if node['label']=='FixtureFacility' else 'procedure_name'
        relationships.append({'csv':'csv/'+node_files[relation['start_node_label']], 'relationship':relation,'endpoint_data_model':endpoint_model})
    return {'nodes':nodes,'relationships':relationships,'missing_values':'CSV blank optional cells represent canonical missing values. The public ingest path must normalize pandas missing sentinels to None; assert notes is absent/null rather than storing float NaN. Raw csv.DictReader alone yields empty strings and is not proof of public ingestion semantics.'}


def ontology_spec():
    model = extraction_data_model()
    nodes = {}
    labels = {}
    for node in model['nodes']:
        label=node['label']; labels[label]=label
        key=node['key_property']['name']
        properties={}
        for prop in [node['key_property'],*node['properties']]:
            value={'type':prop['type']}
            if prop['name']==key:
                value['key']=True
                if key=='name':
                    config={'normalizers':['whitespace','lowercase','blocklist'], 'blocklist_name':'FixtureBlockedNames'}
                    if label=='FixtureFacility':
                        config['normalizers'].insert(2,'alias_map')
                        config['alias_map_name']='FixtureFacilityAliases'
                    value['extensions']={'custom':{EXTENSION:config}}
                else:
                    value['extensions']={'custom':{EXTENSION:{'normalizers':['whitespace']}}}
            properties[prop['name']]=value
        nodes[label]={'label':label,'description':node['description'],'properties':properties}
    relationships={r['type']:{'type':r['type'],'description':'Synthetic '+r['type'].lower().replace('_',' '),'from':{'node':r['start_node_label']},'to':{'node':r['end_node_label']},'properties':{p['name']:{'type':p['type']} for p in r['properties']}} for r in model['relationships']}
    return {'schema':SCHEMA_URI,'version':'synthetic-1','id':'synthetic-maintenance', 'name':'Synthetic maintenance acceptance ontology',
            'description':'Synthetic fixture semantics; dates remain in the structured ingest model.', 'nodes':nodes,'relationships':relationships,
            'extensions':{'custom':{EXTENSION:{'alias_maps':{'FixtureFacilityAliases':{'north works':'fixture facility 01','north lab':'fixture facility 01'}},'blocklists':{'FixtureBlockedNames':['unknown facility','unknown','not a real facility']}}}}}


def extraction_source():
    """Standalone file route shares normalization, but aliases live in ontology route."""
    model=extraction_data_model()
    lines=['"""Synthetic Pydantic extraction schema. Generated; no provider/graph side effects."""',
           'from typing import ClassVar, Optional','from pydantic import BaseModel, Field, field_validator','']
    types={'STRING':'str','INTEGER':'int','FLOAT':'float','BOOLEAN':'bool'}
    key_info={n['label']:n['key_property']['name'] for n in model['nodes']}
    collections=[]
    for node in model['nodes']:
        label=node['label']; key=key_info[label]; name=label+'Entity'
        collections.append((label.lower()+'s',name))
        lines.extend([f'class {name}(BaseModel):',f'    _node_label: ClassVar[str] = {label!r}',f'    _key_property: ClassVar[str] = {key!r}',f'    {key}: str = Field(..., description={node["description"]!r})'])
        for prop in node['properties']:
            lines.append(f'    {prop["name"]}: Optional[{types[prop["type"]]}] = None')
        expression='value.strip().lower()' if key=='name' else 'value.strip()'
        lines.extend([f'    @field_validator({key!r})','    @classmethod','    def normalize_key(cls, value: str) -> str:',f'        return {expression}',''])
    for relation in model['relationships']:
        start=relation['start_node_label'];end=relation['end_node_label'];rtype=relation['type'];name=''.join(p.title() for p in rtype.split('_'))+'Rel'
        collections.append((rtype.lower(),name))
        start_field=start.lower()+'_'+key_info[start];end_field=end.lower()+'_'+key_info[end]
        lines.extend([f'class {name}(BaseModel):',f'    _relationship_type: ClassVar[str] = {rtype!r}',f'    _start_node_label: ClassVar[str] = {start!r}',f'    _end_node_label: ClassVar[str] = {end!r}',f'    _start_key_property: ClassVar[str] = {key_info[start]!r}',f'    _end_key_property: ClassVar[str] = {key_info[end]!r}',f'    {start_field}: str',f'    {end_field}: str'])
        for prop in relation['properties']:
            lines.append(f'    {prop["name"]}: Optional[{types[prop["type"]]}] = None')
        for field,label in [(start_field,start),(end_field,end)]:
            expression='value.strip().lower()' if key_info[label]=='name' else 'value.strip()'
            lines.extend([f'    @field_validator({field!r})','    @classmethod',f'    def normalize_{field}(cls, value: str) -> str:',f'        return {expression}'])
        lines.append('')
    lines.append('class ExtractionOutput(BaseModel):')
    lines.extend(f'    {field}: list[{name}] = Field(default_factory=list)' for field,name in collections)
    return '\n'.join(lines)+'\n'


def _json(path, content):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(content,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')


def write_schemas(dataset, output: Path):
    """Write positive schemas, separate negative cases and lifecycle source variants."""
    import yaml
    output=Path(output);directory=output/'schemas';directory.mkdir(parents=True,exist_ok=True)
    for name,content in [('data_model.json',data_model()),('extraction_data_model.json',extraction_data_model()),('ingest_plan.json',ingest_plan()),('key_normalization.json',KEY_NORMALIZATION),('ontology.json',ontology_spec())]:
        _json(directory/name,content)
    (directory/'ontology.yaml').write_text(yaml.safe_dump(ontology_spec(),sort_keys=False,allow_unicode=True),encoding='utf-8')
    (directory/'extraction_schema.py').write_text(extraction_source(),encoding='utf-8')
    negative=output/'negative';negative.mkdir(exist_ok=True)
    bad=ontology_spec();bad['relationships']['FIXTURE_MADE_AT']['to']['node']='MissingNode'
    _json(negative/'invalid_ontology.json',bad)
    _json(negative/'reserved_metadata.json',{'sourceId':'attempted override','ordinary_metadata':'must fail before writes'})
    (negative/'invalid_utf8.txt').write_bytes(b'valid prefix\n\xff\xfe invalid utf8')
    (negative/'unsupported.xyz').write_text('Unsupported fixture, kept outside default ingestion.',encoding='utf-8')
    (negative/'blocked_aliases.md').write_text('# Rejected identities\nThe words unknown and not a real facility are placeholders, not facilities.\n',encoding='utf-8')
    _json(negative/'failure_cases.json',{'cases':[
        {'id':'invalid-ontology','artifact':'invalid_ontology.json','expected':'validation error before provider/database writes'},
        {'id':'reserved-metadata','artifact':'reserved_metadata.json','expected':'metadata validation error before parsing/writes'},
        {'id':'invalid-encoding','artifact':'invalid_utf8.txt','expected':'actionable UTF-8 error'},
        {'id':'unsupported-file','artifact':'unsupported.xyz','expected':'explicit single-file call rejected; folder discovery ignores unsupported suffix'},
        {'id':'blocked-identities','artifact':'blocked_aliases.md','expected':'ontology normalizer rejects these keys; semantic extraction is not assumed deterministic'},
        {'id':'index-conflict','artifact':None,'expected':'harness creates incompatible temporary fulltext index; no provider call'},
        {'id':'failed-write','artifact':None,'expected':'harness injects data transaction failure; previous active version remains'},
        {'id':'provider-failure','artifact':None,'expected':'harness injects provider error; job reports failure, no false complete'},
    ]})
    lifecycle=output/'lifecycle';lifecycle.mkdir(exist_ok=True)
    first=(dataset.get('products') or [{'name':'fixture pump 00001'}])[0]['name']
    action='Pause the line for 12 minutes and inspect coolant valve CV-7 before resuming production.'
    for version,body in [('v1',f'{first} uses fixture thermal reset 01. {action}'),('v2',f'In this document-only revision, {first} uses fixture thermal reset 02. Fixture thermal reset 02 has a duration of 18 minutes; fixture thermal reset 01 is no longer assigned to this product. This is a deliberate change from its baseline CSV duration of 13 minutes.')]:
        folder=lifecycle/version;folder.mkdir(exist_ok=True)
        (folder/'maintenance.md').write_text('# Maintenance revision\n\n'+body+'\n',encoding='utf-8')
    _json(lifecycle/'expected.json',{'source_family':'explicitly pass the same document_id for both maintenance.md files','v1':{'product':first,'procedure':'fixture thermal reset 01'},'v2':{'product':first,'procedure':'fixture thermal reset 02','removed_assignment':'fixture thermal reset 01','duration_minutes':18,'baseline_csv_duration_minutes':13,'scope':'document-only revision; mixed preserve_existing keeps CSV duration 13'},'structured_guard':'Do not expect extraction to delete CSV-owned relationships. Use a document-only isolated graph to assert removal; use the mixed graph to assert preservation.','pending_harness':['failed/cancelled write rollback','schema change','embedding input/model identity invalidation','owned replacement','manual activation','scoped delete/rebuild']})
    return {'data_model':'schemas/data_model.json','extraction_data_model':'schemas/extraction_data_model.json','ingest_plan':'schemas/ingest_plan.json','ontology_json':'schemas/ontology.json','ontology_yaml':'schemas/ontology.yaml','extraction_python':'schemas/extraction_schema.py','key_normalization':'schemas/key_normalization.json','negative_cases':'negative/failure_cases.json','lifecycle':'lifecycle/expected.json'}
