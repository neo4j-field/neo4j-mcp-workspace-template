# Synthetic extraction golden set

`synthetic_extraction.json` contains three hand-authored maintenance notes and
their expected entities and relationships. It contains no customer material and
the reference labels were not generated or judged by an extraction model.

Use the notes as source chunks in a disposable Neo4j database and run entity
extraction with `synthetic_schema.py` (pass its absolute path to the tool).
Export one candidate JSON object with the same `cases` structure
(`id`, `entities`, `relationships`). Entity keys may differ in case or surrounding
space; relation type, direction, labels, and endpoint keys must match. Include an
empty result for every case, including the negative case.

Compare a candidate with the reference:

```bash
python tests/golden/evaluate.py /absolute/path/to/candidate.json
```

To report a quality change against a previous extraction, add
`--baseline /absolute/path/to/previous-candidate.json`. The output includes
per-case and aggregate precision, recall, F1, and the metric deltas. Store the
model identifier, schema version, and run date beside each candidate so the
comparison is reproducible. CI tests the reference and scorer without making
provider calls; the real extraction result must be supplied by an integration
or manual run.

## Run the real extractor directly

No Neo4j data is needed. From the repository root, using the entity-server Python:

```bash
mcp-neo4j-entity-graph/.venv/bin/python -m tests.golden.run_extraction \
  --output /absolute/path/to/new-candidate.json \
  --baseline /absolute/path/to/previous-candidate.json
```

Omit `--baseline` for the first run. This command makes three small provider
requests using `EXTRACTION_MODEL` from the environment/`.env`. It never substitutes
a model, writes Neo4j data, or sends expected graph facts to the model. Any failed
source aborts without publishing a candidate. Use a new filename for every run.
Candidates record model, UTC timestamp, schema hash, and reference hash; mismatched
baseline hashes are rejected. The standalone evaluator can compare changed schemas
explicitly when needed; the runner's repeat comparison intentionally holds them fixed.

`baselines/20261124_gpt6_luna_{baseline,repeat}.json` are two real extraction runs,
not copies of the reference. Both scored entity and relationship precision/recall/F1
of 1.0; deltas were zero. The set covers four entities and two relationships across
three tiny notes, including no-completed-inspection and empty-output cases. This
is a regression seed, not a measure of general extraction quality. CI tests the
runner with stubs; new provider runs are explicit and may incur provider charges.
The repository reference was prepared during agent-assisted development; no
independent human domain review is asserted by these results.
