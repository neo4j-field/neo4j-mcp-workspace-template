"""Navigation order/page spans are independent of opaque node identifiers."""

import os
import unittest
from uuid import uuid4

from neo4j import AsyncGraphDatabase
from mcp_neo4j_lexical_graph.models import (
    ParsedDocument,
    ParsedElement,
    ParsedPage,
    ParsedSection,
)
from mcp_neo4j_lexical_graph.graph_writer import write_parsed_document
from mcp_neo4j_lexical_graph.graph_reader import (
    get_elements_for_document,
    get_sections_for_document,
)


@unittest.skipUnless(
    os.getenv("NEO4J_MCP_RUN_INTEGRATION") == "1", "opt-in disposable database"
)
class NavigationMetadataTests(unittest.IsolatedAsyncioTestCase):
    async def test_opaque_ids_order_and_descendant_page_spans(self):
        driver = AsyncGraphDatabase.driver(
            os.environ["NEO4J_URI"],
            auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
        )
        database = os.getenv("NEO4J_DATABASE", "neo4j")
        prefix = "navigation-" + uuid4().hex
        ids = [
            prefix + suffix
            for suffix in ("-doc", "-z", "-a", "-m", "-parent", "-child")
        ]
        document = ParsedDocument(
            id=ids[0],
            source_id=prefix,
            name="Navigation fixture",
            source="synthetic",
            parse_mode="docling",
            pages=[
                ParsedPage(page_number=page, element_ids=[eid])
                for page, eid in zip((0, 9, 10), ids[1:4])
            ],
            elements=[
                ParsedElement(
                    id=eid, type="paragraph", text=str(page), page_number=page
                )
                for page, eid in zip((0, 9, 10), ids[1:4])
            ],
            sections=[
                ParsedSection(
                    id=ids[4],
                    title="Parent",
                    level=1,
                    element_ids=[ids[1]],
                    subsection_ids=[ids[5]],
                ),
                ParsedSection(id=ids[5], title="Child", level=2, element_ids=ids[2:4]),
            ],
        )
        cleanup_ids = ids + [f"{ids[0]}_page_{page}" for page in (0, 9, 10)]
        try:
            await write_parsed_document(driver, database, document)
            elements = await get_elements_for_document(driver, database, ids[0])
            self.assertEqual(ids[1:4], [e["id"] for e in elements])
            sections = await get_sections_for_document(driver, database, ids[0])
            self.assertEqual(ids[4:], [s["id"] for s in sections])
            async with driver.session(database=database) as session:
                rows = await (
                    await session.run(
                        "MATCH (s:Section) WHERE s.id IN $ids RETURN s.title AS title, s.order AS order, s.pageStart AS start, s.pageEnd AS end ORDER BY s.order",
                        ids=ids[4:],
                    )
                ).data()
                self.assertEqual(
                    [
                        {"title": "Parent", "order": 0, "start": 0, "end": 10},
                        {"title": "Child", "order": 1, "start": 9, "end": 10},
                    ],
                    rows,
                )
        finally:
            async with driver.session(database=database) as session:
                await session.run(
                    "MATCH (n) WHERE n.id IN $ids DETACH DELETE n", ids=cleanup_ids
                )
            await driver.close()
