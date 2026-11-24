"""Regression tests for all-document lexical graph chunk rebuilding."""

from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastmcp import Client

from mcp_neo4j_lexical_graph.server import create_mcp_server


class LexicalChunkRebuildTests(unittest.IsolatedAsyncioTestCase):
    async def _call_chunk_tool(
        self,
        documents: list[dict[str, object]],
        *,
        clear_existing_chunks: bool,
        document_id: str | None = None,
    ) -> tuple[dict[str, object], AsyncMock]:
        chunk_document = AsyncMock(
            side_effect=lambda *args, **kwargs: {
                "document_id": kwargs["document_id"],
                "chunks_created": 1,
            }
        )
        process_pool = MagicMock()
        server = create_mcp_server(MagicMock(), process_pool=process_pool)

        with (
            patch(
                "mcp_neo4j_lexical_graph.server.list_all_documents",
                AsyncMock(return_value=documents),
            ),
            patch(
                "mcp_neo4j_lexical_graph.server.get_document",
                AsyncMock(
                    side_effect=lambda _driver, _database, doc_id: next(
                        (doc for doc in documents if doc["id"] == doc_id), None
                    )
                ),
            ),
            patch(
                "mcp_neo4j_lexical_graph.server._chunk_single_document",
                chunk_document,
            ),
        ):
            async with Client(server) as client:
                result = await client.call_tool(
                    "chunk_lexical_graph",
                    {
                        "document_id": document_id,
                        "clear_existing_chunks": clear_existing_chunks,
                    },
                )

        self.assertFalse(result.is_error, result)
        return json.loads(result.content[0].text), chunk_document

    async def test_clear_existing_without_document_rebuilds_all_active_eligible_documents(self) -> None:
        documents = [
            {"id": "doc-with-chunks", "active": True, "totalChunkCount": 2, "parseMode": "docling"},
            {"id": "doc-without-chunks", "active": True, "totalChunkCount": 0, "parseMode": "docling"},
            {"id": "inactive-doc", "active": False, "totalChunkCount": 1, "parseMode": "docling"},
            {"id": "integrated-chunks", "active": True, "totalChunkCount": 1, "parseMode": "pymupdf"},
            {"id": "page-image", "active": True, "totalChunkCount": 0, "parseMode": "page_image"},
        ]

        response, chunk_document = await self._call_chunk_tool(
            documents,
            clear_existing_chunks=True,
        )

        self.assertEqual("success", response["status"])
        self.assertEqual(
            ["doc-with-chunks", "doc-without-chunks"],
            [call.kwargs["document_id"] for call in chunk_document.await_args_list],
        )
        self.assertTrue(
            all(
                call.kwargs["clear_existing_chunks"]
                for call in chunk_document.await_args_list
            )
        )

    async def test_default_all_document_call_only_chunks_documents_without_chunks(self) -> None:
        documents = [
            {"id": "doc-with-chunks", "active": True, "totalChunkCount": 2, "parseMode": "docling"},
            {"id": "doc-without-chunks", "active": True, "totalChunkCount": 0, "parseMode": "docling"},
        ]

        _response, chunk_document = await self._call_chunk_tool(
            documents,
            clear_existing_chunks=False,
        )

        self.assertEqual(
            ["doc-without-chunks"],
            [call.kwargs["document_id"] for call in chunk_document.await_args_list],
        )

    async def test_explicit_document_rebuild_remains_scoped_to_that_document(self) -> None:
        documents = [
            {"id": "target-doc", "active": True, "totalChunkCount": 2, "parseMode": "docling"},
            {"id": "other-doc", "active": True, "totalChunkCount": 2, "parseMode": "docling"},
        ]

        _response, chunk_document = await self._call_chunk_tool(
            documents,
            clear_existing_chunks=True,
            document_id="target-doc",
        )

        self.assertEqual(1, chunk_document.await_count)
        self.assertEqual("target-doc", chunk_document.await_args.kwargs["document_id"])


if __name__ == "__main__":
    unittest.main()
