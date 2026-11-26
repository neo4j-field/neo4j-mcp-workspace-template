# Synthetic workspace acceptance dataset

This maintenance POC is generated from one deterministic fictional domain model.
It contains no customer data. It is a test workload and answer key, not evidence
that a model has successfully extracted every fact.

Generate the small profile first:

```bash
scripts/generate-synthetic-dataset.sh --profile smoke
scripts/generate-synthetic-dataset.sh --profile benchmark
```

The default folders are `data/synthetic/smoke` and `data/synthetic/benchmark`.
A nonempty target is refused to preserve earlier evidence: choose another output
folder for a new generation. Generator dependencies are isolated from the server
environments. See the generated manifest for canonical counts and hashes.
The benchmark contains **10,000 rows in products.csv**, plus **102 auxiliary node
rows** (20 facilities, 80 procedures, 2 sensors); it is not 10,000 total CSV records.
Its PDF is exactly 50 pages. Pageless formats carry equivalent logical content.

Use only the manifest's primary input files for a normal run. Alternative formats
are equivalent renderings: they share domain entities and are not independent
facts. Extension aliases, revision variants and negative cases are deliberately
outside the default ingestion folder. Never recursively ingest the whole dataset.

## A short SE walkthrough

Use a fresh disposable database. Load the pinned source revision in Claude Code;
keep configured model names unchanged and use absolute source paths. The schema/index
inspection tool requires APOC Core (`apoc.meta.schema`); verify it is available on
the disposable instance before paid work. A default neo4j-cli Docker instance
does not enable it automatically. Before a
paid run, `./setup.sh --check-model` checks a small structured response. Do not
paste credentials into prompts or reports.

Start with this prompt, replacing `<dataset>` with the absolute generated folder:

> Build a maintenance graph from `<dataset>/csv` and one primary PDF. Use the
> provided schema artifacts and source mappings. Preserve structured values when
> document wording conflicts. Show ingest counts, run extraction and answer the
> canonical questions from expected.json. Cite source pages. Validate the CHATBOT
> report. Keep exact tool calls and evidence; do not treat expected answers as
> retrieved evidence.

`schemas/ingest_plan.json` describes each CSV operation. Compile each node query
from its `node` definition; compile each relationship query from its
`endpoint_data_model` and `relationship` definitions. This matters because one
file's `name` column is another file's `facility_name` or `procedure_name` endpoint.
Use the actual workspace ingest compilers rather than upstream query drafts.
DATE values belong to the structured model. The extraction projection intentionally
omits `commissioned`: current extraction/ontology adapters support scalar
STRING/INTEGER/FLOAT/BOOLEAN, not DATE extraction.

For extraction choose one route per run:

- File route: convert `schemas/extraction_data_model.json` with
  `schemas/key_normalization.json`, or use `schemas/extraction_schema.py` directly.
  Named identities normalize with strip/lowercase. Sensor codes strip whitespace
  but retain case, so `CV-7` and `cv-7` remain distinct.
- Ontology route: set up a separate Ontology DB, import `schemas/ontology.yaml`
  (JSON is equivalent), then generate models and extract using
  `ontology_name="synthetic-maintenance"`. Aliases and blocklists use the template
  extension declared in that file. Test them with the separate variant sources.

Then repeat the document side using Markdown, TXT, HTML/XHTML and DOCX in isolated
runs. Ask the same text questions; use source anchors for pageless citations.
Compare each result against the canonical facts, not against another model's
opinion. Text-layer parsers are not expected to answer raster-only diagram facts.

## Feature and assertion matrix

| Feature | Fixture / action | Expected assertion |
|---|---|---|
| Source mappings and native types | Four CSVs and ingest plan | Correct node keys, typed numeric/boolean/date fields, relationship properties on relationships; counts match expected.json. |
| CSV optional values | Empty notes fields | Canonical missing notes must become absent/null in the graph, never float NaN. Verify the public pandas ingestion path, not only csv.DictReader. |
| Shared identities and case | Same named bridge entities; CV-7/cv-7 sensors | No named duplicates after normalized merges; two distinct sensor identities. |
| Equivalent formats | One primary file per format; alias folder | Same documented text facts; aliases exercise routing without accidental duplicate default ingestion. |
| Native structure | Headings, nested/repeated titles, lists, table, TOC | Native hierarchy/order where format supports it; TXT has literal text and no invented headings. |
| Visual input | Synthetic diagram and table | Image/page-image path can inspect raster-only facts; PDF text-only path must report unavailable evidence. DOCX has an embedded image; linked HTML/Markdown images stay references. |
| Unicode and long content | Multilingual text and long sections | Exact TXT reconstruction, preserved non-ASCII text, bounded retrieval continuation. PDF font support is checked separately. |
| Four chunking strategies | Structured/token-window/by-section/by-page | Coverage, order and truthful source references; by-page on pageless documents uses documented fallback. |
| Conflict policy | Procedure CSV action versus document sentence | CSV action remains under preserve_existing; source link records proposed wording/conflict. Explicit overwrite is a separate isolated run. |
| File schema | Pydantic extraction projection | Entity labels, key types, relationship endpoints and normalization remain valid. |
| Ontology interchange | JSON/YAML import→DB→generate→export | Normative validation and supported semantic roundtrip; no silent dropping of unsupported semantics. |
| Ontology context | Configure get_ontology file or DB | Agent uses declared entities, aliases and relationship paths for text-to-Cypher; physical inspection remains available. |
| Retrieval | Exact identifier, paraphrase, domain filter | Fulltext/vector hits identify the right source; POPULATING/FAILED indexes are not query-ready. |
| PageIndex navigation | Outline→section→subsection→continuation | Correct source text with pages or anchors; tools hidden without usable lexical graph. |
| Lifecycle | lifecycle/v1 then v2, same explicit document_id | Atomic active-version switch; failed replacement preserves v1. In document-only extraction, removed assignment can be removed; CSV-owned claims remain protected in mixed runs. |
| Cache/identity | Repeat embed/extract; modify source/schema/model in isolated test | Exact repeats skip appropriate work; changed identities invalidate caches or reject incompatible index spaces. No silent model substitution. |
| Scoped reset | Select one source family and rebuild/delete | Expected source removed/rebuilt; unrelated fixture graph remains intact. |
| Negative cases | negative/failure_cases.json | Actionable explicit errors, no false job completion and no unintended graph writes. Fault injection is a harness action, not an input-file capability. |
| Analytical mode | Aggregate products/facility, priority and allocation | Typed counts/sums match canonical expected results and an ANALYTICAL report validates. |

## Manual acceptance prompts

Keep prompts, inputs, exact tool calls, generated artifacts and pass/fail outcomes.
These are manual acceptance tasks; merely generating the files does not pass them.

1. **Ontology extraction:** “Import this ontology file and extract the primary
   document. Verify names, keys, types and relationship endpoints against the
   ontology. Show the actual import and model-generation steps.”
2. **Ontology export:** “Export the Ontology DB as JSON/YAML and validate it, then
   compare supported semantics with the original.” Separately test arbitrary
   Pydantic-schema export; that route is unresolved and must not be marked passed
   because Ontology DB export works.
3. **Ontology retrieval:** “Use the configured ontology file through get_ontology
   to answer which procedure belongs to a product's facility. Explain the declared
   relationship path, execute the query and cite actual result evidence.”
4. **Hierarchy:** “Parse the PDF with Docling. Compare nested headings and repeated
   titles with HAS_SUBSECTION links and full chunk heading paths.”
5. **PageIndex:** “Browse the outline, read a nested section, and continue through
   long content. Cite original pages. On the TXT version, use source anchors and
   do not invent page numbers or section structure.”
6. **Rebuild:** “Re-ingest lifecycle/v2 under the same source family. Verify the
   active version and source-owned extraction changes. Then demonstrate that a
   failed write leaves the previous version active in a disposable test.”

For the benchmark record hardware, parser, Neo4j/server revision, configured
provider/model, cache state, elapsed generation/setup/ingest/extract times, memory
and storage, and time to the first validated answer. Parsing times alone are not
time-to-answer. Do not imply a throughput target before measuring it.

## Repeatable validation commands

File hashes and source consistency (stdlib only):

```bash
python3 -m tests.synthetic.validate data/synthetic/smoke
```

Real supported parsers, without a database or paid provider calls:

```bash
uv run --project mcp-neo4j-lexical-graph --extra docling python -m tests.synthetic.validate data/synthetic/smoke --parse --report outputs/reports/synthetic_dataset/smoke-parser-validation.json
```

Public CSV-tool validation requires an **empty disposable database**, with its
connection already provided through environment variables. The database argument
must match the explicitly set `NEO4J_DATABASE`; nonempty databases are refused.
This ingests twice, checks idempotence, expected counts/answers, relationship
properties, native DATE/BOOLEAN/INTEGER/FLOAT values and absent optional strings.
It leaves fixture data for inspection; delete the disposable database/container
when finished. Do not point it at a customer database.

```bash
uv run --project mcp-neo4j-ingest python -m tests.synthetic.check_ingest data/synthetic/smoke --disposable-database YOUR_DISPOSABLE_DATABASE --report outputs/reports/synthetic_dataset/smoke-ingest-validation.json
```

Replace `smoke` with `benchmark` for the larger profile. These checks do not make
LLM calls, validate extraction quality, or measure time to first validated answer.
Those are the next live workflow tests, using the supplied expected answers as an
oracle after retrieval, never as retrieved evidence. The reference workload's
source/page density is recorded under `documents.text_metrics` in the manifest.


## Known findings from fixture validation

The fixture includes a real PDF outline and printed section/page contents. That
is source coverage. The ineffective `extract_toc` option was removed (LEX-003);
there is no separate TOC-entry graph. PageIndex uses the heading-based Section hierarchy.
Native Docling also classified the printed contents/checklist labels as additional
headings on the smoke PDF; its observed depth exceeded the three intended source
levels. Compare against `source.json` and the native PDF outline during manual
hierarchy acceptance. Do not normalize the answer key to a parser's mistakes.

Fixture validation exposed and fixed two data-loss issues: blank CSV cells now
become native nulls rather than pandas NaN, and Docling adapters reject partial
conversions instead of accepting truncated documents after a stage failure.

## Latest live smoke result

The CSV+PDF smoke completed with seven matching answers and a validated report. Extraction, visual descriptions, embeddings, vector/fulltext search, PageIndex and image reading used the real configured providers. APOC had to be enabled explicitly; exact Docling hierarchy quality and manual Claude Code QA remain open. See the [live smoke evidence](reviews/2026-11-24-synthetic-smoke-live.md). The warm full benchmark has now run: all 50 pages / 75 sources processed, 7/7 answers passed, but one extra procedure and two links failed the strict graph oracle. See [benchmark evidence](reviews/2026-11-24-synthetic-benchmark-live.md); first validated answer took 61.866s.
