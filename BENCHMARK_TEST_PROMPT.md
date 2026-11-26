# Claude Code benchmark test prompt

Run the smoke test first. Open a fresh Claude Code session from this repository, then say:
`Read BENCHMARK_TEST_PROMPT.md and run the prompt below.`

## Prompt

Use the develop-neo4j-graph skill to benchmark this workspace as an SE building a maintenance POC. Read `docs/product/SYNTHETIC_DATASET.md` first. If the latest smoke test has unresolved failures, report them before starting an expensive benchmark; do not silently ignore them.

Dataset: `data/synthetic/benchmark` under this repository. Resolve all input paths to absolute paths before calling tools. If it is missing, generate it with `scripts/generate-synthetic-dataset.sh --profile benchmark`.

This profile contains 10,000 product CSV rows plus 102 supporting rows, and one 50-page PDF. Expected CSV graph counts are 10,102 nodes and 20,082 relationships. Documents provide additional evidence about a subset of those entities; extraction is not expected to rediscover all 10,000 products.

Use fresh disposable graph and ontology databases, separate from the smoke run and all existing data. Keep configured model names unchanged. Never print credentials or include them in reports.

Before paid parsing/extraction/embedding steps, verify `get_neo4j_schema_and_indexes` works against the disposable database. It currently requires APOC Core (`apoc.meta.schema`), which a default neo4j-cli Docker instance does not enable. Record any prerequisite repair explicitly; make changes only to the disposable instance.

Run the full CHATBOT workflow on the complete baseline inputs:

1. Record the Git revision, platform/hardware, Neo4j and relevant package versions, configured models/providers and cache state. Record generation/setup separately from the workflow timer. If setup/model assets are already warm, label them warm; do not call this a cold-setup measurement. Do not delete shared caches or reconfigure credentials to manufacture a cold run.
2. Start a monotonic timer immediately before the first ingestion operation. Ingest all four CSV files using `schemas/ingest_plan.json`. Verify the exact structured counts, property types, relationship properties and absence of orphans/duplicate keys.
3. Parse all 50 pages of `pdf/maintenance.pdf` with Docling and build section-aware chunks. Report actual page/element/section/chunk counts and hierarchy discrepancies.
4. Import `schemas/ontology.yaml`, generate the supported extraction schema and extract entities/relationships from every eligible chunk. Report eligible, attempted, successful, empty and failed source counts. Preserve existing structured values and record conflicts/provenance.
5. Embed every eligible chunk. Verify vector/fulltext index definitions and ONLINE readiness before retrieval. Record embedded/skipped/failed counts.
6. Answer every question listed in `expected.json` using actual retrieval. Read question text first, but consult expected answers only after answering. Use `get_ontology` for domain context, vector/fulltext search for suitable questions and PageIndex outline/section navigation where appropriate. Use image evidence for the diagram-only answer and citations for document claims. Record the analytical active-product counts, including facilities with zero active products.
7. Record elapsed time to the first answer that has been retrieved, compared with its expected result and confirmed correct with source evidence. This timer includes ingestion, parsing, extraction, embedding and retrieval. Record total elapsed time separately after all questions and final report validation.
8. Validate the final CHATBOT report. Save per-stage durations, observed resource use where measurable, question results, actual tool calls, failures and artifact paths under a fresh `outputs/reports/synthetic_benchmark_<run-id>/` directory. Mark unavailable measurements explicitly rather than estimating them.

Do not ingest alternative document renderings, aliases, lifecycle variants or negative fixtures during this baseline. Do not sample/truncate rows, pages or chunks, change models/parsers, or drop difficult questions to claim completion. If limits or errors prevent a complete run, retain partial evidence and report the exact incomplete scope. Do not change source code or silently work around failures.

Also report SE usability friction and the stages that dominate elapsed time. Do not infer production throughput from one local POC run. Leave disposable databases available for inspection and identify them in the report; do not delete them automatically.
