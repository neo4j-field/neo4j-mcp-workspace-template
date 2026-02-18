"""Embedding module using LiteLLM.

Supports 100+ embedding providers through LiteLLM abstraction.
Ported from mcp-neo4j-lexical-graph with minimal changes.
"""

import asyncio
from typing import Optional, Callable

import litellm
import structlog

from .models import ProgressUpdate

logger = structlog.get_logger()

DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"


class ChunkEmbedder:
    """Generate embeddings using LiteLLM with parallelised batch processing."""

    def __init__(
        self,
        model: str = DEFAULT_EMBEDDING_MODEL,
        batch_size: int = 100,
        max_retries: int = 3,
    ):
        self.model = model
        self.batch_size = batch_size
        self.max_retries = max_retries
        logger.info("ChunkEmbedder initialized", model=model, batch_size=batch_size)

    async def embed_texts_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = await litellm.aembedding(model=self.model, input=texts)
        sorted_data = sorted(response.data, key=lambda x: x["index"])
        return [item["embedding"] for item in sorted_data]

    async def embed_many(
        self,
        id_text_pairs: list[tuple[str, str]],
        parallel: int = 10,
        progress_callback: Optional[Callable[[ProgressUpdate], None]] = None,
    ) -> list[tuple[str, list[float]]]:
        """Embed a list of (id, text) pairs. Returns list of (id, embedding)."""
        if not id_text_pairs:
            return []

        batches: list[list[tuple[str, str]]] = []
        for i in range(0, len(id_text_pairs), self.batch_size):
            batches.append(id_text_pairs[i : i + self.batch_size])

        semaphore = asyncio.Semaphore(parallel)
        completed = 0
        results: list[tuple[str, list[float]]] = []
        failed_batches: list[int] = []

        async def process_batch(batch_idx: int, batch: list[tuple[str, str]]):
            nonlocal completed
            async with semaphore:
                texts = [t for _, t in batch]
                ids = [i for i, _ in batch]
                for attempt in range(self.max_retries):
                    try:
                        embeddings = await self.embed_texts_batch(texts)
                        completed += 1
                        if progress_callback:
                            progress_callback(
                                ProgressUpdate(
                                    stage="embedding",
                                    current=completed,
                                    total=len(batches),
                                    message=f"Embedded batch {completed}/{len(batches)}",
                                )
                            )
                        return list(zip(ids, embeddings))
                    except Exception as e:
                        logger.warning(f"Batch {batch_idx} attempt {attempt+1} failed", error=str(e))
                        if attempt == self.max_retries - 1:
                            failed_batches.append(batch_idx)
                            return []
                        await asyncio.sleep(2**attempt)

        tasks = [process_batch(idx, batch) for idx, batch in enumerate(batches)]
        batch_results = await asyncio.gather(*tasks)

        for br in batch_results:
            if br:
                results.extend(br)

        if failed_batches:
            logger.warning("Some embedding batches failed", failed=failed_batches)

        return results
