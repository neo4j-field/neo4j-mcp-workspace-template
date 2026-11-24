"""Regression coverage for GPT-6 extraction through the pinned LiteLLM."""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from mcp_neo4j_entity_graph.base_extractor import (
    build_llm_params,
    load_extraction_output_model,
    schema_from_pydantic_module,
)
from mcp_neo4j_entity_graph.models import ChunkType, ClassifiedChunk
from mcp_neo4j_entity_graph.text_extractor import TextExtractor


class GPT6ParameterTests(unittest.IsolatedAsyncioTestCase):
    def test_model_families(self):
        for model in ("gpt-6-luna", "openai/gpt-6-luna", "gpt-6-sol"):
            with self.subTest(model=model):
                params = build_llm_params(model, {"type": "json_object"})
                self.assertEqual("low", params["reasoning_effort"])
                self.assertEqual(["reasoning_effort"], params["allowed_openai_params"])
                self.assertNotIn("temperature", params)

        for model in ("gpt-5.4-mini", "o3", "ollama/qwen3.5", "gpt-4o-mini"):
            with self.subTest(model=model):
                params = build_llm_params(model, {"type": "json_object"})
                self.assertNotIn("allowed_openai_params", params)
                if model.startswith(("gpt-5", "o3")):
                    self.assertNotIn("temperature", params)
                else:
                    self.assertEqual(0.0, params["temperature"])

    async def test_request_boundary(self):
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"bug003_sentinels": []}'))]
        )
        completion = AsyncMock(return_value=response)
        extractor = TextExtractor(model="openai/gpt-6-luna", max_retries=1)
        output_model = load_extraction_output_model(str(Path(__file__).resolve().parents[1] / "fixtures/entity/bug003_schema.py"))
        import sys
        schema = schema_from_pydantic_module(sys.modules["extraction_models"])
        with patch("mcp_neo4j_entity_graph.text_extractor.litellm.acompletion", completion):
            result = await extractor.extract_chunk(
                ClassifiedChunk(id="gpt6", chunk_type=ChunkType.TEXT, text="test"),
                schema,
                output_model,
            )
        self.assertEqual("empty", result.outcome.value)
        kwargs = completion.await_args.kwargs
        self.assertEqual("openai/gpt-6-luna", kwargs["model"])
        self.assertEqual(["reasoning_effort"], kwargs["allowed_openai_params"])
        self.assertNotIn("temperature", kwargs)


if __name__ == "__main__":
    unittest.main()
