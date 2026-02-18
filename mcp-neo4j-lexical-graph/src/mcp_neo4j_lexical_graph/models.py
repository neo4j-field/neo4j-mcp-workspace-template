"""Pydantic models for the lexical graph v2.

Intermediate representation between parsers and Neo4j.
All parsers produce ParsedDocument; the graph writer consumes it.
This is parser-agnostic -- NOT tied to any specific library.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ============================================================
# Intermediate models (parser output -> graph writer input)
# ============================================================


class ParsedElement(BaseModel):
    """An individual content element extracted from the document.

    Elements are the atomic units: paragraphs, headings, tables, images, etc.
    Both tables and images carry text AND image properties.
    """

    id: str = Field(..., description="Unique element identifier")
    type: str = Field(
        ...,
        description=(
            "Element type: paragraph, heading, table, image, list_item, "
            "caption, footnote, formula, code"
        ),
    )

    # Text properties
    text: Optional[str] = Field(
        None,
        description="Plain text content. Tables: cell text; images: caption/description.",
    )
    text_as_html: Optional[str] = Field(
        None, description="HTML representation with structure (tables only)."
    )

    # Image properties (populated for tables AND images)
    image_base64: Optional[str] = Field(
        None,
        description="Base64-encoded image. Tables: rendered crop; images: the image.",
    )
    image_mime_type: Optional[str] = Field(None, description="MIME type of the image.")

    # Layout and structure
    coordinates: Optional[dict[str, float]] = Field(
        None, description="Bounding box {x0, y0, x1, y1}."
    )
    level: Optional[int] = Field(None, description="Heading level (1-6).")
    page_number: int = Field(..., description="0-based page number this element belongs to.")

    # Caption linkage
    caption_target_id: Optional[str] = Field(
        None,
        description="If type=caption, the id of the table/image element this captions.",
    )


class ParsedSection(BaseModel):
    """A document section derived from headings."""

    id: str
    title: str
    level: int = Field(..., description="Heading level that starts this section (1-6).")
    element_ids: list[str] = Field(
        default_factory=list, description="IDs of elements belonging to this section."
    )
    subsection_ids: list[str] = Field(
        default_factory=list, description="IDs of direct child sections."
    )


class ParsedPage(BaseModel):
    """A single page of the document."""

    page_number: int = Field(..., description="0-based page number.")
    width: Optional[float] = None
    height: Optional[float] = None
    text: Optional[str] = Field(None, description="Full page text (text_only / page_image modes).")
    image_base64: Optional[str] = Field(None, description="Base64 page image.")
    image_mime_type: Optional[str] = None
    element_ids: list[str] = Field(
        default_factory=list, description="Element IDs on this page, in reading order."
    )


class ParsedDocument(BaseModel):
    """Complete parsed document -- the universal intermediate format.

    Every parser (text_only, docling, page_image, and future ones)
    converts to this model.  The graph writer only knows about this type.
    """

    id: str = Field(..., description="Unique document version id ({sourceId}_v{version}).")
    source_id: str = Field(..., description="Stable identifier across versions.")
    version: int = Field(1, description="Version number.")
    name: str = Field(..., description="Human-readable document name.")
    source: str = Field(..., description="Source file path or URL.")
    parse_mode: str = Field(..., description="Parser used: text_only, docling, page_image.")
    parse_params: dict[str, Any] = Field(
        default_factory=dict, description="All parameters used for parsing."
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="User-provided metadata."
    )
    created_at: str = Field(
        default_factory=lambda: datetime.now().isoformat(),
        description="ISO timestamp of creation.",
    )
    pages: list[ParsedPage] = Field(default_factory=list)
    elements: list[ParsedElement] = Field(default_factory=list)
    sections: list[ParsedSection] = Field(default_factory=list)


# ============================================================
# Progress reporting
# ============================================================


class ProgressUpdate(BaseModel):
    """Progress update for long-running operations."""

    stage: str = Field(..., description="Current processing stage")
    current: int = Field(..., description="Current item number")
    total: int = Field(..., description="Total items to process")
    message: str = Field(..., description="Human-readable status message")

    @property
    def percentage(self) -> float:
        return (self.current / self.total * 100) if self.total > 0 else 0
