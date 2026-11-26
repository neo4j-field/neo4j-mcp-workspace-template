"""Deterministic, redistributable maintenance facts and source truth.

No timestamps, randomness, provider calls or database access. Documents are
alternate renderings of the same evidence, never additive domain records.
"""
from __future__ import annotations

import csv
from pathlib import Path
import json
from typing import Any

FORMAT_VERSION = 1
CSV_ACTION = 'pause the line for 12 minutes and inspect coolant valve cv-7'
DOCUMENT_ACTION = 'Pause the line for 12 minutes and inspect coolant valve CV-7 before resuming production.'
RELATIONSHIPS = {
    'FIXTURE_MADE_AT': ('FixtureProduct', 'FixtureFacility'),
    'FIXTURE_USES_PROCEDURE': ('FixtureProduct', 'FixtureProcedure'),
    'FIXTURE_OWNED_BY': ('FixtureProcedure', 'FixtureFacility'),
    'FIXTURE_SENSOR_AT': ('FixtureSensor', 'FixtureFacility'),
}


def build_dataset(profile: str = 'smoke') -> dict[str, Any]:
    if profile not in {'smoke', 'benchmark'}:
        raise ValueError('profile must be smoke or benchmark')
    facility_count, procedure_count, product_count = (2, 2, 8) if profile == 'smoke' else (20, 80, 10000)
    facilities = [dict(name=f'fixture facility {i + 1:02d}', region=['north', 'south'][i % 2],
                       capacity=120 + i * 10, active=i % 3 != 2)
                  for i in range(facility_count)]
    procedures = [dict(name=f'fixture thermal reset {i + 1:02d}', facility_name=facilities[i % facility_count]['name'],
                       action=CSV_ACTION if i == 0 else f'wait {12 + i} minutes and inspect fixture valve {i + 1:02d}',
                       duration_minutes=12 + i, approved=True)
                  for i in range(procedure_count)]
    products = []
    for i in range(product_count):
        procedure = procedures[i % procedure_count]
        products.append(dict(name=f'fixture pump {i + 1:05d}', product_code=f'FP-{i + 1:05d}',
                             facility_name=procedure['facility_name'], procedure_name=procedure['name'],
                             priority=i % 3 + 1, active=i % 4 != 3,
                             commissioned=f'2026-{i % 12 + 1:02d}-{i % 28 + 1:02d}',
                             notes=('Café maintenance, "verified"; pressure drop ≤ 2.5' if i == 0 else None if i % 3 == 0 else f'synthetic lot {i % 7}'),
                             allocation=round((i % 9 + 1) / 10, 1)))
    sensors = [dict(code='CV-7', facility_name=facilities[0]['name'], reading=7.25, calibrated=True),
               dict(code='cv-7', facility_name=facilities[1]['name'], reading=2.5, calibrated=False)]
    sections = _sections(profile, products, procedures)
    questions = [
        dict(id='q-bridge', question='Where is Fixture Pump 00001 made, and which procedure does it use?',
             answer={'product':'fixture pump 00001', 'facility':'fixture facility 01', 'procedure':'fixture thermal reset 01'},
             sources=['operations-details'], mode='CHATBOT'),
        dict(id='q-action', question='How long must the line pause for Fixture Thermal Reset 01, and which valve is inspected?',
             answer={'duration_minutes':12, 'valve':'CV-7'}, sources=['thermal-reset'], mode='CHATBOT'),
        dict(id='q-conflict', question='After preserve-existing extraction, what is the stored reset action and what did the document propose?',
             answer={'stored_action':CSV_ACTION, 'proposed_action':DOCUMENT_ACTION}, sources=['thermal-reset'], mode='CHATBOT'),
        dict(id='q-case', question='Are sensor codes CV-7 and cv-7 the same sensor, and what are their readings?',
             answer={'distinct_sensors':2, 'readings':{'CV-7':7.25, 'cv-7':2.5}}, sources=['diagnostics'], mode='CHATBOT'),
        dict(id='q-unicode', question='Which multilingual maintenance note is attached to the first pump?',
             answer={'notes':products[0]['notes']}, sources=['operations-details'], mode='CHATBOT'),
        dict(id='q-count', question='How many active products are assigned to each facility?',
             answer={f['name']:sum(1 for p in products if p['active'] and p['facility_name']==f['name']) for f in facilities},
             sources=['csv/products.csv'], mode='ANALYTICAL'),
        dict(id='q-image', question='What is the emergency bypass code shown only in the diagnostic diagram?',
             answer={'bypass_code':'BYP-42'}, sources=['assets/route.png'], mode='CHATBOT',
             requires='vision/image reading; deliberately absent from document textual body'),
    ]
    return dict(format_version=FORMAT_VERSION, profile=profile, title='Aster Works Synthetic Maintenance Handbook',
                license='CC0-1.0', facilities=facilities, procedures=procedures, products=products,
                sensors=sensors, sections=sections, questions=questions,
                normalization={'FixtureFacility.name':['strip','lowercase'],
                               'FixtureProcedure.name':['strip','lowercase'],
                               'FixtureProduct.name':['strip','lowercase'], 'FixtureSensor.code':['strip']},
                alias_maps={'FixtureFacilityAliases':{'north works':'fixture facility 01'}},
                blocklists={'FixtureBlockedNames':['unknown facility']},
                ontology_variants={
                    'alias': {
                        'path':'variants/ontology_alias.md',
                        'text':'# Alias normalization fixture\n\nFixture Pump 00001 is made at North Works. North Works is an alias for Fixture Facility 01.\n',
                        'expected':{'raw_facility':'North Works','normalized_facility':'fixture facility 01',
                                    'additional_facility_nodes':0}},
                    'blocklist': {
                        'path':'variants/ontology_blocklist.md',
                        'text':'# Blocklist fixture\n\nThe facility name on this intentionally incomplete maintenance record is Unknown Facility. Its identity has not been established.\n',
                        'expected':{'raw_facility':'Unknown Facility','blocked_normalized_name':'unknown facility',
                                    'persisted_blocklisted_nodes':0}},
                },
                visual={'diagram_title':'Synthetic diagnostic routing', 'bypass_code':'BYP-42',
                        'caption':'Figure 1. Diagnostic routing; read the image for the emergency bypass code.'})


def _sections(profile, products, procedures):
    sections = [
        dict(id='overview', level=1, title='Overview', paragraphs=[
            'This synthetic Aster Works handbook is a redistributable acceptance fixture. All people, places, products and operational values are fictional.',
            'Contents: Operations; Operations / Details; Operations / Thermal reset; Maintenance / Details; Diagnostics; Long reference.']),
        dict(id='operations', level=1, title='Operations', paragraphs=['The same facts appear in alternate file formats. Ingest one rendering for the baseline; test equivalence with separate document identities or a disposable database.']),
        dict(id='operations-details', level=2, title='Details', paragraphs=[
            'Fixture Pump 00001 is made at Fixture Facility 01 and uses Fixture Thermal Reset 01. Fixture Thermal Reset 01 is owned by Fixture Facility 01.',
            f'The product identifier is {products[0]["product_code"]}. Its priority is 1, active is true, commissioning date is 2026-01-01 and allocation is 0.1.',
            'The maintenance note reads: Café maintenance, "verified"; pressure drop ≤ 2.5. Preserve Unicode and punctuation exactly.',
            'Operator checklist:', '- Isolate the line.', '- Inspect the coolant valve.', '- Record the reading before restart.'],
             table=dict(headers=['Product','Facility','Procedure','Priority'], rows=[
                 [p['name'],p['facility_name'],p['procedure_name'],str(p['priority'])] for p in products[:4]])),
        dict(id='thermal-reset', level=3, title='Thermal reset', paragraphs=[
            f'Fixture Thermal Reset 01: {DOCUMENT_ACTION}',
            'The authoritative CSV action is deliberately shorter. During document extraction preserve the existing CSV action and record the proposed document wording and action conflict on provenance.',
            'The procedure duration is 12 minutes. This is the coolant intervention, not the unrelated calibration wait.']),
        dict(id='maintenance', level=1, title='Maintenance', paragraphs=['Maintenance and Operations both contain a subsection titled Details. Retrieval must preserve their different heading paths.']),
        dict(id='maintenance-details', level=2, title='Details', paragraphs=[
            'The unrelated calibration wait is 27 minutes. It must not be returned as the thermal reset duration.',
            f'Fixture Pump 00002 is made at Fixture Facility 02 and uses {procedures[1]["name"].title()}.']),
        dict(id='diagnostics', level=1, title='Diagnostics', paragraphs=[
            'CV-7 and cv-7 are two distinct, case-sensitive sensor codes. CV-7 is at Fixture Facility 01, reads 7.25 and is calibrated. cv-7 is at Fixture Facility 02, reads 2.5 and is not calibrated.',
            'Figure 1. Diagnostic routing; read the image for the emergency bypass code. The code is intentionally not transcribed in document text.'],
             table=dict(headers=['Sensor','Reading','Calibrated'],rows=[['CV-7','7.25','true'],['cv-7','2.5','false']])),
        dict(id='long-reference', level=1, title='Long reference', paragraphs=[
            f'Reference block {i:02d}. For Fixture Pump 00001, retain the Operations / Details heading path. '
            'Confirm the coolant inspection context before answering. This deterministic paragraph exercises token windows, source order and resumable long-section reading. '
            'The continuation marker for this block is REF-'+f'{i:02d}.' for i in range(1,17)]),
    ]
    if profile == 'benchmark':
        for i in range(1,46):
            product = products[i]
            sections.append(dict(id=f'case-{i:02d}', level=1 if i % 5 == 1 else 2,
                                 title=f'Operational case {i:02d}', paragraphs=[
                                     f'{product["name"].title()} is made at {product["facility_name"].title()} and uses {product["procedure_name"].title()}. '
                                     f'Its identifier is {product["product_code"]}, priority {product["priority"]}, active {str(product["active"]).lower()}, '
                                     f'commissioning date {product["commissioned"]} and allocation {product["allocation"]}.',
                                     f'Case marker CASE-{i:02d} identifies this source section. Answer with this product and procedure rather than neighboring cases. '
                                     'This is fictional maintenance reference material. Read the applicable section and retain its source citation.',
                                     *_case_observations(i,product,procedures[i % len(procedures)])]))
    return sections


def _case_observations(index, product, procedure):
    """Distinct operational evidence with explicit product scope, not filler text."""
    pressure = round(1.2 + (index % 9) * 0.1, 1)
    low_temperature = 18 + index % 5
    high_temperature = low_temperature + 6
    revision = f'2026-{index % 12 + 1:02d}-{index % 28 + 1:02d}'
    case = f'CASE-{index:02d}'
    name = product['name'].title()
    duration = procedure['duration_minutes']
    return [
        f'Inspection envelope {case}: the nominal test pressure for {name} is {pressure:.1f} bar, with a permitted deviation of 0.10 bar in either direction. '
        f'The coolant inlet temperature must remain between {low_temperature} and {high_temperature} degrees Celsius. These limits belong only to this product and case; they are synthetic acceptance values rather than general equipment advice.',
        f'Before inspecting {name}, confirm identifier {product["product_code"]} and record the isolation time. '
        'Close the local supply and observe pressure for sixty seconds. A drifting reading stops this case; record the deviation before proceeding.',
        f'The assigned procedure remains {procedure["name"].title()}, whose baseline duration is {duration} minutes. '
        'Start that timer after isolation has been recorded, rather than when the work record was opened. '
        'Inspect the visible coolant connection for leakage and the fastener witness marks for movement. '
        'This case does not reassign the product to another facility or replace its structured procedure.',
        f'The observation record for {case} was revised on {revision}. Record the measured pressure, inlet temperature and elapsed isolation time alongside that revision date. '
        'Use an explicit unavailable marker when a reading cannot be taken; an unavailable reading is not zero. '
        'Retain the original observation separately from any later correction so that an analytical question can distinguish missing evidence from a passing inspection.',
        f'Restart verification for {name} requires two consecutive readings inside the permitted pressure and temperature limits. '
        'Take the second reading thirty seconds after the first, then inspect the connection once more while the line is running. '
        'If either reading is outside the envelope, retain the failed observation and repeat the assigned procedure after recording a new isolation time. Do not silently replace the failed reading.',
        f'The structured priority for {name} is {product["priority"]}, its allocation is {product["allocation"]}, and its active flag is {str(product["active"]).lower()}. '
        'An inactive product remains part of the inventory and keeps its facility and procedure relationships. '
        'Exclude it only from questions explicitly restricted to active products; a general inventory count must include both active and inactive records.',
        f'To close {case}, verify that the work record names {product["facility_name"].title()} and includes the inspection revision, two restart readings and the operator checklist result. '
        'The commissioning date identifies when this fictional product entered service; it must not be substituted for the inspection revision date. '
        'A missing checklist result leaves this case incomplete even when both recorded readings are within the numerical limits.',
    ]


def _write_json(path, value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')


def write_csvs(dataset: dict[str, Any], output: Path) -> dict[str, Any]:
    directory = Path(output) / 'csv'
    directory.mkdir(parents=True,exist_ok=True)
    files = {}
    for kind in ['facilities','procedures','products','sensors']:
        path = directory / f'{kind}.csv'
        rows = dataset[kind]
        with path.open('w',encoding='utf-8',newline='') as stream:
            writer = csv.DictWriter(stream,fieldnames=list(rows[0]),lineterminator='\n')
            writer.writeheader()
            writer.writerows({key: str(value).lower() if isinstance(value,bool) else value
                              for key,value in row.items()} for row in rows)
        files[f'csv/{kind}.csv'] = {'rows':len(rows),'columns':list(rows[0]),'encoding':'utf-8'}
    return files


def expected_results(dataset: dict[str, Any]) -> dict[str, Any]:
    counts = {'FixtureFacility':len(dataset['facilities']), 'FixtureProcedure':len(dataset['procedures']),
              'FixtureProduct':len(dataset['products']), 'FixtureSensor':len(dataset['sensors'])}
    relationships = {'FIXTURE_MADE_AT':len(dataset['products']), 'FIXTURE_USES_PROCEDURE':len(dataset['products']),
                     'FIXTURE_OWNED_BY':len(dataset['procedures']), 'FIXTURE_SENSOR_AT':len(dataset['sensors'])}
    return dict(format_version=FORMAT_VERSION, profile=dataset['profile'],
                structured_graph={'nodes_by_label':counts, 'node_total':sum(counts.values()),
                                  'relationships_by_type':relationships,'relationship_total':sum(relationships.values()),
                                  'orphans':0,'duplicate_keys':0},
                csv={'main_product_rows':len(dataset['products']),
                     'auxiliary_rows':sum(len(dataset[k]) for k in ['facilities','procedures','sensors']),
                     'total_data_rows':sum(counts.values()),'header_rows':4},
                bridge={'key':'fixture thermal reset 01','existing_action':CSV_ACTION,
                        'proposed_action':DOCUMENT_ACTION,'policy':'preserve_existing','conflicting_properties':['action']},
                case_sensitive_keys=['CV-7','cv-7'], questions=dataset['questions'],
                ontology_variants={key:{'path':value['path'],'expected':value['expected']}
                                   for key,value in dataset['ontology_variants'].items()},
                source_sections=[{'id':s['id'],'level':s['level'],'title':s['title']} for s in dataset['sections']],
                validation_status='expected truth only; actual parser/provider/database acceptance is recorded separately')


def write_expected(dataset: dict[str, Any], output: Path) -> dict[str, Any]:
    output = Path(output)
    output.mkdir(parents=True,exist_ok=True)
    expected = expected_results(dataset)
    _write_json(output / 'expected.json',expected)
    _write_json(output / 'source.json',dataset)
    for variant in dataset['ontology_variants'].values():
        path=output / variant['path']
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(variant['text'],encoding='utf-8')
    return expected
