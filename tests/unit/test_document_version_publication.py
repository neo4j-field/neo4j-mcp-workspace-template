"""Document publication uses one transaction and changes activation only last."""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from mcp_neo4j_lexical_graph.graph_writer import (
    activate_document_version,
    write_document_atomically,
    write_parsed_document,
)


from mcp_neo4j_lexical_graph.models import ParsedDocument


class DocumentPublicationTests(unittest.IsolatedAsyncioTestCase):
    def driver(self):
        driver, session, transaction = MagicMock(), AsyncMock(), AsyncMock()
        driver.session.return_value.__aenter__.return_value = session

        async def execute_write(operation):
            return await operation(transaction)

        session.execute_write.side_effect = execute_write
        return driver, session, transaction

    async def test_write_finishes_before_activation_in_same_transaction(self):
        driver, session, transaction = self.driver()
        events = []

        async def write(transaction_driver):
            async with transaction_driver.session(database="test") as tx:
                self.assertIs(transaction, tx)
                events.append("write")
            return {"document_id": "manual_v2"}

        async def activate(tx, source_id, document_id):
            self.assertIs(transaction, tx)
            self.assertEqual(("manual", "manual_v2"), (source_id, document_id))
            events.append("activate")

        with patch("mcp_neo4j_lexical_graph.graph_writer._activate_document", activate):
            result = await write_document_atomically(driver, "test", "manual", "manual_v2", write)
        self.assertEqual(["write", "activate"], events)
        self.assertEqual("manual_v2", result["document_id"])
        session.execute_write.assert_awaited_once()

    async def test_failed_write_never_changes_active_version(self):
        driver, _, _ = self.driver()

        async def write(_):
            raise RuntimeError("injected midway through graph")

        with patch("mcp_neo4j_lexical_graph.graph_writer._activate_document", AsyncMock()) as activate:
            with self.assertRaisesRegex(RuntimeError, "injected"):
                await write_document_atomically(driver, "test", "manual", "manual_v2", write)
        activate.assert_not_awaited()

    async def test_invalid_chunk_set_refuses_before_activation(self):
        driver, _, transaction = self.driver()
        result = AsyncMock()
        result.single.side_effect = [{"sourceId": "manual"}, {"count": 0}]
        transaction.run.return_value = result
        with patch("mcp_neo4j_lexical_graph.graph_writer._activate_document", AsyncMock()) as activate:
            with self.assertRaisesRegex(ValueError, "active versions were preserved"):
                await activate_document_version(driver, "test", "manual_v2", 99)
        activate.assert_not_awaited()

    async def test_commit_failure_is_not_reported_as_success(self):
        driver, session, transaction = self.driver()
        write = AsyncMock(return_value={"document_id": "manual_v2"})

        async def failed_commit(operation):
            await operation(transaction)
            raise RuntimeError("commit failed")

        session.execute_write.side_effect = failed_commit
        with self.assertRaisesRegex(RuntimeError, "commit failed"):
            await write_document_atomically(driver, "test", "manual", "manual_v2", write)
        write.assert_awaited_once()

    async def test_deferred_constraint_failure_precedes_any_data_transaction(self):
        driver, session, _ = self.driver()
        result = AsyncMock()
        result.consume.side_effect = RuntimeError("constraint permission denied")
        session.run.return_value = result
        doc = ParsedDocument(
            id="manual_v2", source_id="manual", version=2,
            name="Manual", source="/synthetic/manual.md", parse_mode="document",
        )
        with self.assertRaisesRegex(RuntimeError, "constraint permission denied"):
            await write_parsed_document(driver, "test", doc)
        session.execute_write.assert_not_awaited()
