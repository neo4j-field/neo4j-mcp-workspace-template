"""Fixture renderings preserve the intended content and binary reproducibility."""
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
from zipfile import ZipFile

from tests.synthetic.canonical import build_dataset
from tests.synthetic.renderers import render_documents


class SyntheticRendererTests(unittest.TestCase):
    def test_smoke_formats_native_structure_and_aliases(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = build_dataset('smoke')
            result = render_documents(dataset, root)
            self.assertEqual(4, result['pdf_page_count'])
            self.assertEqual({1, 2, 3}, {entry['level'] for entry in result['pdf_outline']})
            self.assertIn(b'/Outlines', (root/'pdf/maintenance.pdf').read_bytes())
            self.assertIn('native outline', result['capabilities']['pdf']['toc'])
            self.assertIn('no native TOC', result['capabilities']['docx']['toc'])
            self.assertEqual(set(s['id'] for s in dataset['sections']), set(result['pdf_section_pages']))
            self.assertEqual((root/'documents/maintenance.md').read_bytes(), (root/'aliases/maintenance.markdown').read_bytes())
            self.assertEqual((root/'documents/maintenance.txt').read_bytes(), (root/'aliases/maintenance.text').read_bytes())
            xhtml = ET.parse(root/'aliases/maintenance.xhtml')
            self.assertEqual('{http://www.w3.org/1999/xhtml}html', xhtml.getroot().tag)
            self.assertEqual(2, len(xhtml.findall('.//{http://www.w3.org/1999/xhtml}table')))
            for name in ['documents/maintenance.md', 'documents/maintenance.txt', 'documents/maintenance.html']:
                source = (root/name).read_text()
                self.assertIn('Café', source)
                self.assertIn('≤ 2.5', source)
                self.assertNotIn('BYP-42', source)
                self.assertIn('REF-16', source)
            with ZipFile(root/'documents/maintenance.docx') as archive:
                xml = archive.read('word/document.xml').decode()
                self.assertIn('Heading3', xml)
                self.assertIn('<w:tbl>', xml)
                self.assertIn('Café', xml)
                self.assertIn('word/media/image1.png', archive.namelist())
                self.assertTrue(all(info.date_time == (2000, 1, 1, 0, 0, 0) for info in archive.infolist()))
            self.assertFalse(result['capabilities']['text']['headings'])
            self.assertFalse(result['capabilities']['docx']['pages'])

    def test_binary_determinism_and_fifty_page_benchmark(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp)/'a', Path(tmp)/'b'
            dataset = build_dataset('benchmark')
            first, second = render_documents(dataset, a), render_documents(dataset, b)
            self.assertEqual(first, second)
            self.assertEqual(50, first['pdf_page_count'])
            self.assertGreaterEqual(first['text_metrics']['source']['words'], 14000)
            density = first['text_metrics']['pdf']
            self.assertEqual(50, len(density['pages']))
            self.assertGreater(density['median_words_per_page'], 300)
            self.assertGreater(density['max_words_per_page'], density['min_words_per_page'])
            for path in a.rglob('*'):
                if path.is_file():
                    self.assertEqual(path.read_bytes(), (b/path.relative_to(a)).read_bytes(), str(path.relative_to(a)))
            self.assertIn(b'/Count 50', (a/'pdf/maintenance.pdf').read_bytes())

    def test_pdf_refuses_unsupported_glyphs_instead_of_silent_corruption(self):
        dataset = build_dataset('smoke')
        dataset['sections'][0]['paragraphs'].append('Unsupported fixture glyph: 東京')
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, 'unsupported by embedded PDF font'):
                render_documents(dataset, Path(tmp))
