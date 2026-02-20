"""VLM block ordering parser -- PyMuPDF extraction + VLM reading order.

Combines PyMuPDF's precise text/image/table extraction with a Vision Language
Model for reading order determination and semantic classification. Produces
the same ParsedDocument output as the docling parser, making it a drop-in
replacement from the graph writer's perspective.

Three phases:
  Phase 1 (sync): PyMuPDF extracts blocks, tables, images; renders annotated image
  Phase 2 (async): VLM orders and classifies blocks; retry with heuristic fallback
  Phase 3 (sync): Build ParsedDocument with sections, captions, furniture filtering
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
from collections import Counter
from pathlib import Path
from typing import Any, Optional

import fitz
import structlog
from litellm import acompletion
from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel

from ..models import (
    ParsedDocument,
    ParsedElement,
    ParsedPage,
    ParsedSection,
)
from .base import BaseParser

logger = structlog.get_logger()

# ── VLM response models ──────────────────────────────────────────────

class BlockResult(BaseModel):
    id: str
    role: str


class PageBlocks(BaseModel):
    blocks: list[BlockResult]


# ── Constants ─────────────────────────────────────────────────────────

_ROLE_MAP: dict[str, str] = {
    "heading": "heading",
    "paragraph": "paragraph",
    "caption": "caption",
    "figure": "image",
    "table": "table",
    "list": "list_item",
    "footnote": "footnote",
    "sidebar": "paragraph",
    "equation": "formula",
    "code": "code",
    "other": "paragraph",
}

_ANNOTATION_COLORS = [
    "#FF0000", "#00AA00", "#0000FF", "#FF8800", "#8800FF",
    "#00AAAA", "#AA0088", "#888800", "#FF0088", "#0088FF",
    "#AA4400", "#44AA00", "#4400AA", "#AA0044", "#00AA44",
    "#004488", "#880044", "#448800", "#440088", "#884400",
]

DEFAULT_VLM_PROMPT = """\
You are a document layout analysis assistant. You receive:
1. An image of a PDF page with labeled rectangles (B0, B1, B2...) drawn on it
2. A JSON list describing each block (id, type, text preview)

Your job:
- Return the block IDs in the correct **human reading order** \
(top-to-bottom, left-to-right for multi-column layouts)
- Assign each block a semantic **role**: heading, paragraph, caption, \
figure, table, list, footnote, sidebar, equation, code, other
- **Omit** blocks that are: page numbers, repeated headers/footers, \
empty/decorative, or irrelevant margin text
- If a block contains table data (or overlaps a yellow table region \
marked T0, T1...), assign role "table"
- If a block is an image, assign role "figure"
- For multi-column layouts, read each column top-to-bottom before \
moving to the next column

Return ONLY a JSON object with a "blocks" array. \
Each entry has "id" (string) and "role" (string)."""

# Threshold: if VLM filters more than this fraction, keep all blocks
_MAX_FILTER_RATIO = 0.80
# Threshold for cross-page furniture detection
_FURNITURE_PAGE_RATIO = 0.50


# ── Internal data structures ──────────────────────────────────────────

class _RawBlock:
    """Intermediate representation of a PyMuPDF block for one page."""

    __slots__ = (
        "block_id", "bbox", "block_type", "text", "font_size_max",
        "pymupdf_hint", "image_base64", "image_mime_type",
        "text_as_html", "raw_index",
    )

    def __init__(self) -> None:
        self.block_id: str = ""
        self.bbox: tuple[float, float, float, float] = (0, 0, 0, 0)
        self.block_type: str = "text"
        self.text: str = ""
        self.font_size_max: float = 0.0
        self.pymupdf_hint: str | None = None
        self.image_base64: str | None = None
        self.image_mime_type: str | None = None
        self.text_as_html: str | None = None
        self.raw_index: int = 0


class _PageData:
    """All extraction results for a single page."""

    __slots__ = (
        "page_number", "width", "height", "blocks",
        "annotated_image_b64", "page_image_b64",
    )

    def __init__(self) -> None:
        self.page_number: int = 0
        self.width: float = 0.0
        self.height: float = 0.0
        self.blocks: list[_RawBlock] = []
        self.annotated_image_b64: str = ""
        self.page_image_b64: str | None = None


# ── Phase 1: PyMuPDF extraction ──────────────────────────────────────

def _extract_page_blocks(
    page: fitz.Page,
    page_number: int,
    dpi: int = 150,
    store_page_images: bool = False,
) -> _PageData:
    """Extract blocks, tables, images from a single page (sync, GIL-friendly)."""
    pd = _PageData()
    pd.page_number = page_number
    pd.width = float(page.rect.width)
    pd.height = float(page.rect.height)

    # Render page image
    pix = page.get_pixmap(dpi=dpi)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    scale_x = img.width / pd.width
    scale_y = img.height / pd.height

    if store_page_images:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        pd.page_image_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    # Detect tables
    table_bboxes: list[tuple[float, float, float, float]] = []
    table_html_map: dict[int, str] = {}
    try:
        tables_result = page.find_tables()
        for ti, t in enumerate(tables_result.tables):
            table_bboxes.append(t.bbox)
            try:
                import pandas as pd_lib
                df = t.to_pandas()
                table_html_map[ti] = df.to_html(index=False)
            except Exception:
                cells = []
                for row in t.extract():
                    cells.append(" | ".join(str(c) if c else "" for c in row))
                table_html_map[ti] = "<table>" + "".join(
                    f"<tr><td>{'</td><td>'.join(r.split(' | '))}</td></tr>"
                    for r in cells
                ) + "</table>"
    except Exception:
        pass

    raw_blocks = page.get_text("dict")["blocks"]

    # Build annotated image
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14)
    except Exception:
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 14)
        except Exception:
            font = ImageFont.load_default()

    blocks: list[_RawBlock] = []

    for i, block in enumerate(raw_blocks):
        bbox = block["bbox"]
        btype = block.get("type", 0)

        rb = _RawBlock()
        rb.raw_index = i
        rb.bbox = (bbox[0], bbox[1], bbox[2], bbox[3])
        rb.block_id = f"B{i}"

        if btype == 1:
            # Image block
            rb.block_type = "image"
            rb.text = ""
            try:
                xref = block.get("image", None)
                if xref:
                    img_data = page.parent.extract_image(xref)
                    if img_data:
                        rb.image_base64 = base64.b64encode(img_data["image"]).decode("ascii")
                        rb.image_mime_type = f"image/{img_data.get('ext', 'png')}"
                else:
                    clip = page.get_pixmap(clip=fitz.Rect(bbox), dpi=dpi)
                    rb.image_base64 = base64.b64encode(clip.tobytes("png")).decode("ascii")
                    rb.image_mime_type = "image/png"
            except Exception:
                clip = page.get_pixmap(clip=fitz.Rect(bbox), dpi=dpi)
                rb.image_base64 = base64.b64encode(clip.tobytes("png")).decode("ascii")
                rb.image_mime_type = "image/png"
        else:
            # Text block
            rb.block_type = "text"
            text_parts = []
            max_font = 0.0
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text_parts.append(span.get("text", ""))
                    size = span.get("size", 0)
                    if size > max_font:
                        max_font = size
            rb.text = " ".join(text_parts).strip()
            rb.font_size_max = max_font

            if not rb.text:
                continue

        # Check table overlap
        best_table_idx = -1
        best_overlap = 0.0
        block_area = max(1.0, (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]))
        for ti, tb in enumerate(table_bboxes):
            overlap_x = max(0, min(bbox[2], tb[2]) - max(bbox[0], tb[0]))
            overlap_y = max(0, min(bbox[3], tb[3]) - max(bbox[1], tb[1]))
            overlap = (overlap_x * overlap_y) / block_area
            if overlap > best_overlap:
                best_overlap = overlap
                best_table_idx = ti
        if best_overlap > 0.5:
            rb.pymupdf_hint = "overlaps_table"
            if best_table_idx in table_html_map:
                rb.text_as_html = table_html_map[best_table_idx]
            # Crop table image
            tb = table_bboxes[best_table_idx]
            try:
                clip = page.get_pixmap(clip=fitz.Rect(tb), dpi=dpi)
                rb.image_base64 = base64.b64encode(clip.tobytes("png")).decode("ascii")
                rb.image_mime_type = "image/png"
            except Exception:
                pass

        # Draw annotation on image
        color = _ANNOTATION_COLORS[i % len(_ANNOTATION_COLORS)]
        x0s, y0s = bbox[0] * scale_x, bbox[1] * scale_y
        x1s, y1s = bbox[2] * scale_x, bbox[3] * scale_y
        draw.rectangle([x0s, y0s, x1s, y1s], outline=color, width=3)

        label = rb.block_id
        try:
            tw = draw.textlength(label, font=font)
        except Exception:
            tw = len(label) * 8
        th = 16
        draw.rectangle([x0s, y0s, x0s + tw + 6, y0s + th + 4], fill=color)
        draw.text((x0s + 3, y0s + 2), label, fill="white", font=font)

        blocks.append(rb)

    # Draw table region overlays
    for ti, tb in enumerate(table_bboxes):
        x0s, y0s = tb[0] * scale_x, tb[1] * scale_y
        x1s, y1s = tb[2] * scale_x, tb[3] * scale_y
        draw.rectangle([x0s, y0s, x1s, y1s], outline="#FFFF00", width=4)
        draw.text((x1s - 30, y0s + 4), f"T{ti}", fill="#FFFF00", font=font)

    # Encode annotated image
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    pd.annotated_image_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    pd.blocks = blocks

    return pd


def _extract_all_pages(
    pdf_path: str,
    dpi: int = 150,
    store_page_images: bool = False,
) -> list[_PageData]:
    """Extract blocks from all pages of a PDF (sync)."""
    doc = fitz.open(pdf_path)
    pages = []
    try:
        for page_idx in range(len(doc)):
            page = doc[page_idx]
            pd = _extract_page_blocks(page, page_idx, dpi=dpi, store_page_images=store_page_images)
            pages.append(pd)
    finally:
        doc.close()
    return pages


# ── Phase 2: VLM classification ──────────────────────────────────────

async def _classify_page_vlm(
    page_data: _PageData,
    vlm_model: str,
    system_prompt: str,
    text_preview_length: int = 200,
    retries: int = 3,
) -> list[BlockResult]:
    """Send one page to VLM for ordering + classification. Returns ordered blocks."""
    block_metadata = []
    for rb in page_data.blocks:
        entry: dict[str, Any] = {"id": rb.block_id, "type": rb.block_type}
        if rb.text:
            entry["text"] = rb.text[:text_preview_length]
        if rb.pymupdf_hint:
            entry["pymupdf_hint"] = rb.pymupdf_hint
        block_metadata.append(entry)

    if not block_metadata:
        return []

    user_content: list[dict[str, Any]] = [
        {
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{page_data.annotated_image_b64}",
                "detail": "high",
            },
        },
        {
            "type": "text",
            "text": (
                f"Page {page_data.page_number + 1}. "
                f"Here are the blocks:\n\n```json\n{json.dumps(block_metadata, indent=2)}\n```"
            ),
        },
    ]

    valid_ids = {rb.block_id for rb in page_data.blocks}
    last_error: Exception | None = None

    for attempt in range(retries):
        try:
            kwargs: dict[str, Any] = {
                "model": vlm_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                "response_format": PageBlocks,
            }
            if "gpt-5" in vlm_model:
                kwargs["reasoning_effort"] = "low"

            resp = await acompletion(**kwargs)
            result = PageBlocks.model_validate_json(resp.choices[0].message.content)

            # Validate: keep only known block IDs
            valid_blocks = [b for b in result.blocks if b.id in valid_ids]

            # Safety check: if VLM filtered too aggressively, fall back
            if len(page_data.blocks) > 0:
                filter_ratio = 1.0 - len(valid_blocks) / len(page_data.blocks)
                if filter_ratio > _MAX_FILTER_RATIO and len(page_data.blocks) > 3:
                    logger.warning(
                        "VLM filtered too many blocks, falling back to heuristic",
                        page=page_data.page_number,
                        kept=len(valid_blocks),
                        total=len(page_data.blocks),
                    )
                    return _heuristic_fallback(page_data)

            return valid_blocks

        except Exception as e:
            last_error = e
            logger.warning(
                "VLM call failed, retrying",
                page=page_data.page_number,
                attempt=attempt + 1,
                error=str(e),
            )
            if attempt < retries - 1:
                await asyncio.sleep(2 ** attempt)

    logger.error(
        "VLM failed after all retries, using heuristic fallback",
        page=page_data.page_number,
        error=str(last_error),
    )
    return _heuristic_fallback(page_data)


def _heuristic_fallback(page_data: _PageData) -> list[BlockResult]:
    """Deterministic ordering when VLM is unavailable."""
    sorted_blocks = sorted(
        page_data.blocks,
        key=lambda b: (b.bbox[1], b.bbox[0]),
    )

    median_font = 0.0
    font_sizes = [b.font_size_max for b in sorted_blocks if b.font_size_max > 0]
    if font_sizes:
        font_sizes.sort()
        median_font = font_sizes[len(font_sizes) // 2]

    results = []
    for rb in sorted_blocks:
        if rb.block_type == "image":
            role = "figure"
        elif rb.pymupdf_hint == "overlaps_table":
            role = "table"
        elif median_font > 0 and rb.font_size_max > median_font * 1.2:
            role = "heading"
        else:
            role = "paragraph"
        results.append(BlockResult(id=rb.block_id, role=role))
    return results


# ── Phase 3: Build ParsedDocument ─────────────────────────────────────

def _detect_cross_page_furniture(
    all_pages: list[_PageData],
    all_vlm_results: list[list[BlockResult]],
) -> set[str]:
    """Detect repeated text blocks across pages (headers/footers the VLM missed).

    Returns a set of (page_number, block_id) tuples to exclude.
    """
    if len(all_pages) < 3:
        return set()

    text_hashes: Counter[str] = Counter()
    hash_to_keys: dict[str, list[tuple[int, str]]] = {}

    for page_data, vlm_blocks in zip(all_pages, all_vlm_results):
        kept_ids = {b.id for b in vlm_blocks}
        for rb in page_data.blocks:
            if rb.block_id not in kept_ids:
                continue
            normalized = rb.text.strip().lower()[:100]
            if len(normalized) < 5:
                continue
            h = hashlib.md5(normalized.encode()).hexdigest()[:12]
            text_hashes[h] += 1
            hash_to_keys.setdefault(h, []).append(
                (page_data.page_number, rb.block_id)
            )

    threshold = len(all_pages) * _FURNITURE_PAGE_RATIO
    exclude: set[str] = set()
    for h, count in text_hashes.items():
        if count >= threshold:
            for page_num, block_id in hash_to_keys[h]:
                exclude.add(f"{page_num}_{block_id}")

    if exclude:
        logger.info(
            "Cross-page furniture detected",
            blocks_excluded=len(exclude),
            pages=len(all_pages),
        )
    return exclude


def _build_parsed_document(
    all_pages: list[_PageData],
    all_vlm_results: list[list[BlockResult]],
    doc_id: str,
    source_id: str,
    version: int,
    name: str,
    source: str,
    metadata: dict[str, Any],
    parse_params: dict[str, Any],
    extract_sections: bool = True,
    store_page_images: bool = False,
) -> ParsedDocument:
    """Build the ParsedDocument from extraction + VLM results."""
    furniture_keys = _detect_cross_page_furniture(all_pages, all_vlm_results)

    elements: list[ParsedElement] = []
    page_element_ids: dict[int, list[str]] = {}
    elem_counter = 0

    block_lookup: dict[tuple[int, str], _RawBlock] = {}
    for page_data in all_pages:
        for rb in page_data.blocks:
            block_lookup[(page_data.page_number, rb.block_id)] = rb

    for page_data, vlm_blocks in zip(all_pages, all_vlm_results):
        pn = page_data.page_number
        for vb in vlm_blocks:
            key = f"{pn}_{vb.id}"
            if key in furniture_keys:
                continue

            rb = block_lookup.get((pn, vb.id))
            if rb is None:
                continue

            our_type = _ROLE_MAP.get(vb.role, "paragraph")

            elem_id = f"{doc_id}_elem_{elem_counter}"
            elem_counter += 1

            element = ParsedElement(
                id=elem_id,
                type=our_type,
                text=rb.text or None,
                text_as_html=rb.text_as_html,
                image_base64=rb.image_base64,
                image_mime_type=rb.image_mime_type,
                coordinates={"x0": rb.bbox[0], "y0": rb.bbox[1], "x1": rb.bbox[2], "y1": rb.bbox[3]},
                level=1 if our_type == "heading" else None,
                font_size_max=rb.font_size_max if rb.font_size_max > 0 else None,
                page_number=pn,
                caption_target_id=None,
            )
            elements.append(element)
            page_element_ids.setdefault(pn, []).append(elem_id)

    # Build sections from heading elements
    sections: list[ParsedSection] = []
    heading_stack: list[ParsedSection] = []

    if extract_sections:
        for elem in elements:
            if elem.type == "heading" and elem.text:
                sec_id = f"{doc_id}_sec_{len(sections)}"
                section = ParsedSection(
                    id=sec_id,
                    title=elem.text.strip(),
                    level=elem.level or 1,
                    element_ids=[elem.id],
                )
                while heading_stack and heading_stack[-1].level >= (elem.level or 1):
                    heading_stack.pop()
                if heading_stack:
                    heading_stack[-1].subsection_ids.append(sec_id)
                heading_stack.append(section)
                sections.append(section)
            elif heading_stack:
                heading_stack[-1].element_ids.append(elem.id)

    # Link captions to nearest figure/table
    _link_captions(elements)

    # Build pages
    pages: list[ParsedPage] = []
    for page_data in all_pages:
        pn = page_data.page_number
        pages.append(ParsedPage(
            page_number=pn,
            width=page_data.width,
            height=page_data.height,
            text=None,
            image_base64=page_data.page_image_b64 if store_page_images else None,
            image_mime_type="image/png" if store_page_images and page_data.page_image_b64 else None,
            element_ids=page_element_ids.get(pn, []),
        ))

    return ParsedDocument(
        id=doc_id,
        source_id=source_id,
        version=version,
        name=name,
        source=source,
        parse_mode="vlm_blocks",
        parse_params=parse_params,
        metadata=metadata or {},
        pages=pages,
        elements=elements,
        sections=sections,
    )


def _link_captions(elements: list[ParsedElement]) -> None:
    """Link caption elements to their nearest table/figure target."""
    caption_indices = [i for i, e in enumerate(elements) if e.type == "caption"]
    target_indices = [i for i, e in enumerate(elements) if e.type in ("table", "image")]

    for ci in caption_indices:
        best_target = None
        best_dist = float("inf")
        for ti in target_indices:
            dist = abs(ci - ti)
            if dist < best_dist:
                best_dist = dist
                best_target = ti
        if best_target is not None and best_dist <= 3:
            elements[ci].caption_target_id = elements[best_target].id


# ── Main parser class ─────────────────────────────────────────────────

class VLMBlocksParser(BaseParser):
    """Parse PDFs using PyMuPDF blocks + VLM ordering/classification.

    This parser is async-native: call parse_async() instead of parse().
    The sync parse() method raises NotImplementedError directing callers
    to the async path.
    """

    def __init__(
        self,
        vlm_model: str = "gpt-5-mini",
        max_parallel: int = 10,
    ):
        self.vlm_model = vlm_model
        self.max_parallel = max_parallel

    def parse(
        self,
        pdf_path: str,
        source_id: str,
        version: int = 1,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> ParsedDocument:
        raise NotImplementedError(
            "VLMBlocksParser is async-only. Use parse_async() instead."
        )

    async def parse_async(
        self,
        pdf_path: str,
        source_id: str,
        version: int = 1,
        metadata: dict[str, Any] | None = None,
        *,
        dpi: int = 150,
        store_page_images: bool = False,
        vlm_prompt: str | None = None,
        skip_furniture: bool = True,
        extract_sections: bool = True,
        text_preview_length: int = 200,
        vlm_retries: int = 3,
        **kwargs: Any,
    ) -> ParsedDocument:
        path = Path(pdf_path)
        if not path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        doc_id = f"{source_id}_v{version}"
        system_prompt = vlm_prompt or DEFAULT_VLM_PROMPT

        logger.info(
            "VLMBlocksParser: starting",
            pdf_path=pdf_path,
            doc_id=doc_id,
            vlm_model=self.vlm_model,
            max_parallel=self.max_parallel,
        )

        # Phase 1: PyMuPDF extraction (sync, run in thread)
        all_pages = await asyncio.to_thread(
            _extract_all_pages, pdf_path, dpi, store_page_images
        )
        logger.info(
            "VLMBlocksParser: Phase 1 complete",
            pages=len(all_pages),
            total_blocks=sum(len(p.blocks) for p in all_pages),
        )

        # Phase 2: VLM classification (async, parallel across pages)
        sem = asyncio.Semaphore(self.max_parallel)

        async def classify_with_sem(page_data: _PageData) -> list[BlockResult]:
            async with sem:
                return await _classify_page_vlm(
                    page_data,
                    vlm_model=self.vlm_model,
                    system_prompt=system_prompt,
                    text_preview_length=text_preview_length,
                    retries=vlm_retries,
                )

        all_vlm_results = await asyncio.gather(
            *[classify_with_sem(pd) for pd in all_pages]
        )
        logger.info(
            "VLMBlocksParser: Phase 2 complete",
            pages_classified=len(all_vlm_results),
            total_elements=sum(len(r) for r in all_vlm_results),
        )

        # Phase 3: Build ParsedDocument (sync, fast)
        parse_params = {
            "dpi": dpi,
            "store_page_images": store_page_images,
            "vlm_model": self.vlm_model,
            "max_vlm_parallel": self.max_parallel,
            "text_preview_length": text_preview_length,
            "extract_sections": extract_sections,
            "skip_furniture": skip_furniture,
        }

        parsed = _build_parsed_document(
            all_pages=all_pages,
            all_vlm_results=all_vlm_results,
            doc_id=doc_id,
            source_id=source_id,
            version=version,
            name=path.stem,
            source=str(path.resolve()),
            metadata=metadata or {},
            parse_params=parse_params,
            extract_sections=extract_sections,
            store_page_images=store_page_images,
        )

        logger.info(
            "VLMBlocksParser: done",
            doc_id=doc_id,
            pages=len(parsed.pages),
            elements=len(parsed.elements),
            sections=len(parsed.sections),
        )
        return parsed
