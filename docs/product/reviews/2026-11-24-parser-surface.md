# Parser surface reduction — SURF-003

Removed the experimental `vlm_blocks` parser, its dedicated async orchestration,
three VLM-only creation parameters, mode routing/schema descriptions, workflow
columns and dedicated skill reference. Retained PDF modes are `pymupdf`, `docling`
and `page_image`; extension-selected `document` mode still handles Markdown, TXT,
local HTML/XHTML and DOCX. Old experimental mode requests now fail before a job or
database write. No existing graph data is rewritten.

No dependency was exclusive to the removed parser: PyMuPDF, Pillow, LiteLLM and
Pydantic remain necessary for supported parsing, image descriptions or extraction.
General reading-order, caption and native-section handling stays in the supported
adapters; removing this experiment does not require another layout implementation.

Validation: 31 unit/contract checks passed across public routing/schema rejection,
lexical boundaries, retained PDF parser contracts, document parsers and native
Docling hierarchy. The shared graph skill passes `quick_validate.py`. Historical
review/backlog mentions remain for traceability; live code and workflow guides no
longer advertise the removed mode. No provider calls or user database changes were
needed for this reduction.
