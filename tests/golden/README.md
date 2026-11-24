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
