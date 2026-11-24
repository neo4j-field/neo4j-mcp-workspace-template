# Extraction lifecycle audit — 2026-11-24

## EXT-002: implemented

EXTRACTED_FROM is provenance, not proof that the extraction finished. The previous
selector skipped any source with one incoming provenance link and repeatedly
processed successful empty results. It did not detect changed source/schema/model.

Selection now hashes the actual classified source inputs and compares a durable
completion record with a fingerprint covering schema source, extractor package
source, LiteLLM version, model, provider routing, source label, pass settings and
property policy. Only complete, non-invalidated evidence is reused. Empty successful
outputs also receive completion evidence. Before writes, a new attempt invalidates
older completion links for its selected sources. Completion is published only after
all source attempts and graph writes succeed, including relationship-count checks.
Legacy provenance without completion evidence is reprocessed.

Rapid, equal-size schema edits exposed another identity issue: Python could load
stale timestamp/size-cached bytecode. The loader now compiles current source bytes,
with a same-size/same-timestamp regression. Fingerprints appear in start/status
responses and graph completion records.

### Verification

- 15 affected fast identity, parser, entity, normalization, golden-schema and runner
  tests passed; 13 workflow/release/scorer tests passed.
- 14 isolated Neo4j 5.26 integration checks passed: five new completion scenarios,
  two existing coverage/restart scenarios, six bridge/schema/relationship scenarios,
  and one ontology workflow.
- New scenarios cover empty-result reuse after restart; legacy partial provenance;
  changed text, schema, model and policy; forced extraction failure invalidation;
  and missing relationship endpoints preventing false completion.
- No model requests or operations on the owner's configured graph were needed.

### Boundaries

The selector currently reads source payloads before comparing hashes. Bounded IO,
completion-record retention and concurrent-write isolation remain scaling/write
work. Run overlapping source extractions serially. Completion records are local to
the entity-extraction stage, not a cross-server workflow ledger.

## EXT-001: reproduced, not fixed

A disposable two-generation audit extracted an item, an obsolete property, another
entity label and a relationship. The second schema omitted the property, second
entity label and relationship; forced extraction with overwrite returned only the
retained item. Both jobs reported complete, but the graph still contained:

- one stale removed-label node;
- one stale removed relationship;
- the obsolete property with value `old`.

This confirms that skip correctness and replacement correctness are distinct.
MERGE plus SET += is additive even with overwrite enabled. Completion records do
not claim to repair the stale-output defect.

Safe replacement needs explicit ownership of generated node/relationship/property
contributions per source and extraction scope, plus publication only after new
output is ready. It must preserve CSV/shared entities, evidence from other sources,
and user edits. Legacy provenance does not prove ownership, so deleting every node
linked to a source or every property in an old schema would be unsafe. Introduce
ownership for new contributions and an explicit legacy migration/refusal path;
never infer deletion ownership from a matching label or key prefix.

The audit used only private Ext001Audit labels and cleaned them afterward. This
reproduction should become a passing replacement regression when cleanup lands,
not a test that permanently asserts stale data is acceptable.


## Follow-up

The reproduction above is historical evidence. EXT-001 has since been implemented;
see `2026-11-24-owned-replacement.md`. Publication is now all-or-nothing for selected
sources; successful partial source output is no longer committed after a sibling
source fails. Legacy ownership is refused rather than inferred.
