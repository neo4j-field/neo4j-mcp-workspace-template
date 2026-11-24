# ADR-001: Normalize three parsing strategies behind one contract

- Status: accepted
- Priority: deferred until after stabilization
- Date: 2026-09-10

## Context

The lexical graph needs broad document support without losing specialized behavior.
PyMuPDF is a fast path for conventional PDFs. Docling supplies richer structural
conversion and OCR-backed format support. Page-image treats each PDF page visually,
which is valuable for presentation PDFs and other layout-heavy documents.

## Decision

Keep all three strategies as first-class parser adapters:

`source -> parser selection -> parser adapter -> ParsedDocument -> graph writer`

They share a canonical `ParsedDocument` contract and one graph writer. They do not
share an implementation or get forced into the same intermediate extraction logic.
Users may choose `auto`, `pymupdf`, `docling`, or `page_image`. Parser choice and
configuration are stored as provenance.

The canonical model must represent text, hierarchy, tables, images, and
format-appropriate locations. Location is polymorphic: a page and bounding box for
PDF, a slide for presentations, a section path for flowing documents, and similar
native anchors for future formats.

## Consequences

- New parsers do not duplicate Neo4j graph-writing logic.
- Page-image can retain page imagery and vision-derived content.
- Parser output can be regression-tested independently of Neo4j writes.
- The canonical model must avoid collapsing every document into PDF semantics.
- CSV/XLSX remain structured-ingest-first unless lexical treatment is explicitly
  requested.
