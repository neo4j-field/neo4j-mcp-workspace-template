"""Document parsers -- convert PDFs to ParsedDocument."""

from .base import BaseParser
from .page_image import PageImageParser
from .text_only import TextOnlyParser

# DoclingParser imported lazily to avoid requiring docling dependency
__all__ = ["BaseParser", "PageImageParser", "TextOnlyParser"]
