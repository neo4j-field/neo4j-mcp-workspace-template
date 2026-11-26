"""Fixture truth is deterministic and independently checkable before using an LLM."""
import csv
import json
from pathlib import Path
import tempfile
import unittest

from tests.synthetic.canonical import build_dataset, expected_results, write_csvs, write_expected


class CanonicalDatasetTests(unittest.TestCase):
    def test_profiles_are_deterministic_with_explicit_benchmark_row_budget(self):
        for profile,count,facilities,procedures in [('smoke',8,2,2),('benchmark',10000,20,80)]:
            dataset = build_dataset(profile)
            self.assertEqual(dataset,build_dataset(profile))
            expected = expected_results(dataset)
            self.assertEqual(count,len(dataset['products']))
            self.assertEqual(facilities,len(dataset['facilities']))
            self.assertEqual(procedures,len(dataset['procedures']))
            self.assertEqual(count+facilities+procedures+2,expected['csv']['total_data_rows'])
        with self.assertRaises(ValueError):
            build_dataset('production')

    def test_all_endpoints_exist_and_case_sensitive_sensor_keys_stay_distinct(self):
        dataset = build_dataset('benchmark')
        facilities = {r['name'] for r in dataset['facilities']}
        procedures = {r['name']:r for r in dataset['procedures']}
        self.assertEqual(2,len({s['code'] for s in dataset['sensors']}))
        for product in dataset['products']:
            self.assertIn(product['facility_name'],facilities)
            self.assertIn(product['procedure_name'],procedures)
            self.assertEqual(product['facility_name'],procedures[product['procedure_name']]['facility_name'])
        self.assertEqual(10000,len({p['name'] for p in dataset['products']}))
        words=sum(len(p.split()) for s in dataset['sections'] for p in s['paragraphs'])
        self.assertGreaterEqual(words,14000)
        zero_facilities=[name for name,count in next(q for q in dataset['questions'] if q['id']=='q-count')['answer'].items() if count==0]
        self.assertEqual(5,len(zero_facilities))
        expected = expected_results(dataset)
        self.assertEqual(20082,expected['structured_graph']['relationship_total'])
        self.assertEqual(0,expected['structured_graph']['orphans'])

    def test_csv_roundtrip_types_nulls_quotes_and_unicode(self):
        dataset = build_dataset()
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            manifest = write_csvs(dataset,output)
            expected = write_expected(dataset,output)
            self.assertEqual(4,len(manifest))
            with (output/'csv/products.csv').open(encoding='utf-8',newline='') as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(dataset['products'][0]['notes'],rows[0]['notes'])
            self.assertEqual('',rows[3]['notes'])
            self.assertEqual('true',rows[0]['active'])
            self.assertEqual('false',rows[3]['active'])
            self.assertEqual('0.1',rows[0]['allocation'])
            self.assertEqual(expected,json.loads((output/'expected.json').read_text()))
            self.assertEqual(dataset,json.loads((output/'source.json').read_text()))
            self.assertTrue((output/'variants/ontology_alias.md').is_file())
            self.assertIn('North Works',(output/'variants/ontology_alias.md').read_text())
            self.assertNotIn('Unknown Facility','\n'.join(p for s in dataset['sections'] for p in s['paragraphs']))

    def test_ground_truth_distinguishes_conflict_visual_only_and_nested_sources(self):
        dataset = build_dataset()
        expected = expected_results(dataset)
        self.assertNotEqual(expected['bridge']['existing_action'],expected['bridge']['proposed_action'])
        text='\n'.join(p for s in dataset['sections'] for p in s['paragraphs'])
        self.assertIn('CV-7',text)
        self.assertNotIn(dataset['visual']['bypass_code'],text)
        details=[s for s in dataset['sections'] if s['title']=='Details']
        self.assertEqual(2,len(details))
        self.assertEqual(3,max(s['level'] for s in dataset['sections']))
        self.assertGreater(sum(len(p) for p in next(s for s in dataset['sections'] if s['id']=='long-reference')['paragraphs']),4000)
        by_id={q['id']:q for q in dataset['questions']}
        self.assertEqual({'fixture facility 01':4,'fixture facility 02':2},by_id['q-count']['answer'])
        self.assertIn('requires',by_id['q-image'])
