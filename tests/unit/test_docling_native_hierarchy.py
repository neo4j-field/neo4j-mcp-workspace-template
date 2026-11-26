"""Native Docling hierarchy and downstream context, without layout-model downloads."""
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from docling.datamodel.pipeline_options import HeadingHierarchyOptions
from docling.models.stages.heading_hierarchy.heading_hierarchy_model import HeadingHierarchyModel
from docling_core.types.doc import DoclingDocument

from mcp_neo4j_lexical_graph.parsers.docling_parser import DoclingParser, _get_heading_level
from mcp_neo4j_lexical_graph.chunkers.structured import StructuredChunker
from mcp_neo4j_lexical_graph.chunkers.by_section import BySectionChunker
from mcp_neo4j_lexical_graph.postprocessing.section_hierarchy import assign_section_hierarchy

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/desktop/wf001_wf003_smoke.pdf"


class NativeHierarchyTests(unittest.TestCase):
    def parse_document(self, headings):
        document = DoclingDocument(name="native-hierarchy")
        for heading in headings:
            if heading:
                document.add_heading(text=heading, level=1)
            document.add_text(label="text", text="Some section content.")
        stage = HeadingHierarchyModel(HeadingHierarchyOptions(enabled=True))
        stage.assign_heading_levels(document)
        with (
            patch("docling.document_converter.DocumentConverter") as converter,
            patch("litellm.completion", side_effect=AssertionError("No hierarchy LLM")),
            patch("litellm.acompletion", side_effect=AssertionError("No hierarchy LLM")),
        ):
            converter.return_value.convert.return_value = SimpleNamespace(document=document, status="success", errors=[])
            parsed = DoclingParser().parse(str(FIXTURE), "native")
            options = converter.call_args.kwargs["format_options"]["pdf"].pipeline_options
            self.assertTrue(options.heading_hierarchy_options.enabled)
            self.assertFalse(options.generate_parsed_pages)
        return parsed

    def test_numbered_nested_hierarchy_reaches_sections_and_parents(self):
        parsed = self.parse_document(["1. Overview", "1.1 Details", "1.1.1 Checks", "2. Summary"])
        self.assertEqual([1, 2, 3, 1], [s.level for s in parsed.sections])
        self.assertEqual([parsed.sections[1].id], parsed.sections[0].subsection_ids)
        self.assertEqual([parsed.sections[2].id], parsed.sections[1].subsection_ids)
        self.assertEqual([], parsed.sections[3].subsection_ids)

    def test_flat_and_heading_free_documents_stay_valid(self):
        self.assertEqual([1, 1], [s.level for s in self.parse_document(["Overview", "Summary"]).sections])
        parsed = self.parse_document([None])
        self.assertEqual([], parsed.sections)
        self.assertEqual("Some section content.", parsed.elements[0].text)

    def test_reading_order_depth_is_not_a_heading_level(self):
        self.assertEqual(1, _get_heading_level(SimpleNamespace(), "section_header", 5))
        self.assertEqual(3, _get_heading_level(SimpleNamespace(level=3), "section_header", 0))


class NativeHierarchyChunkTests(unittest.IsolatedAsyncioTestCase):
    async def chunks(self, elements, sections, size=500):
        module = "mcp_neo4j_lexical_graph.chunkers.structured"
        with (
            patch(f"{module}.get_elements_for_document", AsyncMock(return_value=elements)),
            patch(f"{module}.get_sections_for_document", AsyncMock(return_value=sections)),
            patch(f"{module}.get_document", AsyncMock(return_value={"name": "Manual"})),
            patch.object(StructuredChunker, "_get_captions", AsyncMock(return_value={"image": "Figure caption"})),
        ):
            return await StructuredChunker(chunk_size=size).create_chunks(None, "neo4j", "manual")

    async def test_full_chains_for_text_oversized_and_visual_chunks(self):
        sections = [
            {"title": "Overview", "level": 1, "elementIds": ["h1"]},
            {"title": "Details", "level": 2, "elementIds": ["h2", "body", "image"]},
        ]
        elements = [
            {"id": "h1", "type": "heading", "text": "Overview"},
            {"id": "h2", "type": "heading", "text": "Details"},
            {"id": "body", "type": "paragraph", "text": "body " * 50},
            {"id": "image", "type": "image", "text": "A diagram"},
        ]
        for size in (10, 500):
            chunks = await self.chunks(elements, sections, size)
            body = next(c for c in chunks if "body" in c.element_ids)
            self.assertIn("Overview > Details", body.section_context)
            image = next(c for c in chunks if c.type == "image")
            self.assertEqual("Details", image.section_heading)
            self.assertEqual("Overview > Details\nFigure caption", image.section_context)

    async def test_flat_and_heading_free_context(self):
        elements = [{"id": "body", "text": "plain content"}]
        chunks = await self.chunks(elements, [])
        self.assertEqual("", chunks[0].section_context)
        chunks = await self.chunks(elements, [
            {"title": "Earlier", "level": 1, "elementIds": []},
            {"title": "Later", "level": 1, "elementIds": ["body"]},
        ])
        self.assertEqual("Later", chunks[0].section_context)

    async def test_repeated_titles_keep_distinct_parent_paths_in_merged_chunk(self):
        sections = [
            {"title": "A", "level": 1, "elementIds": ["a"]},
            {"title": "Details", "level": 2, "elementIds": ["ad"]},
            {"title": "B", "level": 1, "elementIds": ["b"]},
            {"title": "Details", "level": 2, "elementIds": ["bd"]},
        ]
        elements = [{"id": eid, "type": "heading", "text": title}
                    for eid, title in [("a", "A"), ("ad", "Details"), ("b", "B"), ("bd", "Details")]]
        elements.append({"id": "body", "text": "Content"})
        sections[-1]["elementIds"].append("body")
        chunks = await self.chunks(elements, sections)
        self.assertEqual(1, len(chunks))
        self.assertIn("A > Details", chunks[0].section_context)
        self.assertIn("B > Details", chunks[0].section_context)

    async def test_by_section_propagates_chains_to_text_and_visuals(self):
        sections = [
            {"title": "Overview", "level": 1, "elementIds": ["h1"]},
            {"title": "Details", "level": 2, "elementIds": ["body", "image", "table"]},
        ]
        elements = [{"id": eid, "text": text, "type": kind} for eid, text, kind in [
            ("h1", "Overview", "heading"), ("body", "Content", "paragraph"),
            ("image", "Diagram", "image"), ("table", "Values", "table"),
        ]]
        module = "mcp_neo4j_lexical_graph.chunkers.by_section"
        with (
            patch(f"{module}.get_elements_for_document", AsyncMock(return_value=elements)),
            patch(f"{module}.get_sections_for_document", AsyncMock(return_value=sections)),
        ):
            chunks = await BySectionChunker().create_chunks(None, "neo4j", "manual")
        details = [c for c in chunks if c.section_heading == "Details"]
        self.assertEqual({"text", "image", "table"}, {c.type for c in details})
        self.assertTrue(all(c.section_context == "Overview > Details" for c in details))

    async def test_explicit_agent_correction_remains_available_without_llm(self):
        module = "mcp_neo4j_lexical_graph.postprocessing.section_hierarchy"
        with (
            patch(f"{module}.get_sections_for_document", AsyncMock(return_value=[{"id": "s", "level": 1}])),
            patch(f"{module}.infer_hierarchy_from_llm", AsyncMock(side_effect=AssertionError("No implicit LLM"))),
            patch(f"{module}.update_section_levels", AsyncMock(return_value=1)) as update,
            patch(f"{module}.rebuild_subsection_relationships", AsyncMock(return_value=0)),
            patch(f"{module}.build_heading_chains", AsyncMock(return_value={"s": "Section"})),
            patch(f"{module}.propagate_context_to_chunks", AsyncMock(return_value=0)),
        ):
            await assign_section_hierarchy(None, "neo4j", "manual", "Manual", hierarchy=[{"id": "s", "level": 2}])
            update.assert_awaited_once_with(None, "neo4j", {"s": 2})


if __name__ == "__main__":
    unittest.main()
