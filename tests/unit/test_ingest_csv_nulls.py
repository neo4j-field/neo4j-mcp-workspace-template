"""Blank CSV values must not leak pandas NaN into typed graph properties."""
from pathlib import Path
import tempfile
import unittest
from mcp_neo4j_ingest.csv_records import read_csv_records


class CsvNullTests(unittest.TestCase):
    def test_missing_strings_numbers_and_booleans_are_native_null(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'missing.csv'
            path.write_text('code,note,amount,enabled\nCV-7,"Café, verified",7.25,true\ncv-7,,,\n',encoding='utf-8')
            rows=read_csv_records(path)
        self.assertEqual(['CV-7','cv-7'],[r['code'] for r in rows])
        self.assertEqual('Café, verified',rows[0]['note'])
        self.assertEqual(7.25,rows[0]['amount'])
        self.assertTrue(rows[0]['enabled'])
        for column in ['note','amount','enabled']:
            self.assertIsNone(rows[1][column])
