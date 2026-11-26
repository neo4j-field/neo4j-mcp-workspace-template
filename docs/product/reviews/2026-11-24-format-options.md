# Practical input format options — 2026-11-24

**Implementation update:** Markdown, literal TXT, local HTML/XHTML and DOCX are now
implemented. See the [implementation and live verification](2026-11-24-document-formats.md).
The original assessment below records the design tradeoffs before implementation.

**Yes: Markdown, plain text, local HTML and DOCX are sensible small next adapters.**
The installed Docling 2.152.0 already provides their conversion backends, but the
workspace's current PDF wrapper does not support them end to end. This is an
assessment only; no format implementation, dependency or model download was added.

[Official Docling supported formats](https://docling-project.github.io/docling/usage/supported_formats/)
lists Markdown, HTML/XHTML, DOCX, PPTX and XLSX. Its JSON input is specifically a
serialized **Docling Document**, not an arbitrary application's JSON data. Plain
text is listed as an output format there; installed Docling 2.152.0 additionally
maps `.txt`/`.text` and `text/plain` into its Markdown input backend
(`docling/datamodel/base_models.py:161,231`). That installed behavior is evidence
for a possible adapter, not proof that the workspace already accepts text files.

## Suggested order and honest limits

| Input | Relative effort | Preserve / cite | Important boundary |
|---|---|---|---|
| Markdown | Small first feature | Heading hierarchy, ordered text/lists/tables, source path + section/element anchor | No physical pages. Embedded links remain source content; do not automatically crawl targets. |
| TXT | Smallest parsing adapter | Ordered paragraphs and source path + paragraph/line anchor | Usually no real sections. Keep literal text semantics; routing TXT through Markdown can reinterpret markup-like content, so test or use a tiny direct text adapter. |
| Local HTML/XHTML | Small next feature | Native headings, main text, lists/tables, source path + section/element anchor | Static local documents only initially; no browser rendering, JavaScript execution, authenticated crawling or website mirror promise. |
| DOCX | Small-to-medium | Heading styles, paragraphs/lists/tables and source element/section anchors | Word layout pagination depends on rendering; do not invent page numbers. Text boxes, tracked edits, complex tables and images need representative checks. |
| PPTX | Medium, after the above | Slide index, shape/element order, slide-based citations | Slide semantics are real, but extracting shapes is not equivalent to understanding visual layout. Diagrams, charts, embedded media and speaker notes need explicit fidelity checks. Export-to-PDF is an existing-workflow alternative today. |
| XLSX | Structured ingest first | Sheet + cell/range/row anchors; typed values, keys and relationships | Do not flatten business tables into lexical prose by default. Small workbook-to-structured-ingest adapter is more useful than pretending spreadsheet navigation is section navigation. Complex workbooks/formulas remain separate. |
| Application JSON | Structured ingest first | Record keys and JSON-pointer paths | Needs an explicit mapping for arrays/objects/keys/relationships. It is not Docling JSON; no automatic arbitrary JSON semantics. |

After the minimal adapter work, existing chunking, embeddings, entity extraction,
CSV bridge merging and retrieval can be reused for document text. Their reuse must
be verified with a small end-to-end fixture; page images, coordinates and physical
page citations are not features these formats automatically inherit.

## What currently prevents changing only the file extension

- `server.py:311` discovers only `*.pdf`/`*.PDF`; preflight calls `count_pdf_pages`,
  and progress estimates are page-based. Accepting a single non-PDF path does not
  make the later stages compatible.
- `parsers/docling_parser.py:98–122` configures PDF-specific pipeline options, then
  unconditionally calls `fitz.open` for page dimensions/images. Its missing-provenance
  fallback also assumes a page index.
- `models.py:61` requires an integer `ParsedElement.page_number`. `graph_writer.py`
  attaches generic elements through `Page` nodes; `graph_reader.py` and section/page
  chunkers use that path. Pageless content needs direct document/section membership,
  with absent page data rather than fake page zero.
- New PageIndex content tools already recognize direct document elements, but the
  writer, chunking, reconstruction verification and citation output still need a
  focused pageless-source fixture. PPTX should say **slide**, not PDF page.

## Smallest useful implementation scope

Start with MD + TXT, then local HTML + DOCX using the same narrow conversion helper.
Keep the existing PDF flow intact. Add only source format and source anchor fields
needed for truthful citations, allow absent physical page data, and teach the
existing writer/reader path to handle document elements without pages. Preserve
native headings/order; disable PDF cropping/options for non-PDF sources. One tiny
fixture per format should prove extraction, sections where present, chunks,
retrieval continuation and honest citations. No parser-unification project, format
auto-detection framework or new service is necessary to make this useful for SEs.
