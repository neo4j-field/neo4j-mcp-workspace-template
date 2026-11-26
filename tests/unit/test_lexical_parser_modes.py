"""Deterministic adapter fixtures for the three retained PDF parser modes.

PyMuPDF and page-image use the real PDF backend.  The Docling adapter is run
against a tiny in-process converter fixture so CI tests our normalization logic
without downloading Docling's model artifacts or depending on model output.
"""

from __future__ import annotations

import sys
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from mcp_neo4j_lexical_graph.worker import parse_single_pdf


FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures/desktop/wf001_wf003_smoke.pdf"
)


class _Label:
    def __init__(self, value: str):
        self.value = value


class _BBox:
    l, t, r, b = 20, 20, 300, 80


class _Provenance:
    page_no = 1
    bbox = _BBox()


class _Item:
    def __init__(self, label: str, text: str, *, level: int | None = None):
        self.label = _Label(label)
        self.text = text
        self.prov = [_Provenance()]
        self.level = level


class _DoclingDocument:
    def iterate_items(self):
        yield _Item("title", "TEST-002 parser fixture"), 0
        yield _Item("text", "Deterministic Docling adapter content."), 1


class _DocumentConverter:
    def __init__(self, **_kwargs):
        pass

    def convert(self, _path: str):
        return types.SimpleNamespace(document=_DoclingDocument(), status="success", errors=[])


class _PdfPipelineOptions:
    pass


@contextmanager
def _deterministic_docling_backend():
    converter = types.ModuleType("docling.document_converter")
    converter.DocumentConverter = _DocumentConverter
    converter.PdfFormatOption = lambda **kwargs: kwargs
    pipeline = types.ModuleType("docling.datamodel.pipeline_options")
    pipeline.PdfPipelineOptions = _PdfPipelineOptions
    pipeline.HeadingHierarchyOptions = lambda **kwargs: types.SimpleNamespace(**kwargs)
    base_models = types.ModuleType("docling.datamodel.base_models")
    base_models.InputFormat = types.SimpleNamespace(PDF="pdf")
    modules = {
        "docling": types.ModuleType("docling"),
        "docling.document_converter": converter,
        "docling.datamodel": types.ModuleType("docling.datamodel"),
        "docling.datamodel.pipeline_options": pipeline,
        "docling.datamodel.base_models": base_models,
    }
    with patch.dict(sys.modules, modules):
        yield


class LexicalParserModeTests(unittest.TestCase):
    def test_pymupdf_adapter_parses_real_pdf_into_chunks(self) -> None:
        result = parse_single_pdf(
            str(FIXTURE),
            "test002-pymupdf",
            1,
            "pymupdf",
            extract_images=False,
            extract_tables=False,
        )

        self.assertEqual("pymupdf", result["parse_mode"])
        self.assertEqual(1, result["total_pages"])
        self.assertEqual(1, len(result["chunks"]))
        self.assertIn("wf001-wf003-20260910", result["chunks"][0]["text"])

    def test_page_image_adapter_parses_real_pdf_into_rendered_pages(self) -> None:
        result = parse_single_pdf(
            str(FIXTURE), "test002-page-image", 1, "page_image", dpi=72
        )
        parsed = result["parsed_doc"]

        self.assertEqual("page_image", parsed["parse_mode"])
        self.assertEqual(1, len(parsed["pages"]))
        self.assertEqual([], parsed["elements"])
        self.assertEqual("image/png", parsed["pages"][0]["image_mime_type"])
        self.assertTrue(parsed["pages"][0]["image_base64"].startswith("iVBOR"))
        self.assertIn("wf001-wf003-20260910", parsed["pages"][0]["text"])

    def test_docling_adapter_normalizes_converter_output(self) -> None:
        with _deterministic_docling_backend():
            result = parse_single_pdf(
                str(FIXTURE),
                "test002-docling",
                1,
                "docling",
                extract_sections=True,
                store_page_images=False,
            )
        parsed = result["parsed_doc"]

        self.assertEqual("docling", parsed["parse_mode"])
        self.assertEqual(1, len(parsed["pages"]))
        self.assertEqual(["heading", "paragraph"], [e["type"] for e in parsed["elements"]])
        self.assertEqual("TEST-002 parser fixture", parsed["sections"][0]["title"])
        self.assertEqual(
            [e["id"] for e in parsed["elements"]],
            parsed["pages"][0]["element_ids"],
        )


if __name__ == "__main__":
    unittest.main()
