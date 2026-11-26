# Claude Code smoke test prompt

Open a fresh Claude Code session from this repository, then say:
`Read SMOKE_TEST_PROMPT.md and run the prompt below.`

## Prompt

Use the develop-neo4j-graph skill to test this workspace as an SE building a maintenance POC.

Dataset: `data/synthetic/smoke` under this repository. Resolve all input paths to absolute paths before calling tools. If it is missing, generate it with `scripts/generate-synthetic-dataset.sh --profile smoke`.

Read `docs/product/SYNTHETIC_DATASET.md` first.

Use a fresh disposable database. Preserve existing databases and data. Keep the configured model names unchanged. Never print credentials or include them in reports.

Before paid parsing/extraction/embedding steps, verify `get_neo4j_schema_and_indexes` works against the disposable database. It currently requires APOC Core (`apoc.meta.schema`), which a default neo4j-cli Docker instance does not enable. Record any prerequisite repair explicitly; make changes only to the disposable instance.

Run the full CHATBOT workflow:

1. Ingest the four CSV files using `schemas/ingest_plan.json`.
2. Parse `pdf/maintenance.pdf` with Docling and build section-aware chunks.
3. Use `schemas/ontology.yaml` through the supported ontology import/generation route for entity extraction. Use a separate disposable ontology database where available.
4. Generate embeddings and verify vector/fulltext indexes are ONLINE.
5. Answer the questions in `expected.json` using actual graph/document retrieval. Use `get_ontology` for domain context and PageIndex tools where appropriate.
6. Read the question text first, but compare retrieved answers with the expected answers only after answering. Never use the answer key as retrieved evidence.
7. Validate the final CHATBOT report and save the actual prompts, tool calls, failures and artifact paths under a fresh `outputs/reports/synthetic_smoke_<run-id>/` directory.

Check particularly:

- CSV values survive conflicting document extraction, with proposed values/conflicts recorded.
- `CV-7` and `cv-7` remain distinct sensors.
- Section hierarchy matches the source; report discrepancies rather than correcting the oracle.
- PageIndex tools are hidden before usable lexical content exists and become available when the required graph structure exists.
- Answers include correct citations.
- The diagram-only question uses image evidence.

Do not ingest aliases, lifecycle variants or negative fixtures during this baseline run. Do not fix source code or silently work around failures: record them and explain what blocked you. Do not claim success for failed or skipped stages.

Also report any confusing instructions, unnecessary confirmations or manual steps an SE would struggle with. Leave the disposable graph available for inspection and identify it in the report; do not delete it automatically.
