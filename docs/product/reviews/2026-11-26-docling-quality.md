# Docling section quality investigation — 2026-11-26

LEX-004 concerns the distinction between source headings and visually similar labels. The adapter preserves Docling's classification and heading levels; it does not invent the checklist or contents text. Controlled real-model tests isolate the extra sections to Docling's interpretation of bold labels.

## Controlled inputs and results

Generator: `tests/synthetic/docling_quality.py`. The three one-page PDFs contain the same seven intended headings, hierarchy, body facts, checklist and native PDF outline. Only the two label styles and the presence of printed contents differ. Original smoke and benchmark inputs and their oracles are unchanged. All three generated pages were rendered and visually inspected; content fits without clipping.

Runtime: **Docling 2.152.0; docling-core 2.108.0**, with the workspace's existing lexical parser and native heading hierarchy enabled. These are real layout/OCR/heading conversions, without a database or extraction/provider calls.

| Variant | Label styling | Printed contents | Native headings | Extra headings | Intended levels/parents | Adapter preserves native |
|---|---|---|---:|---|---|---|
| clear_headings | regular body text | yes | 7 | none | all correct | exact |
| ambiguous_labels | bold | yes | 9 | Operator checklist:, Document outline and pages | all correct | exact |
| no_contents | bold | no | 8 | Operator checklist: | all correct | exact |

All conversions returned `success`. The oracle checks ordered heading occurrences, levels and full ancestor paths, including the repeated title `Details`. It distinguishes “all intended headings correct” from “exact hierarchy”; the latter fails for both bold-label variants. The clear variant passes both. Removing printed contents removes that extra heading only; it does not resolve the checklist classification. The controlled checklist is classified at level 3, demonstrating that its exact inferred level also depends on layout context.

Evidence is saved in `outputs/reports/docling_quality_20261126/`: generated PDFs, rendered PNGs, expected hierarchy, raw native headings, adapter sections, full parsed results and `investigation.json`. Generated evidence is intentionally ignored by Git; the generator and this report are tracked sources.

The original four-page smoke PDF was also re-parsed from an unchanged copy. Raw Docling produced exactly the previously reported 50 elements and 11 sections, including `Operator checklist:` at level 5 and `Document outline and pages` at level 4. The adapter preserved both raw native levels exactly; all nine intended headings and parent paths were correct. Baseline evidence is under `outputs/reports/docling_quality_20261126/original_smoke/`.

## Decision for stabilization

Keep native hierarchy as the default and describe its limits explicitly: Docling infers headings from document layout, and bold source labels can become sections. A successful parse is not a guarantee that the hierarchy exactly matches author intent. This evidence does **not** justify a label blacklist, a font/level cutoff, or silently deleting headings absent from the PDF outline. Those rules can remove legitimate sections in customer documents; outlines may also be partial or stale. No production parser behavior or graph schema changes were made for this investigation.

For SEs, inspect `get_document_outline` before relying on inferred paths. For incorrect heading levels/parents, retain the existing explicit hierarchy correction workflow (`assign_section_hierarchy`). This tool adjusts hierarchy; it does **not** reclassify or remove false-positive heading elements, so it does not close the exact-hierarchy discrepancy shown here. For editable fixtures/documents, making body labels visually distinct from headings is a demonstrated authoring workaround. Native PDF outline preference can be considered later as an explicit user-selected policy with separate acceptance tests; it is not enabled automatically.

**SURF-004:** N1 does not make the existing hierarchy correction tool redundant. Keep it pending the requested model/tool simplification review. Its explicit correction path remains useful for level/parent mistakes, although these controlled variants do not require such a correction. The need for a separate false-heading correction policy remains open if exact author-intended hierarchy is a release requirement.

## Verification and reproduction

Four focused tests validate that the comparison detects wrong parents for repeated titles, distinguishes extras from missing headings, catches missing repeated headings, and produces deterministic PDFs with native outlines:

```sh
uv run --no-project --python 3.12 --with reportlab==4.4.9 \
  --with python-docx==1.2.0 --with Pillow==13.0.0 --with PyYAML==6.0.3 \
  python -m unittest tests.synthetic.test_docling_quality -v
```

Generate controls with the same dependency environment, then investigate using the lexical runtime (Docling model assets must be cached or downloadable):

```sh
python -m tests.synthetic.docling_quality generate outputs/reports/docling_quality_20261126
LITELLM_LOCAL_MODEL_COST_MAP=True mcp-neo4j-lexical-graph/.venv/bin/python \
  -m tests.synthetic.docling_quality investigate outputs/reports/docling_quality_20261126
```

The real-model run is an investigation command, not a mandatory network/model-dependent unit test. The focused tests do not assert that future Docling releases reproduce today's classification errors. Re-run the controlled investigation after a Docling upgrade and compare evidence before changing the acceptance decision.
