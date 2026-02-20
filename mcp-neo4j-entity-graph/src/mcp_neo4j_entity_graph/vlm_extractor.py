"""Vision Language Model (VLM) entity extraction.

Handles visual chunks (images, tables, pages) by sending both the
extracted text and the image to the VLM for structured extraction.

Lower parallelism (default: 5) since VLM calls are slower and more expensive.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Optional, Type

import litellm
import structlog
from pydantic import BaseModel

from .base_extractor import (
    build_llm_params,
    build_system_prompt,
    build_user_prompt_vlm,
    parse_extraction_response,
)
from .models import (
    ChunkExtractionResult,
    ClassifiedChunk,
    ExtractionSchema,
    ProgressUpdate,
)

logger = structlog.get_logger()


class VlmExtractor:
    """Extract entities from visual chunks using VLM structured output."""

    def __init__(
        self,
        model: str,
        max_retries: int = 3,
    ):
        self.model = model
        self.max_retries = max_retries

        if not litellm.supports_vision(model):
            logger.warning(
                "Model may not support vision",
                model=model,
                hint="Ensure the model supports image inputs for VLM extraction",
            )

    async def extract_chunk(
        self,
        chunk: ClassifiedChunk,
        schema: ExtractionSchema,
        output_model: Optional[Type[BaseModel]] = None,
    ) -> ChunkExtractionResult:
        """Extract entities from a single visual chunk (image + text)."""
        system_prompt = build_system_prompt(schema)
        user_content = build_user_prompt_vlm(chunk)

        response_format: Any = output_model if output_model else {"type": "json_object"}

        for attempt in range(self.max_retries):
            try:
                api_params = build_llm_params(self.model, response_format)
                api_params["messages"] = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ]

                logger.debug(
                    "VLM extraction call",
                    model=self.model,
                    chunk_id=chunk.id,
                    chunk_type=chunk.chunk_type.value,
                    has_text=bool(chunk.text),
                    has_html=bool(chunk.text_as_html),
                )

                response = await litellm.acompletion(**api_params)
                content = response.choices[0].message.content

                result = parse_extraction_response(
                    content, schema, chunk.id, output_model
                )

                if result.entities or result.relationships:
                    logger.debug(
                        "VLM extraction success",
                        chunk_id=chunk.id,
                        entities=len(result.entities),
                        relationships=len(result.relationships),
                    )

                return result

            except litellm.RateLimitError as e:
                logger.warning(
                    f"VLM rate limit (attempt {attempt + 1}/{self.max_retries})",
                    chunk_id=chunk.id,
                    error=str(e),
                )
                if attempt == self.max_retries - 1:
                    logger.error("VLM rate limit exhausted", chunk_id=chunk.id)
                    return ChunkExtractionResult(chunk_id=chunk.id)
                await asyncio.sleep(2 ** (attempt + 2))

            except Exception as e:
                logger.warning(
                    f"VLM extraction attempt {attempt + 1} failed",
                    chunk_id=chunk.id,
                    error=str(e),
                    error_type=type(e).__name__,
                )
                if attempt == self.max_retries - 1:
                    logger.error("All VLM extraction attempts failed", chunk_id=chunk.id)
                    return ChunkExtractionResult(chunk_id=chunk.id)
                await asyncio.sleep(2 ** (attempt + 1))

        return ChunkExtractionResult(chunk_id=chunk.id)

    async def extract_many(
        self,
        chunks: list[ClassifiedChunk],
        schema: ExtractionSchema,
        output_model: Optional[Type[BaseModel]] = None,
        parallel: int = 5,
        progress_callback: Optional[Callable[[ProgressUpdate], None]] = None,
    ) -> list[ChunkExtractionResult]:
        """Extract entities from multiple visual chunks in parallel."""
        if not chunks:
            return []

        semaphore = asyncio.Semaphore(parallel)
        completed = 0
        total = len(chunks)

        async def process(chunk: ClassifiedChunk) -> ChunkExtractionResult:
            nonlocal completed
            async with semaphore:
                result = await self.extract_chunk(chunk, schema, output_model)
                completed += 1
                if progress_callback:
                    progress_callback(
                        ProgressUpdate(
                            stage="vlm_extraction",
                            current=completed,
                            total=total,
                            message=f"VLM: {completed}/{total} chunks",
                        )
                    )
                return result

        tasks = [process(c) for c in chunks]
        return list(await asyncio.gather(*tasks))
