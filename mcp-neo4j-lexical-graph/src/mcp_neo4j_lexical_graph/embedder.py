"""Embedding module using LiteLLM.

Supports 100+ embedding providers through LiteLLM abstraction.
Includes parallelized batch embedding with progress tracking.
"""

import asyncio
from typing import Optional, Callable

import litellm
import structlog

from .models import Chunk, ProgressUpdate

logger = structlog.get_logger()

# Default embedding model
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"


class ChunkEmbedder:
    """Generate embeddings for text chunks using LiteLLM.
    
    Features:
    - Supports 100+ embedding providers via LiteLLM
    - Parallelized batch processing with semaphore
    - Progress callbacks for long-running operations
    - Retry logic for failed embeddings
    
    Example:
        >>> embedder = ChunkEmbedder(model="text-embedding-3-small")
        >>> chunks = await embedder.embed_chunks(chunks, parallel=10)
    """
    
    def __init__(
        self,
        model: str = DEFAULT_EMBEDDING_MODEL,
        batch_size: int = 100,
        max_retries: int = 3
    ):
        """Initialize the embedder.
        
        Args:
            model: LiteLLM embedding model identifier
            batch_size: Number of texts to embed per API call
            max_retries: Maximum retries for failed batches
        """
        self.model = model
        self.batch_size = batch_size
        self.max_retries = max_retries
        
        logger.info(
            "ChunkEmbedder initialized",
            model=model,
            batch_size=batch_size
        )
    
    async def embed_text(self, text: str) -> list[float]:
        """Embed a single text string.
        
        Args:
            text: Text to embed
            
        Returns:
            Embedding vector as list of floats
        """
        response = await litellm.aembedding(
            model=self.model,
            input=[text]
        )
        return response.data[0]["embedding"]
    
    async def embed_texts_batch(
        self,
        texts: list[str]
    ) -> list[list[float]]:
        """Embed multiple texts in a single API call.
        
        Args:
            texts: List of texts to embed
            
        Returns:
            List of embedding vectors
        """
        if not texts:
            return []
        
        response = await litellm.aembedding(
            model=self.model,
            input=texts
        )
        
        # Sort by index to maintain order
        sorted_data = sorted(response.data, key=lambda x: x["index"])
        return [item["embedding"] for item in sorted_data]
    
    async def embed_chunks(
        self,
        chunks: list[Chunk],
        parallel: int = 10,
        progress_callback: Optional[Callable[[ProgressUpdate], None]] = None
    ) -> list[Chunk]:
        """Embed all chunks with parallelized batch processing.
        
        Args:
            chunks: List of chunks to embed
            parallel: Maximum concurrent embedding batches
            progress_callback: Optional callback for progress updates
            
        Returns:
            Chunks with embeddings populated
        """
        if not chunks:
            return []
        
        total_chunks = len(chunks)
        logger.info(
            "Starting chunk embedding",
            total_chunks=total_chunks,
            model=self.model,
            parallel=parallel,
            batch_size=self.batch_size
        )
        
        # Create batches
        batches = []
        for i in range(0, total_chunks, self.batch_size):
            batch = chunks[i:i + self.batch_size]
            batches.append((i, batch))
        
        total_batches = len(batches)
        semaphore = asyncio.Semaphore(parallel)
        completed = 0
        failed_batches = []
        
        async def process_batch(batch_idx: int, batch: list[Chunk]) -> list[tuple[int, list[float]]]:
            """Process a single batch with semaphore control."""
            nonlocal completed
            
            async with semaphore:
                texts = [chunk.text for chunk in batch]
                
                for attempt in range(self.max_retries):
                    try:
                        embeddings = await self.embed_texts_batch(texts)
                        
                        completed += 1
                        if progress_callback:
                            progress_callback(ProgressUpdate(
                                stage="embedding",
                                current=completed,
                                total=total_batches,
                                message=f"Embedded batch {completed}/{total_batches}"
                            ))
                        
                        logger.debug(
                            f"Batch {batch_idx // self.batch_size + 1} embedded",
                            chunks=len(batch)
                        )
                        
                        # Return chunk indices with their embeddings
                        return [(batch_idx + i, emb) for i, emb in enumerate(embeddings)]
                        
                    except Exception as e:
                        logger.warning(
                            f"Batch embedding attempt {attempt + 1} failed",
                            error=str(e)
                        )
                        if attempt == self.max_retries - 1:
                            failed_batches.append(batch_idx)
                            return []
                        await asyncio.sleep(2 ** attempt)  # Exponential backoff
        
        # Process all batches in parallel
        tasks = [process_batch(idx, batch) for idx, batch in batches]
        results = await asyncio.gather(*tasks)
        
        # Flatten results and update chunks
        embedding_map = {}
        for batch_results in results:
            for chunk_idx, embedding in batch_results:
                embedding_map[chunk_idx] = embedding
        
        # Update chunks with embeddings
        embedded_chunks = []
        for i, chunk in enumerate(chunks):
            if i in embedding_map:
                chunk.embedding = embedding_map[i]
            embedded_chunks.append(chunk)
        
        # Log summary
        embedded_count = sum(1 for c in embedded_chunks if c.embedding is not None)
        logger.info(
            "Chunk embedding completed",
            total=total_chunks,
            embedded=embedded_count,
            failed_batches=len(failed_batches)
        )
        
        if failed_batches:
            logger.warning(
                "Some batches failed",
                failed_batch_indices=failed_batches
            )
        
        return embedded_chunks


# Convenience function
async def embed_chunks(
    chunks: list[Chunk],
    model: str = DEFAULT_EMBEDDING_MODEL,
    parallel: int = 10,
    progress_callback: Optional[Callable[[ProgressUpdate], None]] = None
) -> list[Chunk]:
    """Embed chunks with the specified model.
    
    Convenience function that creates an embedder and processes chunks.
    
    Args:
        chunks: List of chunks to embed
        model: Embedding model identifier
        parallel: Maximum concurrent batches
        progress_callback: Optional progress callback
        
    Returns:
        Chunks with embeddings populated
    """
    embedder = ChunkEmbedder(model=model)
    return await embedder.embed_chunks(chunks, parallel=parallel, progress_callback=progress_callback)

