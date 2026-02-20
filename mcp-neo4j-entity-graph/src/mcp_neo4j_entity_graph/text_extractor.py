"""Text-only entity extraction using LiteLLM structured output.

Handles Chunk nodes where type="text" (no image content).
High parallelism (default: 20 concurrent) since text extraction is fast.
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
    build_user_prompt_text,
    parse_extraction_response,
)
from .models import (
    ChunkExtractionResult,
    ClassifiedChunk,
    ExtractionSchema,
    ProgressUpdate,
)

logger = structlog.get_logger()


class TextExtractor:
    """Extract entities from text chunks using LLM structured output."""

    def __init__(
        self,
        model: str,
        max_retries: int = 3,
    ):
        self.model = model
        self.max_retries = max_retries

    async def extract_chunk(
        self,
        chunk: ClassifiedChunk,
        schema: ExtractionSchema,
        output_model: Optional[Type[BaseModel]] = None,
    ) -> ChunkExtractionResult:
        """Extract entities from a single text chunk."""
        system_prompt = build_system_prompt(schema)
        user_prompt = build_user_prompt_text(chunk)

        response_format: Any = output_model if output_model else {"type": "json_object"}

        for attempt in range(self.max_retries):
            try:
                api_params = build_llm_params(self.model, response_format)
                api_params["messages"] = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ]

                logger.debug(
                    "Text extraction call",
                    model=self.model,
                    chunk_id=chunk.id,
                    text_length=len(chunk.text or ""),
                )

                response = await litellm.acompletion(**api_params)
                content = response.choices[0].message.content

                result = parse_extraction_response(
                    content, schema, chunk.id, output_model
                )

                if result.entities or result.relationships:
                    logger.debug(
                        "Text extraction success",
                        chunk_id=chunk.id,
                        entities=len(result.entities),
                        relationships=len(result.relationships),
                    )

                return result

            except litellm.RateLimitError as e:
                logger.warning(
                    f"Rate limit (attempt {attempt + 1}/{self.max_retries})",
                    chunk_id=chunk.id,
                    error=str(e),
                )
                if attempt == self.max_retries - 1:
                    logger.error("Rate limit exhausted", chunk_id=chunk.id)
                    return ChunkExtractionResult(chunk_id=chunk.id)
                await asyncio.sleep(2 ** (attempt + 2))

            except Exception as e:
                logger.warning(
                    f"Text extraction attempt {attempt + 1} failed",
                    chunk_id=chunk.id,
                    error=str(e),
                    error_type=type(e).__name__,
                )
                if attempt == self.max_retries - 1:
                    logger.error("All text extraction attempts failed", chunk_id=chunk.id)
                    return ChunkExtractionResult(chunk_id=chunk.id)
                await asyncio.sleep(2**attempt)

        return ChunkExtractionResult(chunk_id=chunk.id)

    async def extract_many(
        self,
        chunks: list[ClassifiedChunk],
        schema: ExtractionSchema,
        output_model: Optional[Type[BaseModel]] = None,
        parallel: int = 20,
        progress_callback: Optional[Callable[[ProgressUpdate], None]] = None,
    ) -> list[ChunkExtractionResult]:
        """Extract entities from multiple text chunks in parallel."""
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
                            stage="text_extraction",
                            current=completed,
                            total=total,
                            message=f"Text: {completed}/{total} chunks",
                        )
                    )
                return result

        tasks = [process(c) for c in chunks]
        return list(await asyncio.gather(*tasks))
