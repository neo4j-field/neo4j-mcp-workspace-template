# Markdown, TXT, local HTML and DOCX

Use for `.md`, `.markdown`, `.txt`, `.text`, `.html`, `.htm`, `.xhtml` and `.docx`.
Text inputs must be UTF-8. Keep CSV in structured ingestion; XLSX, arbitrary JSON,
legacy `.doc` and slide formats are not added by this workflow.

## Parse and chunk

Pass an absolute local file or folder path to `create_lexical_graph`. Extension
routing selects `document` mode automatically, even with the PDF default mode.
Mixed folders may contain supported documents and PDFs; PDF parser choices still
apply to PDFs. `page_image` requires PDFs. Explicit `document` mode is
for non-PDF inputs only.

Poll `check_processing_status` and inspect both completed and failed file counts.
Get version IDs from the results or `list_documents`.

Call `chunk_lexical_graph` afterward. Prefer `structured` for Markdown/HTML/DOCX
with headings. TXT is literal text with no inferred hierarchy; use `token_window`.
`by_page` on pageless sources falls back to document-order token windows.

Native headings/styles supply section levels without a hierarchy LLM call. Review
them if retrieval depends on a specific nesting structure. Lists, tables and
embedded DOCX images are retained. Referenced images remain references: local and
remote assets are not fetched, and HTML scripts/browser rendering are not run.

## Reuse extraction and retrieval

Use the existing schema/ontology generation, key normalization, `embed_chunks`
and `extract_entities` steps on these Chunk nodes. Generate visual descriptions
when embedded image chunks need semantic retrieval, using the configured model.
CSV bridge merging, conflict policy and provenance work through the same path.

Verify with `verify_lexical_graph`; compare the reconstruction with source content.
Plain TXT reconstruction preserves literal text inside a code fence.

Use `get_document_outline`/`get_section_content` for heading-aware sources and
`get_document_content` for TXT/front matter. These tools appear only when usable
lexical content exists; refresh discovery after ingestion if the client caches it.
Follow returned pagination until sufficient evidence has been read.

Cite the source file, heading path and `source_anchor`. Line/element anchors are
logical source references, not physical pages. Page citation fields remain null;
never invent page numbers for DOCX or other pageless inputs. `node_element_id`
can open retained embedded images through `read_node_image`.

For report validation, include document extraction/schema quality checks. The
existing CLI flag is named `--pdf-data-present`; use it for this document layer
too, despite the legacy flag name.

Default source IDs include the extension for these formats. If filenames resolve
to an ambiguous source ID, rename them or import separately with explicit distinct
`document_id` values. Explicit stable IDs can intentionally select version identity.
