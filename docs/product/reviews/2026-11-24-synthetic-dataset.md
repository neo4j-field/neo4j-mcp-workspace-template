# Synthetic dataset delivery and validation

Generated deterministic CC0 maintenance fixtures from one canonical source:

| Profile | Main products CSV | Auxiliary CSV rows | Expected structured graph | PDF |
|---|---:|---:|---|---|
| Smoke | 8 | 6 | 14 nodes / 20 relationships | 4 pages |
| Benchmark | 10,000 | 102 | 10,102 nodes / 20,082 relationships | 50 pages |

Each profile has 37 hashed artifacts plus manifest.json: four CSVs, primary PDF,
Markdown/TXT/HTML/DOCX documents, four extension aliases including true XHTML,
synthetic diagram, font license, CC0 notice, models/Pydantic/Ontology Spec YAML+JSON,
expected answers/counts, alias/blocklist variants, lifecycle revisions and separate
invalid fixtures. Generated files live in `data/synthetic/{smoke,benchmark}` and
are intentionally gitignored; generator, schemas, oracle, renderer and tests are
source-controlled. Regenerate via `scripts/generate-synthetic-dataset.sh`.

The benchmark has 21,630 source words, not 50 pages manufactured by blank padding.
Median page density is about 450 words; the final visual appendix intentionally
contains a diagram-only answer. Per-page/source density basis and actual ranges
are in the manifest. PDFs contain native three-level outlines (9/54 entries),
printed section/page contents, tables and embedded pixels. PDF pages 1/25/50 were
rendered and visually reviewed for layout; unsupported font glyphs fail generation.

## Verified

- 9 generator/canonical/renderer tests: deterministic repeated file hashes,
  exact workloads, complete artifact references, corruption detection, preserved
  evidence on nonempty targets, native DOCX structures, XHTML and pixel-only fact.
- 4 real schema-contract tests: normative ontology JSON/YAML equivalence,
  extraction Pydantic preflight, actual alias/blocklist validators, sensor key
  case distinction, and actual ingest compiler mappings/types.
- 148 file/real-parser checks per profile: all primary formats/aliases, exact
  page counts/native outlines, Unicode, meaningful text, source anchors and TXT
  literal reconstruction. This uses PyMuPDF and native document adapters.
- 23 public CSV-tool checks per profile on separate empty Neo4j 2026.09 Enterprise
  databases: two ingest passes, exact per-label/per-type counts, no orphans,
  bridge answer, relationship properties, scalar/date types, native nulls,
  case-sensitive sensor readings and active-product counts including zero rows.
  Observed two-pass timings: smoke 1.246s; benchmark 4.963s. These exclude setup,
  PDF work, provider work and time to first validated answer.
- Actual Docling PDF conversion with its OCR assets available: final marker,
  sensor evidence and tables complete. The completion guard now rejects partial
  conversion. Exact hierarchy accuracy is recorded separately below.
- 29 focused parser regressions, 7 ingest compiler/null checks and 10 workflow/CI
  contracts passed; relevant new fixtures/checks are registered in CI. Root final
  committed-revision hosted CI remains a release task.

Machine-readable local evidence is retained in
`outputs/reports/synthetic_dataset/`: smoke/benchmark parser and ingest reports,
Docling smoke report and hardware/workload context. These reports contain no
credentials or customer data. Paid model/provider calls in this pass: **zero**.

## Findings, fixes and remaining acceptance

1. **INGEST-002 fixed:** pandas missing sentinels reached query parameters as NaN.
   Convert missing values to native None before forwarding public ingestion;
   numeric/boolean/date mapping and structured property ownership stay intact.
2. **LEX-002 fixed:** an OCR asset download failure returned a partial Docling
   result (20 elements/5 sections) which the adapter accepted. Both PDF/native
   adapters now require SUCCESS with no conversion errors before using content.
   Actual complete conversion succeeded once assets were available.
3. **Hierarchy quality observation:** Docling treats checklist/printed-contents
   labels as extra headings on this PDF and can assign deeper levels than the
   source's intended three. The oracle remains unchanged; exact hierarchy/path
   quality is a manual acceptance case, not passed by counting headings.
4. **LEX-003 open:** source native outlines are present, but `extract_toc` does not
   currently produce a distinct TOC-entry graph. Implement or retire that surface
   as a separate small decision; do not claim PDF-source TOC equals tool support.

This delivery creates and verifies the test material. Full live extraction,
embeddings/vector/fulltext/PageIndex questions, all lifecycle/failure scenarios,
manual Claude Code QA and the complete cold-setup/time-to-first-validated-answer
baseline have **not** been run on this new dataset. Expected answers are an oracle,
not retrieved evidence. Each feature/scenario has explicit applicability and
unsupported/manual cells in the generated manifests and [SE walkthrough](../SYNTHETIC_DATASET.md).

Cleanup: the dedicated synthetic acceptance container was removed after report capture. Generated fixtures/reports remain; the user database, actual .env and generated client configs were untouched.

LEX-003 follow-up: owner chose removal. The ineffective extract_toc parameter and active guidance were removed; PageIndex continues to use Sections. Historical findings above record the pre-removal audit.
