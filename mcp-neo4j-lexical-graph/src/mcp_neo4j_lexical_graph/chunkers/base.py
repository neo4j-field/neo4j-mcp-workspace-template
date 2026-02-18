"""Base chunker interface.

All chunkers read Elements and Sections from Neo4j and create Chunk nodes.
They are completely decoupled from the parsing layer.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from neo4j import AsyncDriver

# Regex to detect inline base64 image markdown that may have leaked into element text
_BASE64_IMAGE_RE = re.compile(
    r"!\[(?:[^\]]*)\]\(data:image/[^;]+;base64,[A-Za-z0-9+/=\s]+\)",
    re.DOTALL,
)


def strip_base64_from_text(text: str) -> str:
    """Remove inline base64 image markdown from text.

    Safety net for chunkers: if element text contains embedded base64 images
    (e.g. from docling's export_to_markdown), strip them before counting tokens.
    Returns cleaned text or empty string if nothing remains.
    """
    return _BASE64_IMAGE_RE.sub("", text).strip()


@dataclass
class ChunkData:
    """A chunk to be written to Neo4j."""

    id: str
    text: str
    index: int
    token_count: int
    type: str = "text"  # text | table | image
    element_ids: list[str] = field(default_factory=list)
    document_name: str = ""
    section_heading: str = ""
    section_context: str = ""
    image_base64: str = ""
    image_mime_type: str = ""
    text_as_html: str = ""


class BaseChunker(ABC):
    """Abstract base for chunking strategies.

    Subclasses implement ``create_chunks`` which reads from Neo4j
    and returns a list of ChunkData objects ready to be written.
    """

    @abstractmethod
    async def create_chunks(
        self,
        driver: AsyncDriver,
        database: str,
        document_id: str,
        **kwargs: Any,
    ) -> list[ChunkData]:
        """Read Elements/Sections from Neo4j and produce chunks.

        Args:
            driver: Neo4j async driver.
            database: Neo4j database name.
            document_id: Document version id to chunk.
            **kwargs: Strategy-specific options.

        Returns:
            Ordered list of ChunkData objects.
        """
        ...
