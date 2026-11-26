"""The LEX-004 oracle distinguishes extra headings from broken nesting."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from tests.synthetic.docling_quality import compare, expected_hierarchy, generate, VARIANTS


class DoclingQualityOracleTests(unittest.TestCase):
    def test_repeated_titles_require_the_correct_parent_path(self):
        expected = expected_hierarchy()
        actual = deepcopy(expected)
        actual[5]['path'] = ['Operations', 'Details']
        result = compare(expected, actual)
        self.assertEqual([], result['missing_headings'])
        self.assertEqual([], result['extra_headings'])
        self.assertFalse(result['all_intended_levels_and_parents_match'])
        self.assertFalse(result['strict_match'])

    def test_extra_source_label_is_not_a_missing_intended_heading(self):
        expected = expected_hierarchy()
        actual = deepcopy(expected)
        actual.insert(3, dict(title='Operator checklist:', level=4,
                              path=['Operations', 'Details', 'Operator checklist:']))
        result = compare(expected, actual)
        self.assertEqual(['Operator checklist:'], result['extra_headings'])
        self.assertTrue(result['all_intended_levels_and_parents_match'])
        self.assertFalse(result['strict_match'])

    def test_missing_repeated_title_is_detected(self):
        expected = expected_hierarchy()
        result = compare(expected, expected[:5] + expected[6:])
        self.assertEqual(['Details'], result['missing_headings'])
        self.assertFalse(result['strict_match'])

    def test_variants_are_deterministic_and_have_native_outlines(self):
        with tempfile.TemporaryDirectory() as tmp:
            first, second = Path(tmp)/'first', Path(tmp)/'second'
            self.assertEqual(generate(first), generate(second))
            for name in VARIANTS:
                data = (first/(name+'.pdf')).read_bytes()
                self.assertEqual(data, (second/(name+'.pdf')).read_bytes())
                self.assertIn(b'/Outlines', data)
            self.assertNotEqual((first/'clear_headings.pdf').read_bytes(),
                                (first/'ambiguous_labels.pdf').read_bytes())


if __name__ == '__main__':
    unittest.main()
