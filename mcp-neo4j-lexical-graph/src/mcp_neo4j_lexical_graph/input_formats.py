"""Small, explicit input-format routing shared by the MCP preflight and workers."""

from pathlib import Path

DOCUMENT_FORMATS = {
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "text",
    ".text": "text",
    ".html": "html",
    ".htm": "html",
    ".xhtml": "html",
    ".docx": "docx",
}
PDF_MODES = frozenset({"pymupdf", "docling", "page_image"})
SUPPORTED_SUFFIXES = frozenset({".pdf", *DOCUMENT_FORMATS})


def mode_for_path(path: str | Path, requested: str = "pymupdf") -> str:
    """Keep PDF selection; route supported non-PDF files to native document parsing."""
    if requested not in PDF_MODES | {"document"}:
        raise ValueError(
            f"Unknown parse_mode {requested!r}; choose a PDF mode or 'document'"
        )
    suffix = Path(path).suffix.lower()
    if suffix == ".pdf":
        if requested == "document":
            raise ValueError(
                "The 'document' mode is for Markdown, TXT, HTML and DOCX; choose a PDF parse mode for PDF files"
            )
        return requested
    if suffix in DOCUMENT_FORMATS:
        if requested == "page_image":
            raise ValueError(
                f"{requested} requires PDF pages; use automatic document parsing for {suffix}"
            )
        return "document"
    supported = ", ".join(sorted(SUPPORTED_SUFFIXES))
    raise ValueError(
        f"Unsupported file type {suffix or '(none)'!r}; supported: {supported}"
    )


def default_source_id(path: str | Path) -> str:
    """Non-PDF IDs include extension so same-stem mixed files cannot replace each other."""
    path = Path(path)
    return path.stem if path.suffix.lower() == ".pdf" else path.name
