# GraphRAG document-tree and ontology retrieval — 2026-11-24

## Scope and sources

Implemented in the local **separate** GraphRAG Git checkout
`mcp-neo4j-graphrag` (starting revision `19e03d`), plus small lexical writer/reader
changes in this template. The nested repository is intentionally gitignored by
the template; a template commit alone will not ship its changes. The owner selected
separate delivery: [GraphRAG draft PR #2](https://github.com/neo4j-field/mcp-neo4j-graphrag/pull/2)
on `codex/graphrag-tree-ontology`. Setup and both proxy GraphRAG mounts share the
full Git SHA in `mcp-neo4j-proxy/src/mcp_neo4j_proxy/graphrag_revision.txt`.
New clones fetch exactly that commit; dirty checkouts at another revision are
preserved and setup stops with an actionable message. Published package/Desktop
artifact alignment remains a release task.

Used the supplied `genai-workshop-lakehouse/pageindex-graph` outline/read pattern and
read the actual [text2cypher ontology agent](https://github.com/neo4j-field/text2cypher-ontology-agent)
`tools/get_ontology.py`, prompt and movie ontology. Did not reuse its future
`db.ontology.get()` assumption.

## Implemented tools

- `list_retrieval_documents`: active document discovery with literal name/ID search.
- `get_document_outline`: real section roots, full paths, bounded depth, section
  order/page ranges and explicit pagination/drilldown.
- `get_section_content`: original section elements, optional descendants, precise
  source/page citations and continuation inside long individual elements.
- `get_document_content`: whole-document/front-matter reading, explicit flat and
  visual-page fallback. Selected images can be opened via `node_element_id`.
- `get_ontology`: full pinned-spec file context or a projection of the template's
  existing Ontology DB. Supports exact IDs/names/semantic aliases, description
  search, relationship endpoint closure and bounded context/index fallback.

Navigation uses exact active document identity and filters inactive chunk versions.
PageIndex tool discovery is conditional: document tools require active lexical
content; outline/section tools also require section-to-element structure. Empty,
business-only or unavailable databases hide those tools while unrelated tools stay
visible. Availability is checked on each discovery and direct navigation call.
Clients that cache tools must refresh discovery/reconnect after graph changes.
All new tools use read access and timeouts. No new model/provider requests or APOC
are needed. This is agent-driven outline navigation, not an embedded PageIndex
reasoning model. Existing vector/fulltext entry points remain available.

Ontology file validation retains the full normative 1.1.0 semantics, including
cardinality, value constraints and extensions, independently of the narrower
extraction adapter. Identifying/implied/optional labels remain distinct. Declared
semantics are explicitly not evidence of populated data or installed indexes.
File access is configured at startup through `ONTOLOGY_FILE`/`--ontology-file`;
the model cannot supply a filesystem path. Optional ontology connection/name
settings support the existing template database. No entity-server dependency.

## Lexical changes

New parses store document-wide `Element.order`, `Section.order` and descendant-
inclusive `Section.pageStart/pageEnd` (0-based). Outline reads can use these fields
without scanning section bodies. The reader uses numeric page order and explicit
section order rather than lexicographic IDs. Existing graphs need no migration;
legacy unavailable section ranges remain null. Native hierarchy and reading order
were tested with opaque IDs across pages 0, 9 and 10.

## Validation and boundaries

- GraphRAG: **23 unit checks + 10 isolated database checks passed** from the package's
  final standalone test location (`tests/unit`, `tests/integration`).
- Template: **17 lexical regressions + 2 hierarchy/navigation database checks**
  passed; **10 workflow/CI contracts** passed.
- Loaded the reference agent's actual movie ontology and verified `Film` resolves
  to `Movie`, retaining its declared properties/constraints.
- Bundled normative schema inclusion was verified in the built GraphRAG wheel.
- Ruff checks on new modules/tests and both repositories' diff checks passed.
- GraphRAG now has standalone unit/integration CI and publication requires that
  suite; the template CI includes the new lexical navigation test. Hosted runs
  passed on pinned revision `d575b0cb94fb4484272cbd23700640321bef6668` (unit, integration and CodeQL).

Database checks used disposable Neo4j 5.26 Enterprise on a separate localhost port,
with UUID-owned fixtures and no user graph or credential changes. Final cleanup
left zero nodes and the disposable container was removed. No provider
calls/costs. Pagination assumes an unchanged selected version; traversal caps at
32 section edges. No section summaries, cross-document-link extraction, themes or
retrieval-quality benchmark were added. The complete live CSV/PDF/report test,
package delivery and Desktop alignment remain release-checklist work.

## Delivery verification

- Draft PR: https://github.com/neo4j-field/mcp-neo4j-graphrag/pull/2
- Initial delivery pin: `d575b0cb94fb4484272cbd23700640321bef6668`.
- A fresh temporary clone fetched exactly the pinned commit.
- The proxy wheel includes the shared revision resource; its actual `uvx --from`
  Git source launches successfully.
- A namespaced proxy using that exact transport passed hidden → visible → hidden
  discovery as UUID-owned lexical data was created/deleted in a disposable DB.
- 11 setup fixtures plus 10 workflow/CI contracts passed; setup preserves existing
  edits and fails clearly rather than forcing a dirty checkout to a new revision.
- The PR remains draft. Package publication and rebuilt Desktop artifact alignment
  are still pending; only source/setup/proxy pins have changed.

## Onboarding follow-up

The shared source pin is now `e096736059d7dfa0182b49ba07297cf83898d7be`. Expected missing-schema notifications
are suppressed only for capability probes; actual database failures still log and
normal retrieval diagnostics are unchanged. Latest local/hosted validation: **24
unit checks and 10 database checks passed**, with CodeQL green. Full real-provider
CSV/PDF acceptance is recorded in the [live report](2026-11-24-live-release-acceptance.md).

## Additional document formats

The shared pin is now `eaab5bc576ac2709689dc162ed28bf4225affada`. Pageless retrieval returns source format and source anchors with null page numbers. All **25 unit and 11 database checks passed**; hosted unit, integration and CodeQL checks are green for this commit.

## Current index API alignment

The shared pin is now `cd755ebfc7fb28afa153b156595aea693eaa86af`, adding index readiness checks, version-aware vector/fulltext SEARCH and indexed filtering where available. Local validation:28 unit checks and12database integrations on each of Neo4j5.26 and2026.09. See [index report](2026-11-24-search-indexes.md).
