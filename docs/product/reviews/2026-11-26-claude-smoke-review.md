# Claude Code smoke review — 26 November 2026

User supplied Claude Code completion summary and the report at
`outputs/reports/aster_maintenance_chatbot_report.md`. Initial user prompt invoked
the graph skill with the smoke dataset, rather than the longer saved smoke prompt.
Choosing Markdown + PyMuPDF and file-based convert_schema was therefore a valid
core POC route, but does not establish the planned Docling/ontology acceptance.

Read-only independent checks through the exact `.mcp.json` GraphRAG command:

- Report validator: valid=true, seven records, exit0.
- Current graph: two facilities, two procedures, eight products, two sensors;
  domain edge counts 2 owned/8 made/8 uses/2 sensor-at, matching the report.
- 48 EXTRACTED_FROM links use the configured gpt-6-luna model.
- Two active documents: Markdown document mode with8sections and PDF pymupdf,
  four pages. Both display names are maintenance; IDs are distinct.
- **Fresh tools/list includes all four PageIndex tools plus get_ontology.**
  Actual get_document_outline returned all8Markdown headings and intended nested
  paths. Current source HEAD equals the shared pin cd755eb; no missing-build
  explanation is supported by these checks.

Evidence is saved under `outputs/reports/claude_smoke_review_20261126/`, including
the fresh tool listing, actual outline and read queries. No data, model settings,
credentials or generated configuration were changed. No paid calls were made.

## Main finding: discovery/refresh, not absent implementation

The statement that tree tools were not exposed in this server build is too strong.
The conditional middleware filters each tools/list by current graph topology,
but does not send a tools/list_changed notification when another server ingests
lexical data. Initial hiding plus a long-lived client catalog is a likely cause.
We have not proven what Claude cached in that session. E1-REFRESH tracks an actual
client reproduction and fix; merely passing fresh-client visibility is not enough.

Temporary next check: reconnect only neo4j-graphrag in Claude Code, then ask it to
list/browse aster-maintenance-md_v1 and read its Thermal reset section using
PageIndex with citations. Do not ingest, extract or clear the existing graph again.

## Acceptance still open

- Docling PDF section extraction (run used PyMuPDF, Markdown supplied headings).
- Ontology-file import/generation/extraction and file-based get_ontology context;
  run used convert_schema Python instead.
- Extraction-schema-to-ontology export, particularly arbitrary Python input.
- Real-client PageIndex navigation and dynamic visibility refresh.
- Negative/lifecycle/alias/blocklist scenarios (not baseline requirements).

The seven answer matches are Claude's reported result; this review independently
re-ran structural report validation and graph count/provenance checks, not every
original retrieval or image call. Report validation proves completeness, not
independent answer truth.

Small report corrections: lexical PART_OF direction is Chunk→Document, not the
reverse shown in its Mermaid. Clarify that initial text chunks and promoted visual
chunks are different counts. The active-only aggregation works for this smoke but
would omit zero-active facilities in the benchmark; use OPTIONAL MATCH when those
must be included. Section-aware/by_section chunking already exists; merged
structured chunks are not evidence of a missing feature, and PageIndex can read
original sections independently of chunk merging.


## User follow-up: actual Claude Code PageIndex pass after reconnect

User reports direct use of the three tools after reconnecting neo4j-graphrag:

1. list_retrieval_documents, query aster-maintenance; both documents returned.
2. get_document_outline, document aster-maintenance-md_v1, depth5; selected
   aster-maintenance-md_v1_sec_3 at Operations → Details → Thermal reset, level3.
3. get_section_content with include_descendants=true;423characters,4elements,
   has_more=false,fallback_used=false.

Answer12minutes/CV-7 is supported by anchor element:21 (_elem_20, explicit reset
sentence) and element:23 (_elem_22,12-minute duration versus unrelated wait).
Page fields were null for Markdown, with source anchors and no invented pages.
No fallback, ingestion, extraction or mutation occurred. This agrees with the
independent local outline check. The functional Markdown PageIndex route is now
manually passed. Automatic visibility refresh remains a confirmed practical gap;
Docling PDF and long-content/client pagination acceptance remain separate.


## Docling PDF follow-up: run 20261126-113305

Reviewed `outputs/reports/claude_followup_20261126-113305/run_summary.md` and
`hierarchy_comparison.json`; parsed all three JSON evidence files successfully.
This is saved Claude Code/manual evidence, not another graph mutation or paid run.

Accepted functional PDF checks: all 4 pages, 50 elements, 11 sections, 9 structured chunks;
all 9 native-outline headings and intended parents correct; PDF-only Thermal reset
navigation answered 12 minutes / CV-7 with page 1 citations; 4 pagination calls completed
Long reference through REF-16 on page 3, has_more=false. Existing graph/documents and
48 extraction links preserved. Chunk size 400 explains a different chunk count from
the earlier 500-token automated smoke.

Strict hierarchy equality remains false: checklist level 5 and printed-contents
level 4 are additional sections and affect chunk paths. LEX-004 remains open.
Navigation tools were already available, so automatic discovery is not established
and E1-REFRESH remains open. No ontology/extraction/export tests were performed;
those QA-001 items remain pending. The document-tree retrieval part of QA-001 is
now manually passed for both Markdown and Docling PDF, including full pagination.


## Ontology follow-up: run 20261126-115402

Reviewed the saved run summary and parsed all three JSON evidence files.
Independently validated that ontology_export.yaml/json parse to the same document
and pass the bundled normative validator with four node/four relationship types.
No database writes or paid provider calls were made by this review.

Manual supported-route passes: existing ontology DB setup/fresh import, generated
schema, ontology_name extraction restricted to nine Docling chunks (seven nonempty,
two empty, zero failed), original values/domain graph preserved, source conflicts
and relationship claims, YAML/JSON semantic roundtrip, and file-backed get_ontology
plus actual domain Cypher. File context reported source=file; the temporary
ONTOLOGY_FILE setting was restored to unset and user reconnect remains necessary.

Direct arbitrary Python-schema export is unsupported/open (ONT-002), distinct from
the passed DB export. Alias/blocklist definitions roundtrip but their dedicated
runtime cases were not manually exercised. Earlier notes listing these supported
ontology checks as pending are superseded by this evidence. LEX-004 and E1-REFRESH
remain open; no full QA-001 completion or release sign-off is claimed.
