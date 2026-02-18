"""By-section chunker -- one chunk per section.

Aggregates all Element texts within a section. Chunks may exceed chunk_size.
Falls back to by_page if no sections exist.
"""

from __future__ import annotations

from typing import Any

import tiktoken
import structlog
from neo4j import AsyncDriver

from ..graph_reader import get_elements_for_document, get_sections_for_document
from .base import BaseChunker, ChunkData, strip_base64_from_text

logger = structlog.get_logger()

DEFAULT_ENCODING = "cl100k_base"


class BySectionChunker(BaseChunker):
    """One chunk per section."""

    def __init__(self, encoding_name: str = DEFAULT_ENCODING):
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
        sections = await get_sections_for_document(driver, database, document_id)

        if not elements:
            return []

        elem_by_id = {e["id"]: e for e in elements}
        chunks: list[ChunkData] = []
        assigned_eids: set[str] = set()

        if not sections:
            logger.warning(
                "BySectionChunker: no sections found, falling back to by_page",
                document_id=document_id,
            )
            from .by_page import ByPageChunker

            fallback = ByPageChunker()
            return await fallback.create_chunks(
                driver, database, document_id,
                include_tables_as_chunks=include_tables_as_chunks,
                include_images_as_chunks=include_images_as_chunks,
                prepend_section_heading=prepend_section_heading,
            )

        for s in sections:
            heading = s.get("title", "")
            eids = s.get("elementIds") or []
            texts: list[str] = []
            chunk_eids: list[str] = []

            for eid in eids:
                assigned_eids.add(eid)
                e = elem_by_id.get(eid)
                if not e:
                    continue
                etext = (e.get("text") or "").strip()
                etype = e.get("type", "paragraph")

                # Special elements as separate chunks
                if etype == "table" and include_tables_as_chunks and etext:
                    clean_text = strip_base64_from_text(etext)
                    chunks.append(
                        ChunkData(
                            id="", text=clean_text or etext, index=-1,
                            token_count=len(self.encoding.encode(clean_text or etext)),
                            type="table", element_ids=[eid],
                            image_base64=e.get("imageBase64") or "",
                            image_mime_type=e.get("imageMimeType") or "",
                            text_as_html=e.get("textAsHtml") or "",
                        )
                    )
                    continue
                if etype == "image" and include_images_as_chunks and etext:
                    clean_text = strip_base64_from_text(etext)
                    chunks.append(
                        ChunkData(
                            id="", text=clean_text or etext, index=-1,
                            token_count=len(self.encoding.encode(clean_text or etext)),
                            type="image", element_ids=[eid],
                            image_base64=e.get("imageBase64") or "",
                            image_mime_type=e.get("imageMimeType") or "",
                            text_as_html=e.get("textAsHtml") or "",
                        )
                    )
                    continue

                if etext:
                    texts.append(etext)
                    chunk_eids.append(eid)

            if texts:
                full_text = "\n\n".join(
                    ([heading] if heading and prepend_section_heading else []) + texts
                )
                chunks.append(
                    ChunkData(
                        id="", text=full_text, index=-1,
                        token_count=len(self.encoding.encode(full_text)),
                        type="text", element_ids=chunk_eids,
                    )
                )

        # Handle unassigned elements
        unassigned_texts: list[str] = []
        unassigned_eids: list[str] = []
        for e in elements:
            if e["id"] not in assigned_eids:
                etext = (e.get("text") or "").strip()
                if etext:
                    unassigned_texts.append(etext)
                    unassigned_eids.append(e["id"])
        if unassigned_texts:
            full_text = "\n\n".join(unassigned_texts)
            chunks.append(
                ChunkData(
                    id="", text=full_text, index=-1,
                    token_count=len(self.encoding.encode(full_text)),
                    type="text", element_ids=unassigned_eids,
                )
            )

        for idx, c in enumerate(chunks):
            c.index = idx
            c.id = f"{document_id}_chunk_{idx:04d}"

        logger.info("BySectionChunker: done", document_id=document_id, chunks=len(chunks))
        return chunks
