"""By-page chunker -- one chunk per page.

Aggregates all Element texts on a page. Works with any parse mode.
"""

from __future__ import annotations

from typing import Any

import tiktoken
import structlog
from neo4j import AsyncDriver

from ..graph_reader import get_elements_for_document, get_pages_for_document
from .base import BaseChunker, ChunkData, strip_base64_from_text

logger = structlog.get_logger()

DEFAULT_ENCODING = "cl100k_base"


class ByPageChunker(BaseChunker):
    """One chunk per page."""

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
        pages = await get_pages_for_document(driver, database, document_id)

        if not elements or not pages:
            return []

        elem_by_id = {e["id"]: e for e in elements}
        chunks: list[ChunkData] = []

        for page in pages:
            page_num = page["pageNumber"]
            eids = page.get("elementIds") or []
            texts: list[str] = []
            chunk_eids: list[str] = []

            for eid in eids:
                e = elem_by_id.get(eid)
                if not e:
                    continue
                etext = (e.get("text") or "").strip()
                etype = e.get("type", "paragraph")

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
                full_text = "\n\n".join(texts)
                chunks.append(
                    ChunkData(
                        id="", text=full_text, index=-1,
                        token_count=len(self.encoding.encode(full_text)),
                        type="text", element_ids=chunk_eids,
                    )
                )

        for idx, c in enumerate(chunks):
            c.index = idx
            c.id = f"{document_id}_chunk_{idx:04d}"

        logger.info("ByPageChunker: done", document_id=document_id, chunks=len(chunks))
        return chunks
