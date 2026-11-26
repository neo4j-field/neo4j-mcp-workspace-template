"""Pageless local documents: literal UTF-8 text and native Docling structures.

Markdown, HTML and Word use declarative backends, without PDF layout models,
heading inference, browser rendering or referenced-resource fetching.
"""

from __future__ import annotations

import base64
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from typing import Any

from ..metadata import normalize_document_metadata
from ..input_formats import DOCUMENT_FORMATS
from ..models import ParsedDocument, ParsedElement, ParsedSection
from .base import BaseParser
from .conversion_validation import require_complete_conversion
from .docling_parser import _LABEL_MAP, _get_item_text, _get_table_html


class _ImageReferences(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.references: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "img":
            source = dict(attrs).get("src")
            if source:
                self.references.append(source)


def _image_references(text: str, source_format: str) -> list[str]:
    if source_format == "html":
        parser = _ImageReferences()
        parser.feed(text)
        return parser.references
    if source_format == "markdown":
        import marko

        references: list[str] = []

        def walk(node):
            if isinstance(node, marko.inline.Image):
                references.append(node.dest)
            children = getattr(node, "children", [])
            if isinstance(children, list):
                for child in children:
                    walk(child)

        walk(marko.parse(text))
        return references
    return []


def _reference_text(reference: str) -> str:
    if reference.lower().startswith("data:"):
        return "Embedded image reference (not expanded)"
    return f"Image reference (not fetched): {reference}"


def _read_utf8(path: Path) -> str:
    try:
        text = path.read_bytes().decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"{path.name} must contain valid UTF-8 text; convert its encoding before importing"
        ) from exc
    if "\x00" in text:
        raise ValueError(
            f"{path.name} contains NUL bytes; provide UTF-8 text instead of binary or UTF-16 data"
        )
    return text


def _literal_elements(text: str, doc_id: str) -> list[ParsedElement]:
    elements: list[ParsedElement] = []
    pending: list[str] = []
    start = 1
    lines = text.splitlines(keepends=True)
    for number, line in enumerate(lines, 1):
        if not pending:
            start = number
        pending.append(line)
        if not line.strip() or number == len(lines):
            elements.append(
                ParsedElement(
                    id=f"{doc_id}_elem_{len(elements)}",
                    type="paragraph",
                    text="".join(pending),
                    page_number=None,
                    source_anchor=f"lines:{start}-{number}",
                )
            )
            pending = []
    return elements


class StructuredDocumentParser(BaseParser):
    """Parse supported local files; TXT is literal and never parsed as Markdown."""

    def parse(
        self,
        pdf_path: str,
        source_id: str,
        version: int = 1,
        metadata: dict[str, Any] | None = None,
        *,
        extract_images: bool = True,
        extract_tables: bool = True,
        extract_sections: bool = True,
        **kwargs: Any,
    ) -> ParsedDocument:
        metadata = normalize_document_metadata(metadata)
        path = Path(pdf_path)
        if not path.is_file():
            raise FileNotFoundError(f"Document not found: {path}")
        source_format = DOCUMENT_FORMATS.get(path.suffix.lower())
        if source_format is None:
            raise ValueError(
                f"Unsupported document extension {path.suffix!r}; use Markdown, TXT, HTML or DOCX"
            )
        doc_id = f"{source_id}_v{version}"
        text = _read_utf8(path) if source_format != "docx" else ""
        if source_format == "text":
            elements, sections = _literal_elements(text, doc_id), []
        else:
            document = self._convert(path, text, source_format)
            elements, sections = self._adapt(
                document,
                doc_id,
                source_format,
                text,
                extract_images=extract_images,
                extract_tables=extract_tables,
                extract_sections=extract_sections,
            )
        return ParsedDocument(
            id=doc_id,
            source_id=source_id,
            version=version,
            name=path.stem,
            source=str(path.resolve()),
            parse_mode="document",
            source_format=source_format,
            parse_params={
                "source_format": source_format,
                "encoding": "utf-8" if source_format != "docx" else None,
                "referenced_resources_fetched": False,
                "extract_images": extract_images,
                "extract_tables": extract_tables,
                "extract_sections": extract_sections,
            },
            metadata=metadata,
            pages=[],
            elements=elements,
            sections=sections,
        )

    @staticmethod
    def _convert(path: Path, text: str, source_format: str):
        from docling.document_converter import (
            DocumentConverter,
            MarkdownFormatOption,
            HTMLFormatOption,
            WordFormatOption,
        )
        from docling.datamodel.backend_options import (
            MarkdownBackendOptions,
            HTMLBackendOptions,
            MsWordBackendOptions,
        )
        from docling.datamodel.base_models import InputFormat, DocumentStream

        options = {
            InputFormat.MD: MarkdownFormatOption(
                backend_options=MarkdownBackendOptions(
                    encoding="utf-8",
                    fetch_images=False,
                    enable_remote_fetch=False,
                    enable_local_fetch=False,
                )
            ),
            InputFormat.HTML: HTMLFormatOption(
                backend_options=HTMLBackendOptions(
                    fetch_images=False,
                    render_page=False,
                    add_title=False,
                    enable_remote_fetch=False,
                    enable_local_fetch=False,
                )
            ),
            InputFormat.DOCX: WordFormatOption(
                backend_options=MsWordBackendOptions(
                    render_chart_images=False,
                    enable_remote_fetch=False,
                    enable_local_fetch=False,
                )
            ),
        }
        converter = DocumentConverter(
            allowed_formats=list(options), format_options=options
        )
        if source_format == "docx":
            source = path
        else:
            # Canonical extension handles .markdown/.htm/.xhtml without MIME guessing.
            extension = ".md" if source_format == "markdown" else ".html"
            source = DocumentStream(
                name=path.stem + extension, stream=BytesIO(text.encode("utf-8"))
            )
        result = converter.convert(source)
        require_complete_conversion(result, path.name)
        return result.document

    @staticmethod
    def _adapt(
        document,
        doc_id: str,
        source_format: str,
        text: str,
        *,
        extract_images: bool,
        extract_tables: bool,
        extract_sections: bool,
    ):
        elements: list[ParsedElement] = []
        sections: list[ParsedSection] = []
        stack: list[ParsedSection] = []
        pictures: list[ParsedElement] = []
        by_native_ref: dict[str, ParsedElement] = {}
        caption_targets: dict[str, str] = {}
        from docling_core.types.doc import ContentLayer

        # HTML marks real pre-h1 body text as furniture; retain it, not just BODY.
        layers = {layer for layer in ContentLayer if layer != ContentLayer.INVISIBLE}
        for item, _tree_depth in document.iterate_items(included_content_layers=layers):
            label = (
                item.label.value if hasattr(item.label, "value") else str(item.label)
            )
            kind = _LABEL_MAP.get(label.lower())
            if (
                kind is None
                or (kind == "image" and not extract_images)
                or (kind == "table" and not extract_tables)
            ):
                continue
            content = _get_item_text(item, document)
            level = None
            image_base64 = image_mime = None
            if kind == "heading":
                if label.lower() == "title":
                    level = 1
                else:
                    level = max(1, getattr(item, "level", 1))
                    # MD/HTML reserve native level 0 for TitleItem (source h1).
                    if source_format in ("markdown", "html"):
                        level += 1
            if kind == "image":
                content = (
                    item.caption_text(document)
                    if hasattr(item, "caption_text")
                    else None
                )
                image = getattr(item, "image", None)
                if (
                    source_format == "docx"
                    and image is not None
                    and str(image.uri).startswith("data:")
                ):
                    pil_image = item.get_image(document)
                    if pil_image is not None:
                        buffer = BytesIO()
                        pil_image.save(buffer, format="PNG")
                        image_base64 = base64.b64encode(buffer.getvalue()).decode(
                            "ascii"
                        )
                        image_mime = "image/png"
            element = ParsedElement(
                id=f"{doc_id}_elem_{len(elements)}",
                type=kind,
                text=content,
                text_as_html=_get_table_html(item, document)
                if kind == "table"
                else None,
                image_base64=image_base64,
                image_mime_type=image_mime,
                level=level,
                page_number=None,
                source_anchor=f"element:{len(elements) + 1}",
            )
            elements.append(element)
            by_native_ref[item.self_ref] = element
            if kind in ("table", "image"):
                for caption in getattr(item, "captions", []):
                    caption_targets[caption.cref] = element.id
            if kind == "image":
                pictures.append(element)
            if kind == "heading" and content and extract_sections:
                section = ParsedSection(
                    id=f"{doc_id}_sec_{len(sections)}",
                    title=content.strip(),
                    level=level,
                    element_ids=[element.id],
                )
                while stack and stack[-1].level >= level:
                    stack.pop()
                if stack:
                    stack[-1].subsection_ids.append(section.id)
                stack.append(section)
                sections.append(section)
            elif stack:
                stack[-1].element_ids.append(element.id)
        for native_ref, target in caption_targets.items():
            if native_ref in by_native_ref:
                by_native_ref[native_ref].caption_target_id = target
        references = _image_references(text, source_format) if extract_images else []
        if len(references) == len(pictures):
            for picture, reference in zip(pictures, references):
                picture.text = "\n".join(
                    filter(None, [picture.text, _reference_text(reference)])
                )
        elif references:
            # Do not guess which placeholder a backend omitted/merged.
            for reference in references:
                elements.append(
                    ParsedElement(
                        id=f"{doc_id}_elem_{len(elements)}",
                        type="paragraph",
                        text=_reference_text(reference),
                        page_number=None,
                        source_anchor=f"element:{len(elements) + 1}",
                    )
                )
        return elements, sections
