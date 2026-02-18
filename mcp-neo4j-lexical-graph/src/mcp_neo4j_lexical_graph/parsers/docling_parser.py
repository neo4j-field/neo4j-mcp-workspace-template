"""Docling parser -- full layout analysis for complex PDFs.

Uses the Docling DocumentConverter for:
- Fine-grained element extraction (paragraphs, headings, tables, figures, captions)
- Section hierarchy from headings
- Table HTML representation
- Image extraction for figures and tables
- Bounding boxes
- Caption linking (CAPTION_OF)
- TOCEntry extraction from DOCUMENT_INDEX items
- Furniture filtering (headers, footers, page numbers)

Requires the `docling` extra: pip install 'mcp-neo4j-lexical-graph-v2[docling]'
"""

from __future__ import annotations

import base64
import io
import re
from pathlib import Path
from typing import Any

import structlog

from ..models import (
    ParsedDocument,
    ParsedElement,
    ParsedPage,
    ParsedSection,
)
from .base import BaseParser

logger = structlog.get_logger()

# Map docling labels to our element types
_LABEL_MAP: dict[str, str] = {
    "title": "heading",
    "section_header": "heading",
    "text": "paragraph",
    "paragraph": "paragraph",
    "list_item": "list_item",
    "table": "table",
    "picture": "image",
    "figure": "image",
    "chart": "image",
    "caption": "caption",
    "formula": "formula",
    "code": "code",
    "footnote": "footnote",
    "page_header": "page_header",
    "page_footer": "page_footer",
    "document_index": "table_of_contents",
    "checkbox_selected": "paragraph",
    "checkbox_unselected": "paragraph",
    "reference": "footnote",
}

_FURNITURE_TYPES = {"page_header", "page_footer"}


class DoclingParser(BaseParser):
    """Parse PDFs using Docling for full layout analysis."""

    def parse(
        self,
        pdf_path: str,
        source_id: str,
        version: int = 1,
        metadata: dict[str, Any] | None = None,
        *,
        skip_furniture: bool = True,
        exclude_element_types: list[str] | None = None,
        extract_sections: bool = True,
        extract_toc: bool = True,
        store_page_images: bool = False,
        dpi: int = 150,
        **kwargs: Any,
    ) -> ParsedDocument:
        try:
            from docling.document_converter import DocumentConverter, PdfFormatOption
            from docling.datamodel.pipeline_options import PdfPipelineOptions
            from docling.datamodel.base_models import InputFormat
        except ImportError:
            raise ImportError(
                "docling is not installed. Install with: "
                "pip install 'mcp-neo4j-lexical-graph-v2[docling]'"
            )

        path = Path(pdf_path)
        if not path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        doc_id = f"{source_id}_v{version}"
        logger.info("DoclingParser: parsing", pdf_path=pdf_path, doc_id=doc_id)

        # Configure pipeline with image generation for figures and tables
        pipeline_options = PdfPipelineOptions()
        pipeline_options.images_scale = dpi / 72.0
        pipeline_options.generate_picture_images = True
        try:
            pipeline_options.generate_table_images = True
        except AttributeError:
            pass  # older docling versions may not have this

        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
            }
        )
        conv_result = converter.convert(str(path))
        docling_doc = conv_result.document

        exclude_set = set(exclude_element_types or [])

        # Collect page info from PyMuPDF for dimensions and optional images
        import fitz

        fitz_doc = fitz.open(pdf_path)
        page_infos: dict[int, dict[str, Any]] = {}
        for page_idx in range(len(fitz_doc)):
            page = fitz_doc[page_idx]
            rect = page.rect
            info: dict[str, Any] = {
                "width": float(rect.width),
                "height": float(rect.height),
            }
            if store_page_images:
                pix = page.get_pixmap(dpi=dpi)
                info["image_base64"] = base64.b64encode(pix.tobytes("png")).decode("ascii")
                info["image_mime_type"] = "image/png"
            page_infos[page_idx] = info

        # --- Iterate docling items and build our intermediate structures ---
        elements: list[ParsedElement] = []
        sections: list[ParsedSection] = []
        page_element_ids: dict[int, list[str]] = {}  # page_num -> [element_ids]

        # Track headings for section building
        heading_stack: list[ParsedSection] = []  # stack of current sections
        elem_counter = 0

        # Iterate over all items in reading order
        for item, _level in docling_doc.iterate_items():
            label_str = item.label.value if hasattr(item.label, "value") else str(item.label)
            our_type = _LABEL_MAP.get(label_str.lower(), "paragraph")

            # Skip furniture if requested
            if skip_furniture and our_type in _FURNITURE_TYPES:
                continue

            # Skip excluded types
            if our_type in exclude_set:
                continue

            # Get element properties
            elem_id = f"{doc_id}_elem_{elem_counter}"
            elem_counter += 1

            text = _get_item_text(item, docling_doc)
            text_as_html = None
            image_b64 = None
            image_mime = None
            coords = _get_item_bbox(item)
            level = None
            page_num = _get_item_page(item) or 0

            # Type-specific processing
            if our_type == "heading":
                level = _get_heading_level(item, label_str, _level)
            elif our_type == "table":
                text_as_html = _get_table_html(item, docling_doc)
                image_b64, image_mime = _get_item_image(
                    item, docling_doc, coords, page_num, pdf_path, dpi, fitz_doc
                )
            elif our_type == "image":
                image_b64, image_mime = _get_item_image(
                    item, docling_doc, coords, page_num, pdf_path, dpi, fitz_doc
                )
                # Docling's export_to_markdown() embeds the full base64 image
                # in the text (e.g. "Fig. 1\n\n![Image](data:image/png;base64,...)").
                # Strip the base64 portion, keeping only the caption text.
                if text:
                    text = _strip_base64_from_text(text)

            element = ParsedElement(
                id=elem_id,
                type=our_type,
                text=text,
                text_as_html=text_as_html,
                image_base64=image_b64,
                image_mime_type=image_mime,
                coordinates=coords,
                level=level,
                page_number=page_num,
                caption_target_id=None,  # linked below
            )
            elements.append(element)
            page_element_ids.setdefault(page_num, []).append(elem_id)

            # Build sections from headings
            if our_type == "heading" and extract_sections and text:
                sec_id = f"{doc_id}_sec_{len(sections)}"
                section = ParsedSection(
                    id=sec_id,
                    title=text.strip(),
                    level=level or 1,
                    element_ids=[elem_id],
                )

                # Pop stack until we find a parent with lower level
                while heading_stack and heading_stack[-1].level >= (level or 1):
                    heading_stack.pop()

                if heading_stack:
                    heading_stack[-1].subsection_ids.append(sec_id)

                heading_stack.append(section)
                sections.append(section)
            elif extract_sections and heading_stack:
                # Add non-heading elements to current section
                heading_stack[-1].element_ids.append(elem_id)

        # Close fitz_doc now that we're done with image extraction
        fitz_doc.close()

        # --- Link captions to their targets ---
        _link_captions(elements)

        # --- Build pages ---
        total_pages = max(page_infos.keys(), default=-1) + 1
        if not total_pages and page_element_ids:
            total_pages = max(page_element_ids.keys(), default=-1) + 1

        pages: list[ParsedPage] = []
        for pn in range(total_pages):
            info = page_infos.get(pn, {})
            pages.append(
                ParsedPage(
                    page_number=pn,
                    width=info.get("width"),
                    height=info.get("height"),
                    text=None,  # docling mode doesn't store full page text
                    image_base64=info.get("image_base64"),
                    image_mime_type=info.get("image_mime_type"),
                    element_ids=page_element_ids.get(pn, []),
                )
            )

        parsed = ParsedDocument(
            id=doc_id,
            source_id=source_id,
            version=version,
            name=path.stem,
            source=str(path.resolve()),
            parse_mode="docling",
            parse_params={
                "skip_furniture": skip_furniture,
                "exclude_element_types": list(exclude_set),
                "extract_sections": extract_sections,
                "extract_toc": extract_toc,
                "store_page_images": store_page_images,
                "dpi": dpi,
            },
            metadata=metadata or {},
            pages=pages,
            elements=elements,
            sections=sections,
        )

        logger.info(
            "DoclingParser: done",
            doc_id=doc_id,
            pages=len(pages),
            elements=len(elements),
            sections=len(sections),
        )
        return parsed


# ---- Helper functions ----

_BASE64_IMAGE_RE = re.compile(
    r"!\[(?:[^\]]*)\]\(data:image/[^;]+;base64,[A-Za-z0-9+/=\s]+\)",
    re.DOTALL,
)


def _strip_base64_from_text(text: str) -> str:
    """Remove inline base64 image markdown from text, keeping only captions.

    Docling's export_to_markdown() for PictureItem produces text like:
        "Fig. 1\n\n![Image](data:image/png;base64,iVBOR...)"
    This strips the ![Image](data:...) portion and returns just "Fig. 1".
    """
    cleaned = _BASE64_IMAGE_RE.sub("", text).strip()
    return cleaned if cleaned else None


def _get_item_text(item: Any, docling_doc: Any = None) -> str | None:
    """Extract text from a docling item."""
    # TextItem has .text
    if hasattr(item, "text") and item.text:
        return item.text
    # TableItem has export_to_markdown(doc=...)
    if hasattr(item, "export_to_markdown"):
        try:
            if docling_doc is not None:
                return item.export_to_markdown(doc=docling_doc)
            return item.export_to_markdown()
        except TypeError:
            try:
                return item.export_to_markdown()
            except Exception:
                pass
        except Exception:
            pass
    return None


def _get_table_html(item: Any, docling_doc: Any = None) -> str | None:
    """Get HTML representation of a table item."""
    # Docling's export_to_html requires doc= parameter
    if hasattr(item, "export_to_html"):
        try:
            if docling_doc is not None:
                html = item.export_to_html(doc=docling_doc)
            else:
                html = item.export_to_html()
            if html and html.strip():
                return html
        except TypeError:
            try:
                html = item.export_to_html()
                if html and html.strip():
                    return html
            except Exception:
                pass
        except Exception as e:
            logger.debug(f"export_to_html failed: {e}")
    # Fallback: try dataframe -> HTML
    if hasattr(item, "export_to_dataframe"):
        try:
            if docling_doc is not None:
                df = item.export_to_dataframe(doc=docling_doc)
            else:
                df = item.export_to_dataframe()
            if df is not None and not df.empty:
                return df.to_html(index=False)
        except TypeError:
            try:
                df = item.export_to_dataframe()
                if df is not None and not df.empty:
                    return df.to_html(index=False)
            except Exception:
                pass
        except Exception as e:
            logger.debug(f"export_to_dataframe failed: {e}")
    return None


def _get_item_page(item: Any) -> int | None:
    """Get the 0-based page number from a docling item."""
    if hasattr(item, "prov") and item.prov:
        for prov in item.prov:
            if hasattr(prov, "page_no"):
                return prov.page_no - 1  # docling is 1-based
    return None


def _get_item_bbox(item: Any) -> dict[str, float] | None:
    """Get bounding box from a docling item."""
    if hasattr(item, "prov") and item.prov:
        for prov in item.prov:
            if hasattr(prov, "bbox") and prov.bbox is not None:
                bbox = prov.bbox
                if hasattr(bbox, "l"):
                    return {
                        "x0": float(bbox.l),
                        "y0": float(bbox.t),
                        "x1": float(bbox.r),
                        "y1": float(bbox.b),
                    }
    return None


def _get_heading_level(item: Any, label_str: str, tree_level: int = 0) -> int:
    """Determine heading level from a docling item.

    Uses:
    1. label_str == "title" -> level 1
    2. item.level (docling SectionHeaderItem) if valid
    3. tree_level from iterate_items() as fallback
    """
    if label_str.lower() == "title":
        return 1
    # Try item's own level attribute (docling SectionHeaderItem has this)
    item_level = getattr(item, "level", None)
    if isinstance(item_level, int) and item_level > 0:
        return max(1, min(6, item_level))
    # Fall back to tree level from iterate_items()
    # tree_level 0 = top level (title/h1), 1 = h2, etc.
    return max(1, min(6, tree_level + 1))


def _get_item_image(
    item: Any,
    docling_doc: Any,
    coords: dict[str, float] | None,
    page_num: int,
    pdf_path: str,
    dpi: int,
    fitz_doc: Any = None,
) -> tuple[str | None, str | None]:
    """Extract image for a table/figure element.

    Strategy:
    1. Use docling's get_image(doc) method (requires generate_picture_images=True)
    2. Fall back to cropping from the PDF page using PyMuPDF and bounding box
    """
    # Method 1: Use docling's get_image (works for PictureItem and TableItem)
    if hasattr(item, "get_image") and docling_doc is not None:
        try:
            pil_img = item.get_image(docling_doc)
            if pil_img is not None:
                buf = io.BytesIO()
                pil_img.save(buf, format="PNG")
                b64 = base64.b64encode(buf.getvalue()).decode("ascii")
                return b64, "image/png"
        except Exception as e:
            logger.debug(f"docling get_image failed: {e}")

    # Method 2: Try docling's image property (data URI)
    if hasattr(item, "image") and item.image is not None:
        img = item.image
        # Try pil_image property
        try:
            pil_img = getattr(img, "pil_image", None)
            if pil_img is not None:
                buf = io.BytesIO()
                pil_img.save(buf, format="PNG")
                b64 = base64.b64encode(buf.getvalue()).decode("ascii")
                return b64, "image/png"
        except Exception as e:
            logger.debug(f"pil_image extraction failed: {e}")
        # Try data URI
        try:
            if hasattr(img, "uri") and img.uri:
                uri = str(img.uri)
                if uri.startswith("data:"):
                    parts = uri.split(",", 1)
                    if len(parts) == 2:
                        mime = parts[0].split(";")[0].replace("data:", "")
                        return parts[1], mime
        except Exception as e:
            logger.debug(f"data URI extraction failed: {e}")

    # Method 3: Crop from PDF using PyMuPDF and bounding box coordinates
    if coords and pdf_path:
        try:
            import fitz as fitz_lib

            # Use already-open document if available, otherwise open new one
            doc_to_close = None
            if fitz_doc is not None:
                doc = fitz_doc
            else:
                doc = fitz_lib.open(pdf_path)
                doc_to_close = doc

            try:
                page = doc[page_num]
                x0, y0, x1, y1 = coords["x0"], coords["y0"], coords["x1"], coords["y1"]

                # Ensure proper coordinate ordering
                if y0 > y1:
                    y0, y1 = y1, y0
                if x0 > x1:
                    x0, x1 = x1, x0

                # Clamp to page bounds
                page_w, page_h = page.rect.width, page.rect.height
                x0 = max(0, min(x0, page_w))
                x1 = max(0, min(x1, page_w))
                y0 = max(0, min(y0, page_h))
                y1 = max(0, min(y1, page_h))

                rect = fitz_lib.Rect(x0, y0, x1, y1)
                rect.normalize()

                if rect.is_empty or rect.width < 5 or rect.height < 5:
                    logger.debug(f"Rect too small for image crop: {rect}")
                    return None, None

                clip = page.get_pixmap(clip=rect, dpi=dpi)
                b64 = base64.b64encode(clip.tobytes("png")).decode("ascii")
                return b64, "image/png"
            finally:
                if doc_to_close is not None:
                    doc_to_close.close()
        except Exception as e:
            logger.warning(f"Could not crop image from page {page_num}: {e}")

    return None, None


def _link_captions(elements: list[ParsedElement]) -> None:
    """Link caption elements to their nearest table/figure target."""
    caption_indices = [
        i for i, e in enumerate(elements) if e.type == "caption"
    ]
    target_indices = [
        i for i, e in enumerate(elements) if e.type in ("table", "image")
    ]

    for ci in caption_indices:
        # Find the closest target (by index proximity)
        best_target = None
        best_dist = float("inf")
        for ti in target_indices:
            dist = abs(ci - ti)
            if dist < best_dist:
                best_dist = dist
                best_target = ti
        if best_target is not None and best_dist <= 3:
            elements[ci].caption_target_id = elements[best_target].id
