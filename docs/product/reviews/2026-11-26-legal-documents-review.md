# Legal document POC review — 26 November 2026

Reviewed the saved legal_agreements chatbot report, data model, generated Python
schema, retrieval implementation, reporting instructions and report validator.
No graph changes or re-extraction performed. The original execution trace was
not supplied: reported tool executions and answer accuracy cannot be independently
established from the report alone. This review is about tool and evidence quality,
not legal interpretation of the contracts.

## Findings

- The pipeline reportedly completed, but validator exit 0 proves report structure,
  not factual correctness, graph quality or completeness of retrieval history.
  The current skill's singular Query field and shallow presence checks explain
  why incomplete multi-method records pass.
- Q4 claims vector corroboration but omits exact search arguments and returned
  chunk identity. Q3 omits the table-read call/identity. Q6 mentions fulltext in
  prose but omits complete named arguments/results. Q7 puts two queries together
  without separate calls. Additional answer details are not all derivable from
  the displayed Cypher; they need their actual supporting retrieval steps.
- Q6's displayed MATCH/CONTAINS does not query the fulltext index. That is a
  retrieval-selection issue, not evidence of a broken index. A fulltext search
  for the known clause labels is a better first lookup; a bounded literal scan
  remains useful for punctuation/redaction auditing. The report claims a separate
  fulltext call, but the supplied artifacts do not establish its actual execution.
- Q6 truncates returned text to 900 characters and returns no chunk/source ID.
  It has no active-version filter, exact document identity, ordering or explicit
  coverage accounting. Similar omissions affect other retrieval/count queries.
  Q8 counts matching chunks, not redacted monetary terms; punctuation matching
  is a useful literal audit but does not prove all forms of redaction are covered.
- Direct tests of the generated schema show _coerce_money('$2.5 million')=2.5,
  _coerce_money('$250K')=250, _coerce_money('EUR 10 million')=10. Numeric success
  is therefore not sufficient semantic validation. _coerce_percent('50/50')=50
  also accepts an ambiguous expression. These demonstrate unsafe accepted inputs,
  not proof that these particular strings reached the extractor in this run.
- Case-preserving keys explain case-only organizations. Alias Organizations and
  Agreement title fragmentation reveal underspecified identity/context, not a
  MERGE defect. Name-only identity can also merge different parties or agreements.
  Alias resolution must be scoped by agreement; Landlord/Company are not global
  organization identities. City/county/state distinctions are not automatically
  duplicate entities. The report's 45 referenced agreements need sampling before
  calling all of them genuinely distinct.
- 1,504 conflict-bearing provenance links deserve a property/value breakdown.
  Calling them mostly descriptions or harmless requires evidence. Likewise,
  reported creation counters must be distinguished from actual distinct graph
  creations and mentions; exact key uniqueness and zero orphans are weak semantic
  quality checks.
- No styled DOCX headings means no native section tree in this run. Current
  mode_for_path routes DOCX to native document parsing regardless of requested PDF
  mode: recommending a Docling flag is not an implemented remedy. Word numbering,
  style and outline-level evidence should be inspected before proposing a small
  explicit heading policy. Preserve truthful pageless anchors.
- Recovered scratch imports/Cypher syntax errors, brittle report formatting,
  optional unconfigured ontology and unrelated remote MCP failures need separate
  classifications. “None affected the final graph” is stronger than the evidence;
  runtime success coexists with observed identity and normalization risks.

## Proposed small changes, in order

1. Replace singular Query with an ordered per-question retrieval trace. Record
   step ID, tool, exact named arguments (Cypher plus parameters), purpose, selected
   returned source IDs/anchors, brief supporting excerpts and limitations. Include
   failed/empty attempts that influenced the answer; distinguish executed from
   proposed queries. Shared calls can be referenced by ID. Keep full responses in
   a local JSON evidence file and a readable summary in Markdown. Never fabricate
   missing historical calls; label a new rerun separately. No graph audit nodes.
2. Teach the existing report validator to check trace structure, method/call
   coverage and resolvable evidence references. Accept useful Markdown tables and
   equivalent section headings. Keep the claim limited: even a consistent trace
   does not independently prove execution or answer truth.
3. Prefer indexed fulltext for lexical discovery; vector for semantic retrieval;
   Cypher for structured relationships/aggregations. Retrieve bounded original
   evidence after candidate selection. Scope every stage to exact documents and
   active versions. Do not infer absence from a top-k list. Fulltext currently
   lacks a document-filter argument: assess a small optional filter rather than
   relying on post-filtering a tiny global result list.
4. Add a lightweight pre-extraction identity/numeric review: canonical source
   agreement identity, document-scoped aliases, appropriate key normalization,
   explicit entity-vs-role rules and adversarial money/percent examples. Reject
   uncertain conversions or retain raw text; do not silently take the first
   number, invent currency or normalize ambiguous dates. Support custom generated
   validators carefully without introducing a legal-specific framework.
5. Replace “validated” with separate statuses for execution, structural checks,
   evidence coverage and semantic findings. Make report recommendations respect
   actual parser capabilities and the owner's simple graph-model preference.

For this existing run, first recover real call history if available; otherwise
run a clearly labeled read-only retrieval audit and create a report supplement.
Verify monetary properties and high-impact aliases before any reviewed merge.
Do not re-extract or canonicalize the user's database automatically.

Fulltext reference: Neo4j's official Cypher Manual, current Full-text indexes
(https://neo4j.com/docs/cypher-manual/current/indexes/search-indexes/full-text-indexes/).
The existing GraphRAG helper already selects SEARCH on supported releases and
legacy procedures on older versions; this run does not justify rewriting it.
