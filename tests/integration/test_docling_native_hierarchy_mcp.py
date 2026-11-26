"""Opt-in native hierarchy → adapter → real graph/chunking integration.

Uses real Docling hierarchy inference on synthetic detected headings, not a full
PDF layout conversion or model download. Run only on the disposable test DB.
"""
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from neo4j import AsyncGraphDatabase
from docling.datamodel.pipeline_options import HeadingHierarchyOptions
from docling.models.stages.heading_hierarchy.heading_hierarchy_model import HeadingHierarchyModel
from docling_core.types.doc import DoclingDocument

from mcp_neo4j_lexical_graph.parsers.docling_parser import DoclingParser
from mcp_neo4j_lexical_graph.graph_writer import write_parsed_document
from mcp_neo4j_lexical_graph.chunkers.structured import StructuredChunker
from mcp_neo4j_lexical_graph.chunkers.by_section import BySectionChunker


@unittest.skipUnless(os.getenv("NEO4J_MCP_RUN_INTEGRATION") == "1", "opt-in isolated graph test")
class DoclingNativeHierarchyIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_hierarchy_graph_and_section_aware_chunks(self):
        # The explicit integration flag opts into the supplied test database.
        # All mutable data uses fresh UUID identities and exact cleanup below.
        driver = AsyncGraphDatabase.driver(os.environ["NEO4J_URI"], auth=(
            os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]))
        database = os.getenv("NEO4J_DATABASE", "neo4j")
        source_id = "n1-native-" + uuid4().hex
        document = DoclingDocument(name="native-integration")
        for heading in ("1. Overview", "1.1 Details", "1.1.1 Checks", "2. Summary"):
            document.add_heading(text=heading, level=1)
            document.add_text(label="text", text="Content for " + heading)
        HeadingHierarchyModel(HeadingHierarchyOptions(enabled=True)).assign_heading_levels(document)
        fixture = Path(__file__).resolve().parents[1] / "fixtures/desktop/wf001_wf003_smoke.pdf"
        with patch("docling.document_converter.DocumentConverter") as converter:
            converter.return_value.convert.return_value = SimpleNamespace(document=document, status="success", errors=[])
            parsed = DoclingParser().parse(str(fixture), source_id)
        ids = [parsed.id] + [e.id for e in parsed.elements] + [s.id for s in parsed.sections]
        ids += [f"{parsed.id}_page_{p.page_number}" for p in parsed.pages]
        try:
            await write_parsed_document(driver, database, parsed)
            async with driver.session(database=database) as session:
                result = await session.run("""
                    MATCH (a:Section)-[:HAS_SUBSECTION]->(b:Section)
                    WHERE a.id IN $ids AND b.id IN $ids
                    RETURN a.title AS parent, b.title AS child ORDER BY child
                """, ids=ids)
                self.assertEqual([
                    {"parent": "1. Overview", "child": "1.1 Details"},
                    {"parent": "1.1 Details", "child": "1.1.1 Checks"},
                ], await result.data())
            for chunker in (StructuredChunker(), BySectionChunker()):
                chunks = await chunker.create_chunks(driver, database, parsed.id)
                check_eid = parsed.sections[2].element_ids[-1]
                chunk = next(c for c in chunks if check_eid in c.element_ids)
                self.assertIn("1. Overview > 1.1 Details > 1.1.1 Checks", chunk.section_context)
                summary_eid = parsed.sections[3].element_ids[-1]
                summary = next(c for c in chunks if summary_eid in c.element_ids)
                self.assertIn("2. Summary", summary.section_context)
        finally:
            async with driver.session(database=database) as session:
                await session.run("MATCH (n) WHERE n.id IN $ids DETACH DELETE n", ids=ids)
            await driver.close()


if __name__ == "__main__":
    unittest.main()
