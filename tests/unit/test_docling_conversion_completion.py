"""Failed/partial Docling conversion must never become a successful ParsedDocument."""
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from docling.datamodel.base_models import ConversionStatus, DoclingComponentType, ErrorItem, FailureCategory
from docling_core.types.doc import DoclingDocument
from mcp_neo4j_lexical_graph.parsers.conversion_validation import require_complete_conversion
from mcp_neo4j_lexical_graph.parsers.docling_parser import DoclingParser
from mcp_neo4j_lexical_graph.parsers.structured_document import StructuredDocumentParser

PDF=Path(__file__).resolve().parents[1]/'fixtures/desktop/wf001_wf003_smoke.pdf'


class DoclingConversionCompletionTests(unittest.TestCase):
    def test_actual_status_values_and_structured_error_summary(self):
        self.assertIsNone(require_complete_conversion(SimpleNamespace(status=ConversionStatus.SUCCESS,errors=[]),'fixture.pdf'))
        error=ErrorItem(component_type=DoclingComponentType.MODEL,module_name='rapid_ocr_model',error_message='model unavailable',category=FailureCategory.INFERENCE_FAILURE,page_no=3)
        for status in [ConversionStatus.PARTIAL_SUCCESS,ConversionStatus.FAILURE,ConversionStatus.PENDING,ConversionStatus.STARTED,ConversionStatus.SKIPPED]:
            with self.subTest(status=status),self.assertRaisesRegex(ValueError,'Partial content was rejected before graph writes') as caught:
                require_complete_conversion(SimpleNamespace(status=status,errors=[error]),'fixture.pdf')
            self.assertIn(status.value,str(caught.exception))
            self.assertIn('rapid_ocr_model',str(caught.exception))
            self.assertIn('page 3',str(caught.exception))
        for result in [SimpleNamespace(status=ConversionStatus.SUCCESS,errors=[error]),SimpleNamespace(errors=[]),SimpleNamespace(status='success')]:
            with self.assertRaises(ValueError):require_complete_conversion(result,'fixture.pdf')

    def test_pdf_rejects_partial_before_reading_document_but_allows_success(self):
        document=DoclingDocument(name='complete')
        document.add_text(label='text',text='All content retained.')
        with patch('docling.document_converter.DocumentConverter') as converter:
            converter.return_value.convert.return_value=SimpleNamespace(status=ConversionStatus.PARTIAL_SUCCESS,errors=[])
            with self.assertRaisesRegex(ValueError,'partial_success'):
                DoclingParser().parse(str(PDF),'completion-check')
            converter.return_value.convert.return_value=SimpleNamespace(status=ConversionStatus.SUCCESS,errors=[],document=document)
            parsed=DoclingParser().parse(str(PDF),'completion-check')
            self.assertEqual(['All content retained.'],[e.text for e in parsed.elements])

    def test_native_document_rejects_partial_without_errors(self):
        with patch('docling.document_converter.DocumentConverter') as converter:
            converter.return_value.convert.return_value=SimpleNamespace(status=ConversionStatus.PARTIAL_SUCCESS,errors=[])
            with self.assertRaisesRegex(ValueError,'partial_success'):
                StructuredDocumentParser._convert(Path('fixture.md'),'# Title','markdown')
            converter.return_value.convert.return_value=SimpleNamespace(status=ConversionStatus.SUCCESS,errors=[],document='complete-native-document')
            self.assertEqual('complete-native-document',StructuredDocumentParser._convert(Path('fixture.md'),'# Title','markdown'))
