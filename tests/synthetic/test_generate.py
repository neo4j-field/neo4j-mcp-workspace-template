"""Generator integrity checks exercise files/ground truth rather than mirror formatting."""
import json
from pathlib import Path
import tempfile
import unittest
from .generate import generate
from .validate import validate


class DatasetGenerationTests(unittest.TestCase):
    def test_smoke_is_reproducible_complete_and_preserves_previous_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            a,b=Path(tmp)/'a',Path(tmp)/'b'
            first=generate('smoke',a);second=generate('smoke',b)
            self.assertEqual(first,second)
            self.assertEqual((a/'manifest.json').read_bytes(),(b/'manifest.json').read_bytes())
            result=validate(a)
            self.assertEqual('passed',result['status'],[x for x in result['checks'] if not x['passed']])
            self.assertEqual(4,first['documents']['pdf_page_count'])
            self.assertTrue((a/'assets/FONT_LICENSE.txt').is_file())
            with self.assertRaisesRegex(ValueError,'not empty'):
                generate('smoke',a)
            path=a/'documents/maintenance.txt'
            path.write_text('corrupted fixture',encoding='utf-8')
            failed=validate(a)
            self.assertEqual('failed',failed['status'])
            self.assertTrue(any(not c['passed'] and c['name']=='hash:documents/maintenance.txt' for c in failed['checks']))

    def test_benchmark_exact_workload_and_explicit_untested_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'benchmark'
            manifest=generate('benchmark',out)
            expected=json.loads((out/'expected.json').read_text())
            self.assertEqual(50,manifest['documents']['pdf_page_count'])
            self.assertEqual(10000,expected['csv']['main_product_rows'])
            self.assertEqual(10102,expected['csv']['total_data_rows'])
            result=validate(out)
            self.assertEqual('passed',result['status'],[x for x in result['checks'] if not x['passed']])
            self.assertIn('manual Claude Code QA',result['not_tested'])
            self.assertIn('live workflow acceptance not implied',manifest['status'])
