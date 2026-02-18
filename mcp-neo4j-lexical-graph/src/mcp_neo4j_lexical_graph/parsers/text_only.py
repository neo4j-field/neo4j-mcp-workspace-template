"""Text-only parser using PyMuPDF.

Fast, zero API cost. Produces one Element per page (type='paragraph').
No sections, no bounding boxes. Good for simple text PDFs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
import structlog

from ..models import ParsedDocument, ParsedElement, ParsedPage
from .base import BaseParser

logger = structlog.get_logger()


class TextOnlyParser(BaseParser):
    """Extract text from PDFs using PyMuPDF -- one Element per page."""

    def parse(
        self,
        pdf_path: str,
        source_id: str,
        version: int = 1,
        metadata: dict[str, Any] | None = None,
        *,
        store_page_images: bool = False,
        dpi: int = 150,
        **kwargs: Any,
    ) -> ParsedDocument:
        path = Path(pdf_path)
        if not path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        doc_id = f"{source_id}_v{version}"
        logger.info("TextOnlyParser: parsing", pdf_path=pdf_path, doc_id=doc_id)

        doc = fitz.open(pdf_path)
        pages: list[ParsedPage] = []
        elements: list[ParsedElement] = []

        for page_idx in range(len(doc)):
            page = doc[page_idx]
            text = page.get_text("text").strip()
            rect = page.rect

            element_id = f"{doc_id}_elem_p{page_idx}"

            # Build element
            element = ParsedElement(
                id=element_id,
                type="paragraph",
                text=text if text else None,
                page_number=page_idx,
            )
            elements.append(element)

            # Build page
            page_image_b64: str | None = None
            page_mime: str | None = None
            if store_page_images:
                pix = page.get_pixmap(dpi=dpi)
                page_image_b64 = _pixmap_to_base64(pix)
                page_mime = "image/png"

            parsed_page = ParsedPage(
                page_number=page_idx,
                width=float(rect.width),
                height=float(rect.height),
                text=text if text else None,
                image_base64=page_image_b64,
                image_mime_type=page_mime,
                element_ids=[element_id],
            )
            pages.append(parsed_page)

        doc.close()

        parsed = ParsedDocument(
            id=doc_id,
            source_id=source_id,
            version=version,
            name=path.stem,
            source=str(path.resolve()),
            parse_mode="text_only",
            parse_params={
                "store_page_images": store_page_images,
                "dpi": dpi,
            },
            metadata=metadata or {},
            pages=pages,
            elements=elements,
            sections=[],
            toc_entries=[],
        )

        logger.info(
            "TextOnlyParser: done",
            doc_id=doc_id,
            pages=len(pages),
            elements=len(elements),
        )
        return parsed


def _pixmap_to_base64(pix: fitz.Pixmap) -> str:
    """Convert a PyMuPDF Pixmap to a base64-encoded PNG string."""
    import base64

    png_bytes = pix.tobytes("png")
    return base64.b64encode(png_bytes).decode("ascii")
