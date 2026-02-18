"""Base parser interface.

All parsers produce a ParsedDocument. Future parsers (unstructured, llamaparse,
OCR, etc.) implement this same interface.
"""

from abc import ABC, abstractmethod
from typing import Any

from ..models import ParsedDocument


class BaseParser(ABC):
    """Abstract base for document parsers."""

    @abstractmethod
    def parse(
        self,
        pdf_path: str,
        source_id: str,
        version: int = 1,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> ParsedDocument:
        """Parse a PDF and return a ParsedDocument.

        Args:
            pdf_path: Path to the PDF file.
            source_id: Stable document identifier (same across versions).
            version: Version number for this parse.
            metadata: Optional user-provided metadata.
            **kwargs: Parser-specific options.

        Returns:
            A fully populated ParsedDocument.
        """
        ...
