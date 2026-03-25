"""Subprocess-safe parsing functions for background processing.

These top-level functions run in a ProcessPoolExecutor. They must be
importable at module level (pickle requirement). They communicate
progress back to the main process via a multiprocessing.Queue.

The functions return ParsedDocument objects (or dicts for pymupdf mode)
which are automatically pickled/unpickled by the executor.
"""

from __future__ import annotations

import json
import logging
import multiprocessing
from pathlib import Path
from typing import Any, Optional

# Progress message types (sent as tuples on the queue):
#   ("parsing_start", source_id, page_count)
#   ("parsing_done", source_id, element_count, section_count)
#   ("error", source_id, error_message)

logger = logging.getLogger(__name__)


def _send_progress(
    queue: Optional[multiprocessing.Queue],
    *args: Any,
) -> None:
    """Send a progress tuple on the queue (if available)."""
    if queue is not None:
        try:
            queue.put_nowait(args)
        except Exception:
            pass


def count_pdf_pages(pdf_path: str) -> int:
    """Count pages in a PDF using PyMuPDF. Fast and reliable."""
    import fitz
    doc = fitz.open(pdf_path)
    count = len(doc)
    doc.close()
    return count


def parse_single_pdf(
    pdf_path: str,
    source_id: str,
    version: int,
    parse_mode: str,
    progress_queue: Optional[multiprocessing.Queue] = None,
    *,
    # Common params
    metadata: Optional[dict[str, Any]] = None,
    dpi: int = 150,
    # pymupdf params
    chunk_size: int = 500,
    chunk_overlap: int = 50,
    extract_images: bool = True,
    extract_tables: bool = True,
    # docling params
    skip_furniture: bool = True,
    extract_sections: bool = True,
    extract_toc: bool = True,
    store_page_images: bool = False,
) -> dict[str, Any]:
    """Parse a single PDF in a subprocess.

    Returns a dict with:
      - "parse_mode": the mode used
      - "parsed_doc": serialized ParsedDocument (for docling/page_image)
      - "pymupdf_result": full result dict (for pymupdf mode, which does its own graph writing)

    For pymupdf mode, returns the data needed to write to Neo4j in the main process.
    For docling/page_image modes, returns a serialized ParsedDocument.
    """
    _send_progress(progress_queue, "parsing_start", source_id, 0)

    path = Path(pdf_path)
    metadata = metadata or {}

    if parse_mode == "pymupdf":
        return _parse_pymupdf(
            pdf_path=pdf_path,
            source_id=source_id,
            version=version,
            metadata=metadata,
            dpi=dpi,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            extract_images=extract_images,
            extract_tables=extract_tables,
            progress_queue=progress_queue,
        )
    elif parse_mode == "page_image":
        return _parse_page_image(
            pdf_path=pdf_path,
            source_id=source_id,
            version=version,
            metadata=metadata,
            dpi=dpi,
            progress_queue=progress_queue,
        )
    elif parse_mode == "docling":
        return _parse_docling(
            pdf_path=pdf_path,
            source_id=source_id,
            version=version,
            metadata=metadata,
            dpi=dpi,
            skip_furniture=skip_furniture,
            extract_sections=extract_sections,
            extract_toc=extract_toc,
            store_page_images=store_page_images,
            progress_queue=progress_queue,
        )
    elif parse_mode == "vlm_blocks":
        raise RuntimeError(
            "vlm_blocks mode is async-only and cannot run in a subprocess worker. "
            "It is handled directly in the server's event loop."
        )
    else:
        raise ValueError(f"Unknown parse_mode: {parse_mode}")


def _parse_pymupdf(
    pdf_path: str,
    source_id: str,
    version: int,
    metadata: dict[str, Any],
    dpi: int,
    chunk_size: int,
    chunk_overlap: int,
    extract_images: bool,
    extract_tables: bool,
    progress_queue: Optional[multiprocessing.Queue],
) -> dict[str, Any]:
    """PyMuPDF parsing in subprocess. Returns all data needed for graph writing."""
    import base64
    import re
    from datetime import datetime

    import fitz
    import tiktoken

    path = Path(pdf_path)
    doc_id = f"{source_id}_v{version}"

    fitz_doc = fitz.open(pdf_path)
    total_pages = len(fitz_doc)

    _send_progress(progress_queue, "parsing_start", source_id, total_pages)

    full_text_parts: list[str] = []
    element_records: list[dict[str, Any]] = []
    fig_counter = 0
    tbl_counter = 0

    for page_idx in range(total_pages):
        page = fitz_doc[page_idx]

        # 1. Find tables
        table_bboxes: list[tuple[float, float, float, float]] = []
        page_tables: list[dict[str, Any]] = []
        if extract_tables:
            try:
                finder = page.find_tables()
                for table in finder.tables:
                    bbox = tuple(table.bbox)
                    w = bbox[2] - bbox[0]
                    h = bbox[3] - bbox[1]
                    if w < 30 or h < 30:
                        continue
                    rows = table.extract()
                    if not rows or (len(rows) < 2 and len(rows[0]) < 2):
                        continue
                    try:
                        text = table.to_markdown()
                    except Exception:
                        text = "\n".join(
                            " | ".join(str(c or "") for c in row) for row in rows
                        )
                    table_bboxes.append(bbox)
                    page_tables.append({
                        "y_pos": bbox[1],
                        "bbox": bbox,
                        "text": text,
                    })
            except Exception:
                pass

        # 2. Get text blocks and image blocks
        blocks = page.get_text("blocks")
        page_items: list[dict[str, Any]] = []
        found_image_bboxes: list[tuple[float, float, float, float]] = []

        for block in blocks:
            bx0, by0, bx1, by1 = block[0], block[1], block[2], block[3]
            block_type = block[6]

            if block_type == 0:
                cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2
                in_table = any(
                    tb[0] <= cx <= tb[2] and tb[1] <= cy <= tb[3]
                    for tb in table_bboxes
                )
                if in_table:
                    continue
                text = block[4].strip()
                if text:
                    page_items.append({"type": "text", "y_pos": by0, "text": text})

            elif block_type == 1 and extract_images:
                w, h = bx1 - bx0, by1 - by0
                if w < 30 or h < 30:
                    continue
                cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2
                in_table = any(
                    tb[0] <= cx <= tb[2] and tb[1] <= cy <= tb[3]
                    for tb in table_bboxes
                )
                if in_table:
                    continue
                page_items.append({
                    "type": "image", "y_pos": by0,
                    "bbox": (bx0, by0, bx1, by1),
                })
                found_image_bboxes.append((bx0, by0, bx1, by1))

        # 2b. Embedded images via get_images()
        if extract_images:
            try:
                for img_info in page.get_images(full=True):
                    xref = img_info[0]
                    try:
                        rects = page.get_image_rects(xref)
                        for rect in rects:
                            if rect.width < 30 or rect.height < 30:
                                continue
                            bbox = (rect.x0, rect.y0, rect.x1, rect.y1)
                            cx, cy = (rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2
                            in_table = any(
                                tb[0] <= cx <= tb[2] and tb[1] <= cy <= tb[3]
                                for tb in table_bboxes
                            )
                            if in_table:
                                continue
                            already_found = any(
                                abs(fb[0] - bbox[0]) < 5 and abs(fb[1] - bbox[1]) < 5
                                for fb in found_image_bboxes
                            )
                            if already_found:
                                continue
                            page_items.append({
                                "type": "image", "y_pos": rect.y0,
                                "bbox": bbox,
                            })
                            found_image_bboxes.append(bbox)
                    except Exception:
                        pass
            except Exception:
                pass

        # 3. Add tables
        for tbl in page_tables:
            page_items.append({
                "type": "table", "y_pos": tbl["y_pos"],
                "bbox": tbl["bbox"], "text": tbl["text"],
            })

        # 4. Sort by y-position
        page_items.sort(key=lambda x: x["y_pos"])

        # 5. Build interleaved text and element data
        for item in page_items:
            if item["type"] == "text":
                full_text_parts.append(item["text"])
            elif item["type"] == "image":
                elem_id = f"{doc_id}_fig_{fig_counter}"
                fig_counter += 1
                bbox = item["bbox"]
                image_b64 = _crop_image_from_page(page, bbox, dpi)
                element_records.append({
                    "id": elem_id, "type": "image",
                    "imageBase64": image_b64, "imageMimeType": "image/png",
                    "pageNumber": page_idx,
                    "coordinates": json.dumps({
                        "x0": bbox[0], "y0": bbox[1],
                        "x1": bbox[2], "y1": bbox[3],
                    }),
                })
                full_text_parts.append(f"[IMAGE: {elem_id}]")
            elif item["type"] == "table":
                elem_id = f"{doc_id}_tbl_{tbl_counter}"
                tbl_counter += 1
                bbox = item["bbox"]
                image_b64 = _crop_image_from_page(page, bbox, dpi)
                element_records.append({
                    "id": elem_id, "type": "table",
                    "text": item["text"],
                    "imageBase64": image_b64, "imageMimeType": "image/png",
                    "pageNumber": page_idx,
                    "coordinates": json.dumps({
                        "x0": bbox[0], "y0": bbox[1],
                        "x1": bbox[2], "y1": bbox[3],
                    }),
                })
                full_text_parts.append(f"[TABLE: {elem_id}]\n{item['text']}")

    fitz_doc.close()

    full_text = "\n\n".join(part for part in full_text_parts if part.strip())

    # Chunk the text
    encoding = tiktoken.get_encoding("cl100k_base")
    tokens = encoding.encode(full_text)
    total_tokens = len(tokens)

    strategy_params = json.dumps({
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap,
    })

    chunks: list[dict[str, Any]] = []
    token_start = 0
    while token_start < total_tokens:
        token_end = min(token_start + chunk_size, total_tokens)
        chunk_tokens = tokens[token_start:token_end]
        chunk_text = encoding.decode(chunk_tokens)

        chunks.append({
            "id": f"{doc_id}_chunk_{len(chunks):04d}",
            "text": chunk_text,
            "index": len(chunks),
            "tokenCount": len(chunk_tokens),
            "type": "text",
            "chunkSetVersion": 1,
            "active": True,
            "strategy": "token_window",
            "strategyParams": strategy_params,
            "documentName": Path(pdf_path).stem,
        })

        step = chunk_size - chunk_overlap
        next_start = token_start + step
        if next_start >= total_tokens or next_start <= token_start:
            break
        token_start = next_start

    _send_progress(progress_queue, "parsing_done", source_id,
                   len(element_records), 0)

    return {
        "parse_mode": "pymupdf",
        "doc_id": doc_id,
        "source_id": source_id,
        "version": version,
        "total_pages": total_pages,
        "element_records": element_records,
        "chunks": chunks,
        "fig_counter": fig_counter,
        "tbl_counter": tbl_counter,
        "doc_props": {
            "id": doc_id,
            "sourceId": source_id,
            "version": version,
            "active": True,
            "name": Path(pdf_path).stem,
            "source": str(Path(pdf_path).resolve()),
            "parseMode": "pymupdf",
            "parseParams": json.dumps({
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
                "dpi": dpi,
                "extract_images": extract_images,
                "extract_tables": extract_tables,
            }),
            "totalPages": total_pages,
            "totalElements": len(element_records),
            "createdAt": datetime.now().isoformat(),
            **{k.replace(" ", "_").replace("-", "_"): v for k, v in metadata.items()},
        },
    }


def _parse_page_image(
    pdf_path: str,
    source_id: str,
    version: int,
    metadata: dict[str, Any],
    dpi: int,
    progress_queue: Optional[multiprocessing.Queue],
) -> dict[str, Any]:
    """Page-image parsing in subprocess."""
    from .parsers.page_image import PageImageParser

    parser = PageImageParser()
    parsed = parser.parse(
        pdf_path=pdf_path,
        source_id=source_id,
        version=version,
        metadata=metadata,
        dpi=dpi,
    )

    _send_progress(progress_queue, "parsing_done", source_id,
                   0, 0)

    return {
        "parse_mode": "page_image",
        "parsed_doc": parsed.model_dump(),
    }


def _parse_docling(
    pdf_path: str,
    source_id: str,
    version: int,
    metadata: dict[str, Any],
    dpi: int,
    skip_furniture: bool,
    extract_sections: bool,
    extract_toc: bool,
    store_page_images: bool,
    progress_queue: Optional[multiprocessing.Queue],
) -> dict[str, Any]:
    """Docling parsing in subprocess."""
    try:
        from .parsers.docling_parser import DoclingParser
    except ImportError:
        raise ImportError(
            "Docling is not installed. Re-run setup with docling enabled, or: "
            "uv sync --extra docling --directory mcp-neo4j-lexical-graph"
        )

    parser = DoclingParser()
    parsed = parser.parse(
        pdf_path=pdf_path,
        source_id=source_id,
        version=version,
        metadata=metadata,
        skip_furniture=skip_furniture,
        exclude_element_types=None,
        extract_sections=extract_sections,
        extract_toc=extract_toc,
        store_page_images=store_page_images,
        dpi=dpi,
    )

    _send_progress(progress_queue, "parsing_done", source_id,
                   len(parsed.elements), len(parsed.sections))

    return {
        "parse_mode": "docling",
        "parsed_doc": parsed.model_dump(),
    }


def _crop_image_from_page(
    page: Any, bbox: tuple[float, ...], dpi: int
) -> Optional[str]:
    """Crop a region from a PyMuPDF page and return base64-encoded PNG."""
    import base64

    try:
        import fitz as fitz_lib
        rect = fitz_lib.Rect(bbox[0], bbox[1], bbox[2], bbox[3])
        rect.normalize()
        if rect.is_empty or rect.width < 5 or rect.height < 5:
            return None
        pix = page.get_pixmap(clip=rect, dpi=dpi)
        return base64.b64encode(pix.tobytes("png")).decode("ascii")
    except Exception:
        return None
