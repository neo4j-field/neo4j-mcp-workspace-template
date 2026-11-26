# Claude Code follow-up acceptance prompt

Run after the core smoke test. Open Claude Code in this repository and say:
`Read FOLLOWUP_ACCEPTANCE_PROMPT.md and run the prompt below.`

## Prompt

Use the develop-neo4j-graph skill to finish the targeted acceptance checks that
the existing Aster maintenance smoke run did not cover. This is a follow-up,
not another complete CSV ingestion or benchmark.

Read `docs/product/SYNTHETIC_DATASET.md` and the QA-001 section of
`docs/product/RELEASE_CHECKLIST.md`. Dataset: `data/synthetic/smoke`; resolve paths
to absolute paths for tools. Keep configured models unchanged. Never print
credentials or change model/API settings or generated MCP configuration files.

Use only the existing smoke/test database, after checking the target. Preserve
its current CSV entities, documents, extraction claims and reports. Do not clear
the graph or re-ingest the CSVs. Save evidence under a fresh
`outputs/reports/claude_followup_<run-id>/` folder. Do not edit server source code
or invent helper implementations to make an unsupported feature appear to pass.

### 1. Docling PDF hierarchy and PageIndex

- Parse only `pdf/maintenance.pdf` with `parse_mode="docling"`, using a new,
  unique document_id such as `aster-docling-qa-<run-id>`. Preserve the earlier
  Markdown and PyMuPDF versions. Verify all four pages completed.
- Build structured chunks. Compare the actual Sections, parent links and chunk
  heading paths against `source.json` and the PDF's native outline. Record extra,
  missing or incorrectly nested headings. Do not call assign_section_hierarchy
  or modify the fixture to hide discrepancies.
- List available GraphRAG tools. If navigation tools are missing, record that
  before asking me to reconnect neo4j-graphrag. Continue after reconnect, but
  mark automatic discovery as failed rather than treating reconnect as a fix.
- Use list_retrieval_documents → get_document_outline → get_section_content
  against the NEW Docling document. Answer the reset-duration/valve question
  from its Thermal reset section, with exact section/element IDs and correct
  one-based PDF page citations. Do not fall back to the Markdown document.
- Read Long reference with a small max_chars (for example 1200). Follow each
  returned next.offset/text_offset until has_more=false; verify REF-16 is reached.
  Respect actual tool bounds: content limit is at most 25, max_chars at most 20000.

### 2. Ontology file used for extraction

- Use the existing user-created ontology database registered through
  NEO4J_ONTOLOGY_DATABASE. Do not create another database or change credentials.
  If it is unavailable, report the configuration/permission blocker rather than
  substituting another extraction route and calling this test passed.
- Call setup_ontology_db and import_ontology_spec with the actual contents of
  `schemas/ontology.yaml`. If a compatible `synthetic-maintenance` ontology already
  exists, inspect/reuse it without overwriting; distinguish reuse from a fresh
  import in the results. Do not create duplicate conflicting type definitions.
- Generate/review the Pydantic schema from the ontology. Verify four entity and
  four relationship types, matching keys/endpoints; named keys normalize with
  whitespace/lowercase, while CV-7 and cv-7 retain distinct case-sensitive keys.
  DATE is deliberately excluded from extraction, while remaining in CSV data.
- Extract using ontology_name (not schema= pointing at the previous Python file).
  Restrict source_ids to the NEW Docling document's chunks and use a fresh
  extraction_scope with property_policy="preserve_existing". Wait for completion
  and report eligible/attempted/nonempty/empty/failed/persisted source counts.
- Verify the stored CSV action and both sensor identities remain unchanged;
  inspect proposed values/conflicts and entity/relationship source provenance.
  Record any extra entities or edges rather than deleting them or changing the
  expected results. Do not claim alias/blocklist execution merely because their
  definitions exist; record those as separate untested cases unless exercised.

### 3. Ontology export and supported roundtrip

- Export the imported ontology with export_ontology_spec to YAML and JSON; save
  both and validate the normative spec. Compare labels, keys, scalar types,
  relationship endpoints and supported normalization/alias/blocklist semantics.
- Separately export the original
  `outputs/schemas/aster_maintenance_schema.py` DIRECTLY with
  export_extraction_schema_ontology(schema_path=ABSOLUTE_PATH, format="yaml")
  and format="json". This additive tool requires the updated entity server;
  do not restart an active test merely to load it. Validate and compare the
  resulting supported scalar key/type/endpoint/normalization contract.
  export_ontology_spec(ontology_name=...) exports the Ontology DB: it does not
  establish arbitrary Python-schema export. Custom Python validation logic outside
  the supported subset must fail explicitly. If the running server lacks the new
  tool, record this check as pending updated-server acceptance; do not manually
  reconstruct an ontology and call the capability passed.

### 4. File-backed get_ontology context

- This test must use the actual ontology FILE, not only the imported Ontology DB.
  get_ontology cannot accept an arbitrary file path as a tool argument.
- Configure the existing GraphRAG ONTOLOGY_FILE setting to the absolute path of
  `schemas/ontology.yaml`. If a temporary .env edit is required, change only this
  nonsecret setting, preserve any previous value, and never hand-edit generated
  MCP config files. Ask me to reconnect only neo4j-graphrag when the setting changes.
  If this cannot be configured through the supported route, report the blocker.
- Call get_ontology and verify the returned context is file-backed. Ask it which
  relationship connects products to procedures, which property represents its
  priority, and how named keys versus sensor keys normalize.
- Then answer where Fixture Pump 00001 is made and which procedure it uses:
  get_ontology for domain context first, then actual read-only Cypher for values.
  Do not call get_schema/get_neo4j_schema_and_indexes routinely for domain meaning;
  physical schema/index inspection remains available if genuinely needed.
- Record the tools and provenance of the context. Restore the prior ONTOLOGY_FILE
  setting after this test and reconnect as needed, unless I ask to keep it.

### 5. Acceptance notes

Save one table with PASS / PARTIAL / FAIL / BLOCKED / UNSUPPORTED for each test,
plus actual tool calls, prompts, database/document IDs, result paths, citations,
failures and SE usability friction. Distinguish functionally correct retrieval
from exact hierarchy accuracy and automatic discovery. Identify any acceptance
item still open; successful report formatting is not proof of feature support.
Keep test data available for inspection; do not tear down databases automatically.
