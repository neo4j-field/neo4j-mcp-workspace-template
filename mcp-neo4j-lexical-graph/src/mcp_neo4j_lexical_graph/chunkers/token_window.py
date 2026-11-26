"""Token-window chunker.

Reads Elements from Neo4j in reading order, concatenates text,
then splits by token count with overlap. Simple and predictable.
"""

from __future__ import annotations

from typing import Any

import tiktoken
import structlog
from neo4j import AsyncDriver

from ..graph_reader import get_elements_for_document
from .base import BaseChunker, ChunkData, strip_base64_from_text, attach_source_locators

logger = structlog.get_logger()

DEFAULT_ENCODING = "cl100k_base"


class TokenWindowChunker(BaseChunker):
    """Sliding-window token chunker -- no structure awareness."""

    def __init__(
        self,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        encoding_name: str = DEFAULT_ENCODING,
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.encoding = tiktoken.get_encoding(encoding_name)

    async def create_chunks(
        self,
        driver: AsyncDriver,
        database: str,
        document_id: str,
        *,
        include_tables_as_chunks: bool = True,
        include_images_as_chunks: bool = True,
        prepend_section_heading: bool = True,
        **kwargs: Any,
    ) -> list[ChunkData]:
        elements = await get_elements_for_document(driver, database, document_id)
        if not elements:
            return []

        # Separate special elements if they should be their own chunks
        special_chunks: list[ChunkData] = []
        text_elements: list[dict[str, Any]] = []

        for e in elements:
            etype = e.get("type", "paragraph")
            etext = e.get("text") or ""

            if etype == "table" and include_tables_as_chunks and etext.strip():
                clean_text = strip_base64_from_text(etext)
                special_chunks.append(
                    ChunkData(
                        id="",
                        text=clean_text or etext,
                        index=-1,
                        token_count=len(self.encoding.encode(clean_text or etext)),
                        type="table",
                        element_ids=[e["id"]],
                        image_base64=e.get("imageBase64") or "",
                        image_mime_type=e.get("imageMimeType") or "",
                        text_as_html=e.get("textAsHtml") or "",
                    )
                )
            elif etype == "image" and include_images_as_chunks and etext.strip():
                clean_text = strip_base64_from_text(etext)
                special_chunks.append(
                    ChunkData(
                        id="",
                        text=clean_text or etext,
                        index=-1,
                        token_count=len(self.encoding.encode(clean_text or etext)),
                        type="image",
                        element_ids=[e["id"]],
                        image_base64=e.get("imageBase64") or "",
                        image_mime_type=e.get("imageMimeType") or "",
                        text_as_html=e.get("textAsHtml") or "",
                    )
                )
            else:
                if etext.strip():
                    text_elements.append(e)

        # Concatenate text elements
        full_text = "\n\n".join(e.get("text", "") for e in text_elements)
        tokens = self.encoding.encode(full_text)
        total_tokens = len(tokens)
        # Map token windows back to original elements using UTF-8 byte spans.
        # Encoding each element separately would shift token boundaries at joins.
        spans = []
        byte_offset = 0
        for index, element in enumerate(text_elements):
            if index:
                byte_offset += len("\n\n".encode("utf-8"))
            end = byte_offset + len(element["text"].encode("utf-8"))
            spans.append((byte_offset, end, element["id"]))
            byte_offset = end
        text_bytes = full_text.encode("utf-8")

        def character_boundary(offset: int) -> int:
            # Individual BPE tokens can end inside a Unicode codepoint. Adjacent
            # zero-overlap windows must use the same character boundary so text
            # is neither replaced by U+FFFD nor lost during reconstruction.
            while offset < len(text_bytes) and text_bytes[offset] & 0xC0 == 0x80:
                offset += 1
            return offset

        token_offsets = [0]
        for token in tokens:
            token_offsets.append(
                token_offsets[-1] + len(self.encoding.decode_single_token_bytes(token))
            )

        text_chunks: list[ChunkData] = []
        token_start = 0
        while token_start < total_tokens:
            token_end = min(token_start + self.chunk_size, total_tokens)
            byte_start = character_boundary(token_offsets[token_start])
            byte_end = character_boundary(token_offsets[token_end])
            chunk_text = text_bytes[byte_start:byte_end].decode("utf-8")

            if chunk_text:
                text_chunks.append(
                    ChunkData(
                        id="",
                        text=chunk_text,
                        index=-1,
                        token_count=len(self.encoding.encode(chunk_text)),
                        type="text",
                        element_ids=[
                            eid
                            for start, end, eid in spans
                            if start < byte_end and end > byte_start
                        ],
                    )
                )

            step = self.chunk_size - self.chunk_overlap
            next_start = token_start + step
            if next_start >= total_tokens or next_start <= token_start:
                break
            token_start = next_start

        # Merge and assign indices
        all_chunks = text_chunks + special_chunks
        attach_source_locators(all_chunks, elements)
        for idx, c in enumerate(all_chunks):
            c.index = idx
            c.id = f"{document_id}_chunk_{idx:04d}"

        logger.info(
            "TokenWindowChunker: done",
            document_id=document_id,
            text_chunks=len(text_chunks),
            special_chunks=len(special_chunks),
        )
        return all_chunks
