# Assigned procedure extraction contract — 2026-11-26

EXT-005's original run remains a failed strict graph-quality check: 81 procedures rather than 80 and 10,002 product assignments rather than 10,000. Its additional `restart verification` concept was grounded in the source, which describes restart verification inside the assigned maintenance procedure. The original ontology's broad description (“A named synthetic maintenance procedure”) did not explicitly distinguish assigned procedures from their verification substeps. The original graph, reports, input documents and count/cardinality oracle remain unchanged.

## Controlled semantic clarification

`tests/synthetic/procedure_contract.py` deep-copies a supplied ontology and changes exactly two descriptions:

- `FixtureProcedure` means an explicitly named and formally assigned procedure. Readings, inspections and verification substeps are not separate procedures unless the source explicitly identifies and assigns them as such. Extraction must not invent a name from an activity phrase.
- `FIXTURE_USES_PROCEDURE` represents that formal assignment, rather than every activity performed within it.

This is model guidance, not an enforced validation constraint. There is no fixture-name allowlist. Labels, keys, property types, endpoints, relationships, normalizers, aliases and blocklists remain identical. The canonical schemas and generated dataset were not edited to fit the result. The original source text remains the same.

Two tests verify independent deep copying, exactly two description changes, normative validation and propagation through the real schema generator. Both pass using the entity server runtime.

## Full workload validation

Evidence directory: `outputs/reports/procedure_contract_benchmark_20261126/`. The separate harness derives from the original benchmark runner and records its code, source hashes, tool schemas, model identifiers, stages and tool outputs. It asserts the disposable URI `neo4j://localhost:17692`, uses only `granularity-graph` / `granularity-ontology`, reads owner-only disposable credentials, and overrides all connection/database/run paths. The root `.env`, generated MCP configuration and user database are untouched.

The workload uses the unchanged benchmark: 10,000 products plus 102 auxiliary rows and a 50-page PDF, public CSV ingestion, actual Docling parsing, all eligible chunks extracted with configured provider/model, visual descriptions, embeddings, retrieval and provenance checks. Warm runtime/model caches mean this is not a cold-setup timing measurement.

The strict expected node/edge counts and one-assignment-per-product checks remain intact. Post-extraction discrepancies are collected without stopping subsequent diagnostics, and any failed check makes the final result an acceptance failure. A separate complete snapshot checks every original non-null node property and every original domain edge/property against the CSV state. Previously absent optional values may be enriched under `preserve_existing`; the original harness's assumption that null notes must remain null is not a protected-value overwrite rule.

### Observed result

**Controlled run passes its graph-quality and preservation checks.** All 50 pages parsed; 75/75 eligible chunks attempted, 74 nonempty and persisted, one empty, zero failed. The configured extraction model remained `gpt-6-luna` with its configured provider; embeddings remained `text-embedding-3-small` (1536 dimensions). The generated live schema contains both narrowed descriptions.

| Check | Result |
|---|---|
| Domain nodes | 20 facilities, **80 procedures**, 10,000 products, 2 sensors; no duplicates/orphans |
| Domain edges | 10,000 MADE_AT, **10,000 USES_PROCEDURE**, 80 OWNED_BY, 2 SENSOR_AT |
| Product assignment cardinality | All 10,000 have exactly one facility and one procedure |
| Original values and edges | All 10,102 original nodes and 20,082 original edges retained; zero changed original non-null properties, endpoints or edge types/properties |
| Extraction/provenance/vector checks | All pass; indexes ONLINE |
| Target answers | 7/7 match unchanged oracles using retrieved graph/section evidence and visual inspection of the MCP-returned diagram |
| Timing | 68.169s to first validated answer; 71.428s measured pipeline; warm caches |

Answer comparison is recorded in `answer_oracle_comparison.json`; it is saved-evidence validation, not an autonomous chatbot quality score. The image-only bypass code was visually read as `BYP-42` from `0091_graphrag_read_node_image_1.png`. All 43 pipeline/preservation checks pass after the diagnostic correction below.

### Initial preservation-check failure and read-only diagnosis

The extra snapshot audit initially compared whole relationship property maps for equality and reported **95 changed edges**. The original edge IDs, endpoints, types and original property values were all intact. Those 95 edges gained only these bookkeeping properties: `__extractionValues` and `__extractionReconcileLock`. Adding provenance/reconciliation metadata is not overwriting an original CSV value.

The initial failed artifacts remain as `summary_initial_snapshot_check.json` and `csv_preservation_initial_snapshot_check.json`. A read-only before/after snapshot comparison verified every original property as a subset of the current map, while still requiring identical edge IDs/endpoints/types. It reports zero missing/changed original values and 95 edges with permitted additive metadata. `csv_preservation.json` records this corrected basis; the isolated harness was corrected for reproducibility. No graph repair, deletion or provider rerun was performed to obtain a pass.

These two added relationship properties are concrete examples for the requested **GRAPH-001 model review**: assess whether reconciliation bookkeeping belongs in a stabilization template and how it affects explaining/querying the customer graph. This investigation does not endorse or redesign that model.

## Scope of the resolution

This is a **fixture/project ontology configuration improvement**, not a global extraction-engine fix or a universal guarantee against over-extraction. The source's intended distinction is now explicit in the extraction contract, and one full stochastic run respected it without relaxing expected counts/cardinality. Other POCs must define their own entity granularity. If verification is itself a formally named/assigned procedure in another project, its ontology should say so.

One successful live run cannot prove that an LLM will never produce an extra concept. The descriptions are guidance rather than a hard constraint. Preserve this controlled variant alongside the original failed run; use it as a regression workload when changing prompts, models or ontology semantics. No broad entity allowlist, name-pattern filter, source rewrite, graph deletion or global prompt restriction was added. The disposable databases and container remain available for owner inspection.
