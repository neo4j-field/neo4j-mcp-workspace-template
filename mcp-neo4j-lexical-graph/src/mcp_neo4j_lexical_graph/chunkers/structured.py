"""Structured chunker -- section-aware token window with element-boundary splitting.

Reads Elements and Sections from Neo4j in reading order (NEXT_ELEMENT chain).
Accumulates elements up to chunk_size tokens, using section boundaries as
preferred split points. Merges small sections into the next chunk rather
than creating undersized chunks.

Key rules:
- Split between elements, never mid-element (unless element > chunk_size)
- A heading element must never be the last element in a chunk
- Tables/images become their own chunks (with caption as context if available)
- Every chunk gets documentName, sectionHeading, sectionContext metadata
"""

from __future__ import annotations

from typing import Any

import tiktoken
import structlog
from neo4j import AsyncDriver

from ..graph_reader import (
    get_elements_for_document,
    get_sections_for_document,
    get_document,
)
from .base import BaseChunker, ChunkData, strip_base64_from_text

logger = structlog.get_logger()

DEFAULT_ENCODING = "cl100k_base"


class StructuredChunker(BaseChunker):
    """Section-aware token-window chunker with element-boundary splitting."""

    def __init__(
        self,
        chunk_size: int = 500,
        encoding_name: str = DEFAULT_ENCODING,
    ):
        self.chunk_size = chunk_size
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

        sections = await get_sections_for_document(driver, database, document_id)
        doc = await get_document(driver, database, document_id)
        doc_name = doc.get("name", document_id) if doc else document_id

        # Build element_id -> section heading lookup
        elem_to_heading: dict[str, str] = {}
        for s in sections:
            title = s.get("title", "")
            for eid in (s.get("elementIds") or []):
                elem_to_heading[eid] = title

        # Fetch captions: target_element_id -> caption_text
        captions = await self._get_captions(driver, database, document_id)

        # Identify special (table/image) element IDs
        skip_ids: set[str] = set()
        special_chunks: list[ChunkData] = []

        for e in elements:
            eid = e["id"]
            etype = e.get("type", "paragraph")
            etext = (e.get("text") or "").strip()

            if etype == "table" and include_tables_as_chunks:
                clean = strip_base64_from_text(etext) if etext else ""
                text = clean or etext or ""
                caption_text = captions.get(eid, "")
                heading = elem_to_heading.get(eid, "")
                special_chunks.append(
                    ChunkData(
                        id="",
                        text=text,
                        index=-1,
                        token_count=len(self.encoding.encode(text)) if text else 0,
                        type="table",
                        element_ids=[eid],
                        document_name=doc_name,
                        section_heading=heading,
                        section_context=caption_text or heading,
                        image_base64=e.get("imageBase64") or "",
                        image_mime_type=e.get("imageMimeType") or "",
                        text_as_html=e.get("textAsHtml") or "",
                    )
                )
                skip_ids.add(eid)
            elif etype == "image" and include_images_as_chunks:
                clean = strip_base64_from_text(etext) if etext else ""
                text = clean or etext or ""
                caption_text = captions.get(eid, "")
                heading = elem_to_heading.get(eid, "")
                special_chunks.append(
                    ChunkData(
                        id="",
                        text=text,
                        index=-1,
                        token_count=len(self.encoding.encode(text)) if text else 0,
                        type="image",
                        element_ids=[eid],
                        document_name=doc_name,
                        section_heading=heading,
                        section_context=caption_text or heading,
                        image_base64=e.get("imageBase64") or "",
                        image_mime_type=e.get("imageMimeType") or "",
                        text_as_html=e.get("textAsHtml") or "",
                    )
                )
                skip_ids.add(eid)

        # Walk elements in reading order, accumulate into chunks
        text_chunks: list[ChunkData] = []

        # Accumulator state
        acc_texts: list[str] = []
        acc_tokens: int = 0
        acc_eids: list[str] = []
        acc_heading: str = ""  # heading active when this chunk started
        current_heading: str = ""  # most recent heading seen

        def _flush() -> None:
            """Emit the current accumulator as a chunk."""
            nonlocal acc_texts, acc_tokens, acc_eids, acc_heading
            if not acc_texts:
                return
            chunk_text = "\n\n".join(acc_texts)
            text_chunks.append(
                ChunkData(
                    id="",
                    text=chunk_text,
                    index=-1,
                    token_count=len(self.encoding.encode(chunk_text)),
                    type="text",
                    element_ids=list(acc_eids),
                    document_name=doc_name,
                    section_heading=acc_heading,
                    section_context=acc_heading,
                )
            )
            acc_texts = []
            acc_tokens = 0
            acc_eids = []

        for e in elements:
            eid = e["id"]
            if eid in skip_ids:
                continue

            etype = e.get("type", "paragraph")
            etext = (e.get("text") or "").strip()
            if not etext:
                continue

            is_heading = etype == "heading"
            elem_tokens = len(self.encoding.encode(etext))

            # Update current heading tracker
            if is_heading:
                current_heading = etext

            # If this is a heading and we have accumulated enough content,
            # flush to start a new chunk at this section boundary.
            # Only flush if we're past half the target size -- otherwise
            # merge small sections together to avoid tiny chunks.
            min_flush_tokens = self.chunk_size // 2
            if is_heading and acc_texts and acc_tokens >= min_flush_tokens:
                _flush()

            # Set the heading for the chunk if accumulator is empty
            if not acc_texts:
                acc_heading = current_heading

            # Single element exceeds chunk_size: flush current, emit oversized as its own chunk
            if elem_tokens > self.chunk_size:
                _flush()
                acc_heading = current_heading
                text_chunks.append(
                    ChunkData(
                        id="",
                        text=etext,
                        index=-1,
                        token_count=elem_tokens,
                        type="text",
                        element_ids=[eid],
                        document_name=doc_name,
                        section_heading=current_heading,
                        section_context=current_heading,
                    )
                )
                continue

            # Would adding this element exceed chunk_size?
            if acc_tokens + elem_tokens > self.chunk_size and acc_texts:
                # Check: is the last accumulated element a heading?
                # If so, pop it and carry it over to the next chunk
                if len(acc_texts) > 1 and acc_eids:
                    last_eid = acc_eids[-1]
                    last_elem = next((x for x in elements if x["id"] == last_eid), None)
                    if last_elem and last_elem.get("type") == "heading":
                        # Pop the trailing heading
                        popped_text = acc_texts.pop()
                        popped_eid = acc_eids.pop()
                        popped_tokens = len(self.encoding.encode(popped_text))
                        acc_tokens -= popped_tokens
                        _flush()
                        # Start new chunk with the popped heading
                        acc_heading = popped_text
                        current_heading = popped_text
                        acc_texts = [popped_text]
                        acc_tokens = popped_tokens
                        acc_eids = [popped_eid]
                    else:
                        _flush()
                        acc_heading = current_heading
                else:
                    _flush()
                    acc_heading = current_heading

            acc_texts.append(etext)
            acc_tokens += elem_tokens
            acc_eids.append(eid)

        # Flush any remaining content
        _flush()

        # Interleave special chunks at the end (they have their own context)
        all_chunks = text_chunks + special_chunks
        for idx, c in enumerate(all_chunks):
            c.index = idx
            c.id = f"{document_id}_chunk_{idx:04d}"

        logger.info(
            "StructuredChunker: done",
            document_id=document_id,
            text_chunks=len(text_chunks),
            special_chunks=len(special_chunks),
        )
        return all_chunks

    async def _get_captions(
        self,
        driver: AsyncDriver,
        database: str,
        document_id: str,
    ) -> dict[str, str]:
        """Fetch caption text for table/figure elements via CAPTION_OF relationships."""
        query = """
            MATCH (caption:Element)-[:CAPTION_OF]->(target:Element)
            WHERE caption.id STARTS WITH $prefix
            RETURN target.id AS targetId, caption.text AS captionText
        """
        async with driver.session(database=database) as session:
            result = await session.run(query, prefix=document_id)
            rows = await result.data()
        return {r["targetId"]: (r.get("captionText") or "") for r in rows}
