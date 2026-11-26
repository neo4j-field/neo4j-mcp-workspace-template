# Full synthetic benchmark — 2026-11-24

**Executed with strict quality failures retained.** All seven target answers passed
and the report validator passed, but whole-graph reconciliation did not.

Full workload: 10,000 product rows plus 102 supporting rows, all 50 PDF pages,
527 Elements, 55 Sections and 75 chunks (72 text, 2 table, 1 image). All 75 sources
were selected/attempted: 74 nonempty successes, 1 successful empty, 0 failed. All
75 vectors are 1536d with configured model/input identity; search indexes reached
ONLINE. Models unchanged: `gpt-6-luna`, `text-embedding-3-small`.

## Warm-cache timings

| Stage | Seconds |
|---|---:|
| CSV ingestion | 3.388 |
| Complete CSV graph checks | 1.119 |
| Docling parsing + atomic graph write | 30.235 |
| Chunking + lexical verification | 1.446 |
| Ontology import/generation | 1.341 |
| Full entity extraction | 18.255 |
| Visual descriptions | 2.729 |
| Embeddings + index readiness | 3.313 |
| First answer retrieval/check | 0.035 |

**First validated answer: 61.866s**, measured automatically from ingestion start
with a monotonic clock after saving actual retrieval and comparing it to the
oracle. This includes all source parsing/extraction/embedding, not an early CSV
shortcut. Remaining retrieval took 2.380s; summed timed stages reached the strict
quality stop at 64.269s. Read-only diagnosis/review/reporting followed separately.
The final report timing in `timings.json` includes those pauses and is not pure
machine throughput. Cold setup was not measured.

Context: Apple M1 Max, 10 logical CPUs, 64 GiB RAM; Neo4j 2026.09 Enterprise in
Docker; existing runtimes/Docling assets warm, new databases/indexes; bundled APOC
preflight passed before paid work. Defaults for extraction concurrency were
20 text / 5 visual; one Docling file worker, structured 500-token chunks.
Thirteen resource snapshots observed maximum aggregate harness/child RSS 5.06 GiB
(shared pages may double-count), plus separate Neo4j working-set snapshots up to
1.157 GiB. Docker's 7.748 GiB shared VM ceiling is not a reserved container allocation.
The smoke container/desktop activity remained present. Provider costs/token usage
were not measured. This is one local POC observation, not production throughput.

## Quality findings

- Before extraction: 10,102 nodes / 20,082 domain edges, exact typed/source mappings.
  After extraction: 10,103 nodes / 20,084 domain edges. An additional `restart verification`
  procedure was derived from CASE-24/CASE-40 wording, linked to pumps 00025 / 00041.
  Those products now have two USES_PROCEDURE edges, so strict count/cardinality
  checks fail. This is source-grounded semantic granularity under a broad ontology,
  not an established key-merge bug or invented source text. EXT-005 tracks review.
- All 10,102 original CSV nodes and every original non-null node property were
  compared in full and preserved. Original 20,082 structured edges, endpoint mappings
  and product relationship properties were also verified separately from additions.
  One null note filled from source is allowed enrichment, not an overwrite bug.
- 242 entity-source links touch 115 distinct entities; 107 relationship claims and 75 durable
  completion records match actual successful sources/run/model/fingerprint. No
  duplicate keys or domain orphans. Status entities_created=163 counts keys across
  batches; it is not a new-node/global-uniqueness count.
- All 7 retrieved answers match, including all 20 facility aggregates / five zeros and an
  actual image read of BYP-42 on PDF page 50. This does not assess recall over all 45
  extended case questions. Expected answers were not supplied to extraction.
- Native hierarchy remains partial: 55 sections / max level 4, compared with 54 native
  outline entries/max source level 3. The printed-contents title is an extra heading;
  intended core paths still work. LEX-004 stays open and no correction was applied.

Full evidence: `outputs/reports/synthetic_benchmark_20261124_live_01/` contains
`chatbot_report.md`, `summary.json`, strict failure snapshot, ordered public MCP
calls, `answer_comparison.json`, `independent_audit.json`, original-value/edge
comparisons, actual image, source/input/runtime hashes and resource/timing data.
The timed run stopped at its first strict quality failure; only read-only checks
continued. No result deletion, source modification or provider rerun hid it.

The benchmark instance remains available separately from smoke: container
`synthetic-benchmark-live-20261124`, URI `neo4j://localhost:17690`, HTTP 17490,
graph `benchmark-live`, ontology `benchmark-ontology `. Owner-only temporary connection
file `/tmp/synthetic-benchmark-live-20261124.env` is retained; no credentials are in
reports. User .env/MCP configs/data and existing smoke graph were untouched.
Manual Claude Code smoke remains pending for the user; no automation was created.
