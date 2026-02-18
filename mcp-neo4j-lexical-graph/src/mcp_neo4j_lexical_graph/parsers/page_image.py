"""Page-image parser using PyMuPDF.

Renders each page as an image and also extracts text.
Creates only Document + Page nodes (no Elements).
Page nodes carry both text and imageBase64 properties.
Optimised for slides / visual content destined for VLM entity extraction.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
import structlog

from ..models import ParsedDocument, ParsedPage
from .base import BaseParser

logger = structlog.get_logger()


class PageImageParser(BaseParser):
    """Extract text + render page images using PyMuPDF.

    Produces only Document and Page nodes -- no Elements.
    Each Page carries the full page text and a rendered PNG image.
    """

    def parse(
        self,
        pdf_path: str,
        source_id: str,
        version: int = 1,
        metadata: dict[str, Any] | None = None,
        *,
        dpi: int = 150,
        **kwargs: Any,
    ) -> ParsedDocument:
        path = Path(pdf_path)
        if not path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        doc_id = f"{source_id}_v{version}"
        logger.info("PageImageParser: parsing", pdf_path=pdf_path, doc_id=doc_id)

        doc = fitz.open(pdf_path)
        pages: list[ParsedPage] = []

        for page_idx in range(len(doc)):
            page = doc[page_idx]
            text = page.get_text("text").strip()
            rect = page.rect

            # Render page image
            pix = page.get_pixmap(dpi=dpi)
            png_bytes = pix.tobytes("png")
            image_b64 = base64.b64encode(png_bytes).decode("ascii")

            parsed_page = ParsedPage(
                page_number=page_idx,
                width=float(rect.width),
                height=float(rect.height),
                text=text if text else None,
                image_base64=image_b64,
                image_mime_type="image/png",
                element_ids=[],
            )
            pages.append(parsed_page)

        doc.close()

        parsed = ParsedDocument(
            id=doc_id,
            source_id=source_id,
            version=version,
            name=path.stem,
            source=str(path.resolve()),
            parse_mode="page_image",
            parse_params={"dpi": dpi},
            metadata=metadata or {},
            pages=pages,
            elements=[],
            sections=[],
        )

        logger.info(
            "PageImageParser: done",
            doc_id=doc_id,
            pages=len(pages),
        )
        return parsed
