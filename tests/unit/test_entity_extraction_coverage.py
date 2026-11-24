"""Deterministic regression coverage for BUG-003 silent extraction loss."""

from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastmcp import Client

from mcp_neo4j_entity_graph.base_extractor import (
    build_user_prompt_text,
    build_user_prompt_vlm,
    load_extraction_output_model,
    parse_extraction_response,
    schema_from_pydantic_module,
)
from mcp_neo4j_entity_graph.models import (
    ChunkExtractionOutcome,
    ChunkExtractionResult,
    ChunkType,
    ClassifiedChunk,
    ExtractedEntity,
)
from mcp_neo4j_entity_graph.server import create_mcp_server
from mcp_neo4j_entity_graph.text_extractor import TextExtractor


TEST_RUN_ID = "bug003-unit-regression"
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "fixtures/entity/bug003_schema.py"


class _FakeResult:
    def __init__(self, *, rows=None, record=None):
        self._rows = rows or []
        self._record = record

    async def consume(self):
        return None

    async def data(self):
        return self._rows

    async def single(self):
        return self._record


class _FakeSession:
    def __init__(self, source_label: str):
        self.source_label = source_label

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def execute_write(self, callback):
        return await callback(self)

    async def run(self, query, **params):
        if "AS legacy" in query:
            return _FakeResult(record={"legacy": 0})
        if "SET p.invalidated = true" in query:
            return _FakeResult()
        if "RETURN published" in query:
            return _FakeResult(record={"published": len(params["sources"])})
        if "eligible_sources" in query:
            return _FakeResult(record={"eligible_sources": 4})

        if f"MATCH (n:{self.source_label})" in query:
            if "WHERE (n.text IS NOT NULL OR n.imageBase64 IS NOT NULL)" not in query:
                raise AssertionError("content eligibility must be grouped before skip filters")
            if "completedFingerprints" not in query or "run.status = 'complete'" not in query:
                raise AssertionError("selection must use successful durable completion evidence")
            is_page = self.source_label == "Bug003PageSource"
            return _FakeResult(
                rows=[
                    {
                        "id": f"{TEST_RUN_ID}-already-extracted",
                        "text": "SENTINEL-IGNORED",
                        "type": "text",
                        "isPage": is_page,
                    },
                    {
                        "id": f"{TEST_RUN_ID}-success",
                        "text": "SENTINEL-SUCCESS",
                        "type": "text",
                        "isPage": is_page,
                    },
                    {
                        "id": f"{TEST_RUN_ID}-empty",
                        "text": "SENTINEL-EMPTY",
                        "type": "text",
                        "isPage": is_page,
                    },
                    {
                        "id": f"{TEST_RUN_ID}-failed",
                        "text": "SENTINEL-FAILED-END",
                        "type": "text",
                        "isPage": is_page,
                    },
                ][1:]
            )

        if "$entities" in query:
            return _FakeResult(
                record={
                    "entities_created": len(params["entities"]),
                    "rels_created": len(params["entities"]),
                }
            )

        if "$relationships" in query:
            return _FakeResult(record={"created": 0})

        if "sources_persisted" in query:
            return _FakeResult(record={"sources_persisted": 1})

        raise AssertionError(query)


class _FakeDriver:
    def __init__(self, source_label: str):
        self.source_label = source_label

    def session(self, **_kwargs):
        return _FakeSession(self.source_label)


class EntityExtractionCoverageTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.output_model = load_extraction_output_model(str(SCHEMA_PATH))
        import sys

        cls.schema = schema_from_pydantic_module(sys.modules["extraction_models"])

    def test_prompt_preserves_end_sentinel_for_text_and_page(self) -> None:
        text = "start\n" + ("payload " * 2000) + "SENTINEL-AT-END"
        text_chunk = ClassifiedChunk(id="text", chunk_type=ChunkType.TEXT, text=text)
        page_chunk = ClassifiedChunk(
            id="page",
            chunk_type=ChunkType.PAGE,
            text=text,
            image_base64="aW1hZ2U=",
            image_mime_type="image/png",
        )

        self.assertIn("SENTINEL-AT-END", build_user_prompt_text(text_chunk))
        page_prompt = build_user_prompt_vlm(page_chunk)
        self.assertIn("SENTINEL-AT-END", page_prompt[0]["text"])

    def test_parser_distinguishes_empty_invalid_and_nonempty_responses(self) -> None:
        empty = parse_extraction_response(
            '{"bug003_sentinels": []}', self.schema, "empty", self.output_model
        )
        invalid = parse_extraction_response(
            '{"bug003_sentinels": [', self.schema, "invalid", self.output_model
        )
        blank = parse_extraction_response("", self.schema, "blank", self.output_model)
        nonempty = parse_extraction_response(
            '{"bug003_sentinels": [{"sentinelId": "SENTINEL"}]}',
            self.schema,
            "success",
            self.output_model,
        )

        self.assertEqual(ChunkExtractionOutcome.EMPTY, empty.outcome)
        self.assertEqual(ChunkExtractionOutcome.FAILED, invalid.outcome)
        self.assertEqual(ChunkExtractionOutcome.FAILED, blank.outcome)
        self.assertEqual(ChunkExtractionOutcome.SUCCESS, nonempty.outcome)

    async def test_parse_failure_is_retried_and_exhaustion_is_explicit(self) -> None:
        response = type(
            "Response",
            (),
            {
                "choices": [
                    type(
                        "Choice",
                        (),
                        {"message": type("Message", (), {"content": "not-json"})()},
                    )()
                ]
            },
        )()
        extractor = TextExtractor(model="fixture-model", max_retries=2)

        with (
            patch(
                "mcp_neo4j_entity_graph.text_extractor.litellm.acompletion",
                new=AsyncMock(return_value=response),
            ) as completion,
            patch("mcp_neo4j_entity_graph.text_extractor.asyncio.sleep", new=AsyncMock()),
        ):
            result = await extractor.extract_chunk(
                ClassifiedChunk(id="failed", chunk_type=ChunkType.TEXT, text="sentinel"),
                self.schema,
                self.output_model,
            )

        self.assertEqual(2, completion.await_count)
        self.assertEqual(ChunkExtractionOutcome.FAILED, result.outcome)
        self.assertEqual(2, result.attempts)
        self.assertIn("parse", result.error.lower())

    async def _stub_extract(self, chunk, _schema, _output_model):
        if chunk.id.endswith("-success"):
            return ChunkExtractionResult(
                chunk_id=chunk.id,
                outcome=ChunkExtractionOutcome.SUCCESS,
                entities=[
                    ExtractedEntity(
                        label="Bug003Sentinel",
                        properties={
                            "sentinelId": "SENTINEL-SUCCESS",
                            "testRunId": TEST_RUN_ID,
                        },
                    )
                ],
            )
        if chunk.id.endswith("-empty"):
            return ChunkExtractionResult(
                chunk_id=chunk.id, outcome=ChunkExtractionOutcome.EMPTY
            )
        return ChunkExtractionResult(
            chunk_id=chunk.id,
            outcome=ChunkExtractionOutcome.FAILED,
            error="structured response remained truncated after 3 attempts",
            attempts=3,
        )

    async def test_job_reports_coverage_failure_for_chunk_and_page_sources(self) -> None:
        for source_label in ("Bug003ChunkSource", "Bug003PageSource"):
            with self.subTest(source_label=source_label):
                server = create_mcp_server(_FakeDriver(source_label))
                with patch(
                    "mcp_neo4j_entity_graph.server.TextExtractor.extract_chunk",
                    new=self._stub_extract,
                ):
                    async with Client(server) as client:
                        started_result = await client.call_tool(
                            "extract_entities",
                            {
                                "schema": str(SCHEMA_PATH),
                                "source_label": source_label,
                                "force": False,
                                "batch_size": 1,
                                "text_parallel": 3,
                            },
                        )
                        started = json.loads(started_result.content[0].text)
                        for _ in range(100):
                            status_result = await client.call_tool(
                                "check_extraction_status", {"job_id": started["job_id"]}
                            )
                            status = json.loads(status_result.content[0].text)
                            if status["status"] in {"complete", "failed"}:
                                break
                            await asyncio.sleep(0.005)
                        else:
                            self.fail("BUG-003 fixture extraction did not finish")

                self.assertEqual("failed", status["status"], status)
                self.assertEqual(4, status["eligible_sources"])
                self.assertEqual(3, status["selected_sources"])
                self.assertEqual(3, status["sources_attempted"])
                self.assertEqual(1, status["sources_succeeded"])
                self.assertEqual(1, status["sources_empty"])
                self.assertEqual(1, status["sources_failed"])
                self.assertEqual(0, status["sources_persisted"])
                self.assertEqual([f"{TEST_RUN_ID}-failed"], status["failed_source_ids"])


if __name__ == "__main__":
    unittest.main()
