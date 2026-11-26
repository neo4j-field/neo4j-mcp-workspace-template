"""Opt-in exact lexical deletion and metadata write boundaries on disposable DB."""

import os
import unittest
from uuid import uuid4

from neo4j import AsyncGraphDatabase
from mcp_neo4j_lexical_graph.graph_reader import delete_document_cascade
from mcp_neo4j_lexical_graph.graph_writer import write_parsed_document
from mcp_neo4j_lexical_graph.models import ParsedDocument


@unittest.skipUnless(
    os.getenv("NEO4J_MCP_RUN_INTEGRATION") == "1", "disposable DB opt-in"
)
class LexicalWriteBoundaryIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.driver = AsyncGraphDatabase.driver(
            os.environ["NEO4J_URI"],
            auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"]),
        )
        self.database = os.environ["NEO4J_DATABASE"]
        self.run = uuid4().hex
        self.target = "boundary-" + self.run

    async def asyncTearDown(self):
        async with self.driver.session(database=self.database) as session:
            await session.run(
                "MATCH (n {testRunId:$run}) DETACH DELETE n", run=self.run
            )
        await self.driver.close()

    async def test_exact_deletion_preserves_prefix_neighbors_shared_children_and_domain(
        self,
    ):
        async with self.driver.session(database=self.database) as session:
            await session.run(
                """
                CREATE (d:Document {id:$target,testRunId:$run}),
                       (neighbor:Document {id:$target+'_neighbor',testRunId:$run})
                CREATE (page:Page {id:$target+'-private-page',testRunId:$run}),(d)-[:HAS_PAGE]->(page)
                CREATE (private:Element {id:'arbitrary-'+$run,testRunId:$run}),(page)-[:HAS_ELEMENT]->(private)
                CREATE (prefixed:Element {id:$target+'_neighbor-element',testRunId:$run}),
                       (neighbor)-[:HAS_ELEMENT]->(prefixed)
                CREATE (sharedPage:Page {id:$target+'-shared-page',testRunId:$run}),
                       (d)-[:HAS_PAGE]->(sharedPage),(neighbor)-[:HAS_PAGE]->(sharedPage)
                CREATE (sharedElement:Element {id:$target+'-shared-element',testRunId:$run}),
                       (sharedPage)-[:HAS_ELEMENT]->(sharedElement)
                CREATE (section:Section {id:$target+'-section',testRunId:$run}),
                       (d)-[:HAS_SECTION]->(section),(section)-[:HAS_ELEMENT]->(private)
                CREATE (chunk:Chunk {id:$target+'-chunk',testRunId:$run}),(chunk)-[:PART_OF]->(d),
                       (chunk)-[:HAS_ELEMENT]->(private)
                CREATE (domain:Product {id:$target+'-domain',testRunId:$run}),
                       (domain)-[:EXTRACTED_FROM]->(chunk)
                CREATE (orphan:Element {id:$target+'-orphan',testRunId:$run})
                CREATE (sharedSection:Section {id:$target+'-shared-section',testRunId:$run}),
                       (d)-[:HAS_SECTION]->(sharedSection),(neighbor)-[:HAS_SECTION]->(sharedSection)
                CREATE (sectionElement:Element {id:$target+'-section-element',testRunId:$run}),
                       (sharedSection)-[:HAS_ELEMENT]->(sectionElement)
                CREATE (sharedChunk:Chunk {id:$target+'-shared-chunk',testRunId:$run}),
                       (sharedChunk)-[:PART_OF]->(d),(sharedChunk)-[:PART_OF]->(neighbor)
                CREATE (chunkElement:Element {id:$target+'-chunk-element',testRunId:$run}),
                       (sharedChunk)-[:HAS_ELEMENT]->(chunkElement)
            """,
                target=self.target,
                run=self.run,
            )
        counts = await delete_document_cascade(self.driver, self.database, self.target)
        self.assertEqual(1, counts["Document"])
        self.assertEqual(1, counts["Element"])
        self.assertEqual(1, counts["Chunk"])
        async with self.driver.session(database=self.database) as session:
            result = await session.run(
                "MATCH (n {testRunId:$run}) RETURN n.id AS id", run=self.run
            )
            ids = {row["id"] for row in await result.data()}
            self.assertEqual(
                {
                    self.target + suffix
                    for suffix in (
                        "_neighbor",
                        "_neighbor-element",
                        "-shared-page",
                        "-shared-element",
                        "-domain",
                        "-shared-chunk",
                        "-chunk-element",
                        "-orphan",
                        "-shared-section",
                        "-section-element",
                    )
                },
                ids,
            )
            result = await session.run(
                "MATCH ()-[r:EXTRACTED_FROM]->() RETURN count(r) AS count"
            )
            self.assertEqual(0, (await result.single())["count"])
        # Repeated deletion is a no-op, not an ID-prefix cleanup.
        self.assertTrue(
            all(
                count == 0
                for count in (
                    await delete_document_cascade(
                        self.driver, self.database, self.target
                    )
                ).values()
            )
        )

    async def test_valid_metadata_keeps_document_identity_and_custom_fields(self):
        doc = ParsedDocument(
            id=self.target,
            source_id=self.run,
            name="Custom",
            source="/fixture.pdf",
            parse_mode="docling",
            metadata={"customer name": "Acme", "testRunId": self.run},
        )
        await write_parsed_document(self.driver, self.database, doc)
        async with self.driver.session(database=self.database) as session:
            result = await session.run(
                "MATCH (d:Document {id:$id}) RETURN d.sourceId AS source,d.active AS active,d.customer_name AS custom",
                id=self.target,
            )
            self.assertEqual(
                {"source": self.run, "active": True, "custom": "Acme"},
                (await result.single()).data(),
            )
