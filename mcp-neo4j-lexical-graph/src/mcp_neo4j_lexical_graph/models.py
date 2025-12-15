"""Pydantic models for the lexical graph.

Core Lexical Data Model:
- Document: Top-level container for source documents
- Chunk: Text segments with embeddings for retrieval
"""

from typing import Optional
from pydantic import BaseModel, Field


class Chunk(BaseModel):
    """A text chunk from a document.
    
    Chunks are the atomic units for retrieval and entity extraction.
    They are connected via NEXT relationships to preserve document order.
    """
    id: str = Field(..., description="Unique chunk identifier (document_id + index)")
    text: str = Field(..., description="The text content of the chunk")
    index: int = Field(..., description="Position in document (0-based)")
    start_char: int = Field(..., description="Start character position in original text")
    end_char: int = Field(..., description="End character position in original text")
    token_count: int = Field(..., description="Number of tokens in chunk")
    embedding: Optional[list[float]] = Field(None, description="Vector embedding of text")
    
    def to_neo4j_properties(self) -> dict:
        """Convert to Neo4j node properties (excluding embedding for separate handling)."""
        return {
            "id": self.id,
            "text": self.text,
            "index": self.index,
            "startChar": self.start_char,
            "endChar": self.end_char,
            "tokenCount": self.token_count,
        }


class Document(BaseModel):
    """A source document in the lexical graph.
    
    Documents are the top-level containers that hold chunks.
    """
    id: str = Field(..., description="Unique document identifier")
    name: str = Field(..., description="Human-readable document name")
    source: str = Field(..., description="Source path or URL of the document")
    total_chunks: Optional[int] = Field(None, description="Total number of chunks")
    total_tokens: Optional[int] = Field(None, description="Total tokens across all chunks")
    
    def to_neo4j_properties(self) -> dict:
        """Convert to Neo4j node properties."""
        props = {
            "id": self.id,
            "name": self.name,
            "source": self.source,
        }
        if self.total_chunks is not None:
            props["totalChunks"] = self.total_chunks
        if self.total_tokens is not None:
            props["totalTokens"] = self.total_tokens
        return props


class ChunkingResult(BaseModel):
    """Result of processing a PDF into chunks."""
    document_id: str
    source_path: str
    total_pages: int
    total_characters: int
    total_tokens: int
    chunks: list[Chunk]
    
    def to_json(self) -> str:
        """Serialize to JSON for MCP transport."""
        return self.model_dump_json()


class ProgressUpdate(BaseModel):
    """Progress update for long-running operations."""
    stage: str = Field(..., description="Current processing stage")
    current: int = Field(..., description="Current item number")
    total: int = Field(..., description="Total items to process")
    message: str = Field(..., description="Human-readable status message")
    
    @property
    def percentage(self) -> float:
        return (self.current / self.total * 100) if self.total > 0 else 0

