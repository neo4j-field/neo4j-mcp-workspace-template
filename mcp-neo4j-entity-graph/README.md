# MCP Neo4j Entity Graph Server

[![PyPI version](https://badge.fury.io/py/mcp-neo4j-entity-graph.svg)](https://pypi.org/project/mcp-neo4j-entity-graph/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

MCP server for extracting entities and relationships from graph nodes using LLM structured output, creating entity graphs directly in Neo4j.

**Supports 100+ LLM providers via LiteLLM** (OpenAI, Anthropic, Google, Azure, Bedrock, Ollama, etc.)

## Features

- **Dual extraction pipeline**: Text-only (LLM) and visual (VLM) extraction auto-routed per chunk
- **Grammar-enforced structured output**: Pydantic models used as `response_format` — the LLM cannot violate the schema
- **Async background processing**: Long extractions run in background with job tracking
- **Multi-provider LLM support**: Use any LLM via LiteLLM (OpenAI, Claude, Gemini, etc.)
- **Schema-driven**: Define entity types and relationships to extract
- **Provenance tracking**: `EXTRACTED_FROM` relationships link entities to source chunks
- **High parallelism**: Configurable concurrency (text: up to 50, VLM: up to 50)
- **Batched writes**: Optimized Neo4j writes (configurable batch size)
- **Incremental**: Only processes nodes without prior extraction (unless `force=true`)
- **Multi-pass ready**: Architecture supports entity-only, relationship-only, and corrective passes (v2)

## Tools

### `convert_schema`

Converts data model output from the Data Modeling MCP to a Pydantic extraction schema.

**Parameters:**

| Parameter | Required | Description |
|-----------|----------|-------------|
| `modeling_output` | Yes | JSON output from the Data Modeling MCP server |
| `output_path` | Yes | Path to save the Pydantic `.py` file (e.g. `/path/to/schema.py`) |

**Output:**
- `{output_path}` — Strongly-typed Pydantic models used as `response_format` for LLM structured extraction

The `.py` file can be customized before running extraction:
- Add `Literal` types to constrain categorical fields (phase, status, therapeutic area...)
- Add `@field_validator` for normalization (strip legal suffixes, resolve aliases...)

### Ontology Graph Spec import/export

Run `setup_ontology_db` once, then use `import_ontology_spec(content=...)` for YAML or JSON with
`schema: https://neo4j.com/docs/ontology-graph-spec/1.1.0/schema.json`.
Validation uses the bundled, pinned normative schema offline. Import creates a new
ontology atomically; existing ontology, type, alias-map or blocklist names cause an
actionable error. Then use the existing `generate_schema_from_ontology` or
`extract_entities(ontology_name=...)` workflow. Export with
`export_ontology_spec(ontology_name="my-poc", format="yaml")` (`json` also works).

To export a Python extraction schema created by `convert_schema`, call
`export_extraction_schema_ontology(schema_path="/absolute/path/schema.py", format="yaml")`.
Save the returned content as an ontology file for file-backed GraphRAG `get_ontology`,
or pass it to `import_ontology_spec`. This export uses no database or LLM and creates
no graph metadata. Loading the Python input executes trusted code, as extraction does.

Python export supports the generated scalar contract, descriptions, required fields,
optional `None` defaults, scalar keys, endpoint bindings and `strip()` / `strip().lower()`
validators. Exact identity is retained through extension normalizers `strip` and
`strip_lower`; existing `whitespace` and `lowercase` normalizers also collapse internal
spaces and retain their existing behavior. Arbitrary Python schemas are not losslessly
convertible: custom validators, serializers, model configuration, constrained/Literal/Enum
fields, aliases and meaningful defaults are rejected with a field-specific error.
For a schema generated from an ontology with richer normalizers, export the source
ontology with `export_ontology_spec` instead. The interchange covers JSON extraction
and graph semantics, not Python-only input types or output-wrapper naming.

The extraction subset supports STRING/INTEGER/FLOAT/BOOLEAN properties, one key per
node and one source/target node type per relationship. Template normalizers, alias
maps, blocklists and composed names round-trip through the namespaced
`extensions.custom.neo4j-mcp-workspace-template` extension. Unsupported semantics
are rejected before import writes, including compound keys, extra labels, temporal/
list/vector types, cardinalities and arbitrary constraint/index deployment. The
adapter preserves extraction semantics for this subset; it does not deploy a spec
as database DDL. Spec semantic aliases differ from value-normalization alias maps.
Ontology IDs must be filename-safe for the existing generated-schema cache.
Export canonicalizes spec identifiers to database names. YAML anchors/aliases and
unrecognized custom metadata are rejected rather than silently discarded.

### `extract_entities`

Extracts entities and relationships from graph nodes using LLM. Returns immediately with a job ID.

The tool auto-detects chunk types and routes accordingly:
- **Text chunks** (`type="text"`): sent to LLM with text only
- **Image/Table chunks** (with `imageBase64`): sent to VLM with text + image
- **Page nodes** (`:Page` label with `imageBase64`): sent to VLM with text + page image

**Parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `schema` | required | Path to the Pydantic `.py` file generated by `convert_schema` |
| `source_label` | `"Chunk"` | Label of source nodes (`Chunk` or `Page`) |
| `force` | `false` | Re-extract all eligible sources; otherwise reuse only matching successful completion records |
| `text_parallel` | `20` | Max concurrent text extractions |
| `vlm_parallel` | `5` | Max concurrent VLM extractions |
| `batch_size` | `10` | Chunks to batch before writing to Neo4j |
| `model` | env var | LLM model (defaults to `EXTRACTION_MODEL`) |
| `pass_type` | `"full"` | `full`, `entities_only`, `relationships_only`, `corrective` |
| `pass_number` | `1` | Pass number for multi-pass extraction |

### `check_extraction_status`

Monitor background extraction jobs.

Coverage is explicit in every job status: `eligible_sources`, `selected_sources`,
`sources_attempted`, `sources_succeeded`, `sources_empty`, `sources_failed`, and
`sources_persisted`. Blank or invalid structured responses are retried; exhausted
sources are listed in `failed_source_ids`/`failure_details` and make the job
`failed` rather than allowing a false successful completion. A valid structured
response containing no matching entities is counted separately as `sources_empty`.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `job_id` | None | Specific job to check. If omitted, returns all jobs. |

### `cancel_extraction`

Cancel a running extraction job.

| Parameter | Required | Description |
|-----------|----------|-------------|
| `job_id` | Yes | Job ID to cancel |

## Quick Start

```python
# 1. Convert schema from Data Modeling MCP
convert_schema(
    modeling_output='{"nodes": [...], "relationships": [...]}',
    output_path="data_models/my_schema.py"
)
# Creates: my_schema.py (Pydantic models, ready for customization)

# 2. (Optional) Open my_schema.py and add Literal constraints / field_validators

# 3. Extract entities (runs in background)
extract_entities(
    schema="data_models/my_schema.py",
)
# Returns: {"job_id": "abc123", "status": "started", ...}

# 4. Check progress
check_extraction_status(job_id="abc123")
# Returns: {"status": "extracting", "chunks_completed": 45, ...}

# 5. Re-run extraction (incremental — only unprocessed nodes)
extract_entities(schema="data_models/my_schema.py")

# 6. Force re-extraction even when source and configuration are unchanged
# Schema changes are detected automatically; force is not required for them.
extract_entities(schema="data_models/my_schema.py", force=True)
```

## Generated Pydantic Models

`convert_schema` generates a `.py` file with strongly-typed Pydantic models. The `ExtractionOutput` class is sent to the LLM as `response_format`, meaning the LLM output is grammar-constrained — it literally cannot produce values outside the schema.

```python
class DrugEntity(BaseModel):
    _node_label: ClassVar[str] = "Drug"
    _key_property: ClassVar[str] = "name"

    name: str = Field(..., description="Drug name")
    dose: Optional[str] = Field(default=None, description="Dosage")

    @field_validator("name", mode="before")
    @classmethod
    def _normalize_name(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v

class TreatsRel(BaseModel):
    _relationship_type: ClassVar[str] = "TREATS"
    drug_name: str = Field(..., description="Drug name")
    disease_name: str = Field(..., description="Disease name")

class ExtractionOutput(BaseModel):
    drugs: list[DrugEntity] = Field(default_factory=list)
    treats: list[TreatsRel] = Field(default_factory=list)
```

## Customizing the Schema

After running `convert_schema`, open the `.py` file and add constraints before extraction:

### Literal constraints (normalize categorical fields)

```python
from typing import Literal

class ClinicalProgramEntity(BaseModel):
    # Forces the LLM to pick from these exact values — no more "Phase III" vs "Phase 3"
    phase: Optional[Literal["Phase 1", "Phase 2", "Phase 3", "Registration", "Approved"]] = Field(
        default=None,
        description="Clinical phase — map Phase I→Phase 1, Phase II→Phase 2, Phase III→Phase 3"
    )
```

### Field validators (normalize entity keys to avoid duplicates)

```python
import re

_LEGAL_SUFFIX_RE = re.compile(r",?\s*(Inc\.?|Ltd\.?|AG|SE|GmbH|Pharmaceuticals?)\s*$", re.IGNORECASE)

class CompanyEntity(BaseModel):
    @field_validator("name", mode="before")
    @classmethod
    def _normalize(cls, v):
        if isinstance(v, str):
            v = v.strip()
            while True:
                cleaned = _LEGAL_SUFFIX_RE.sub("", v).strip()
                if cleaned == v:
                    break
                v = cleaned
        return v
```

> **Important:** Apply the same normalization to the corresponding relationship field (e.g. `company_name` in `DevelopsRel`) so that Neo4j `MERGE` keys always match.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `NEO4J_URI` | `bolt://localhost:7687` | Neo4j connection URI |
| `NEO4J_USERNAME` | `neo4j` | Neo4j username |
| `NEO4J_PASSWORD` | (required) | Neo4j password |
| `NEO4J_DATABASE` | `neo4j` | Neo4j database name |
| `EXTRACTION_MODEL` | `gpt-6-luna` | Default LLM model for extraction |
| `OPENAI_API_KEY` | - | Required for OpenAI models |

## Usage with Cursor

Add to your `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "neo4j-entity-graph": {
      "command": "uv",
      "args": [
        "--directory", "/path/to/mcp-neo4j-entity-graph",
        "run", "mcp-neo4j-entity-graph"
      ],
      "env": {
        "NEO4J_URI": "neo4j://127.0.0.1:7687",
        "NEO4J_USERNAME": "neo4j",
        "NEO4J_PASSWORD": "your-password",
        "OPENAI_API_KEY": "your-api-key",
        "EXTRACTION_MODEL": "gpt-6-luna"
      }
    }
  }
}
```

## Performance

Previously tested on pharma pipeline PDFs with `gpt-5.4-mini`:

| Mode | Concurrency | Time | Entities | Relationships |
|------|-------------|------|----------|---------------|
| Text-only | 50 | 107s | 1,584 | 1,257 |
| VLM (page images) | 50 | 114s | 1,597 | 1,378 |

## Architecture

```
server.py           - MCP tools (convert_schema, extract_entities, check/cancel)
job_manager.py      - Async job tracking, progress, cancellation
base_extractor.py   - Shared: prompts, parsing, Pydantic model loading
text_extractor.py   - Text-only LLM extraction (high parallelism)
vlm_extractor.py    - Vision+text VLM extraction (configurable parallelism)
schema_generator.py - Pydantic model code generation from data model
models.py           - Internal types (ExtractionSchema, ClassifiedChunk, etc.)
```

## Graph Schema

After extraction, your Neo4j database will contain:

```
(:Entity)-[:EXTRACTED_FROM]->(:Chunk)
(:Entity)-[relationship]->(:Entity)
```

Example query:

```cypher
MATCH (e)-[:EXTRACTED_FROM]->(c:Chunk)-[:PART_OF]->(d:Document {name: "my-doc"})
RETURN labels(e)[0] as type, count(e) as count
ORDER BY count DESC
```

### Mixed CSV/PDF bridge keys and property conflicts

`convert_schema` accepts `key_normalization`, a map from entity label to `strip`
(default, preserves case) or `strip_lower`. The same normalization is generated
for the entity key and every relationship endpoint referring to it. Match this
policy to structured ingest keys; do not lowercase case-sensitive identifiers.
Ontology-based schemas continue to use their configured normalizer chains.

`extract_entities` now defaults to `property_policy="preserve_existing"`: it fills
missing entity/relationship properties and retains existing non-null values, including CSV
values. To intentionally replace values, pass `property_policy="overwrite"`.
In either mode, null proposals never explicitly delete external/structured values.
Missing/null fields withdraw this scope's prior owned assertions during replacement.
This is a change from the previous unconditional overwrite behavior. `force=true` selects
sources for re-extraction; it does not override the property policy. Entity writes use
Cypher dynamic property assignment (Neo4j 5.24 or newer).

Each `EXTRACTED_FROM` link stores `proposedPropertiesJson` (JSON of the proposed
entity properties), `conflictingProperties` (property names differing from the
stored values before the write), and `propertyPolicy`. Inspect these fields when
validating a run. They describe the latest write to that source link, not a full
property-level history. Relationship proposals and conflicts are recorded on
`EntityExtractionClaim` nodes linked to their source with `CLAIM_SOURCE`.
Both node and relationship properties use the selected property policy. With
preserve mode, conflicting contributions keep an existing supported value; if its
supporting source is withdrawn, a remaining source can supply the replacement.
Review conflicts before using results as authoritative facts.

### Durable completion and skipping

Extraction publishes `(:EntityExtractionRun)-[:PROCESSED_SOURCE]->(source)` only
when all selected sources and their graph writes succeed. Successful empty outputs
also receive completion evidence. Failed, interrupted or legacy provenance-only
runs do not qualify for skipping. A new attempt invalidates older completion
links for its selected sources before writing, so an unsuccessful forced attempt
cannot leave an older marker that hides partial writes.

Reuse requires both a source-input hash and an extraction fingerprint matching
schema bytes, extractor package source, LiteLLM/Pydantic/Neo4j driver versions, model, provider routing,
source label, ownership scope, pass configuration and property policy. The fingerprint is
returned at job start and in status. Source payloads are currently read before
hash comparison, including images; reducing repeated payload transfer and retaining
bounded completion history are future scaling work. Completion records are stage
local, not a cross-server workflow ledger.

Updated schemas/inputs are selected without force. Legacy provenance is not proof
of completion: sources with missing/incomplete ownership metadata are refused
before replacement rather than skipped or automatically claimed as owned.
Serialize jobs touching shared canonical entities while broader write/scaling
hardening is pending.


### Scoped replacement and ownership

`extract_entities` accepts `extraction_scope`, a stable pipeline name reused across
schema/model revisions, and `source_ids`, an optional list of source Chunk/Page IDs.
The default scope is the absolute schema path or ontology name, combined with the
source label. Different scopes and sources retain separate contributions.

Partial duplicate records from one source are combined before publication;
publication order is stable by source ID rather than API completion time.
All model results are staged first. Source inputs are checked again under publication
locks; changed/deleted inputs abort instead of publishing a stale result. If every
source succeeds, one Neo4j transaction withdraws the selected sources' old contributions in that scope, writes the new
entities and relationships, and publishes completion. Failed extraction publishes
no partial domain results. Missing endpoints or other write errors roll back
cleanup and new writes together. Empty successful results withdraw old output too.
Cancellation before publication preserves the old domain graph; a completed commit
cannot be undone by a later cancellation request.

The writer tracks properties it introduced and objects it created with reserved
`__extraction*` metadata. Source links include `ownershipVersion`, `extractionScope`,
`runId` and `extractionFingerprint`. Relationship claims identify source, scope,
physical relationship, proposed values and run. Cleanup preserves other sources'
contributions, pre-existing objects, external edits and structured ownership. Only
unchanged, unreferenced, extraction-created objects are garbage-collected.
Objects with foreign properties, labels or relationships are conservatively kept.
Supported generated scalar values are strings, integers, floats and booleans;
custom non-JSON values are conservatively retained when identity cannot be proven.

The CSV query compiler now declares `__structuredSource` and
`__structuredProperties` on imported nodes/relationships, including imports after
extraction with the same value. External/custom writers should declare the same
protection when taking ownership: identical-value assertions cannot otherwise be
distinguished from an untouched extracted value. Reserved metadata cannot be
supplied as extracted/compiled CSV properties. This ownership protocol does not
turn the source link into a complete property-value history.

**Existing graphs:** no automatic migration or database clearing is performed.
Sources with legacy EXTRACTED_FROM links require a reviewed ownership migration,
or a fresh source namespace with `source_ids` explicitly selecting the new chunks.
New contributions may read known legacy proposals as support, but do not acquire
ownership of legacy data. Ambiguous legacy property support aborts replacement
rather than claiming clean output after retaining potentially stale owned fields.

Publication currently uses one transaction and retains model results in memory.
Use bounded source scopes; large-run throughput, bounded memory, source deletion,
claim/history retention and cross-server recovery remain separate hardening work.
The internal records are current contribution state, not a historical fact ledger.

### Extraction schema preflight

File schemas, modeling-to-schema conversion and ontology-generated schemas now use
one fail-fast contract. Invalid schemas are rejected before document-source reads,
completion invalidation, graph publication or model calls (ontology metadata must
first be read to compile an ontology schema).

Supported stored property/key types are STRING, INTEGER, FLOAT and BOOLEAN. Manual
Pydantic models can use corresponding scalar annotations, optional non-key fields,
homogeneous Literal/Enum constraints, and matching field constraints on endpoints.
Lists, mappings, arbitrary nested models and heterogeneous unions are rejected
instead of silently described as STRING. Additional property `required` flags are
honored by generated models. Identifier collisions, private/reserved fields,
duplicate entity/relationship/property names, missing entity references, ambiguous
keys and inconsistent endpoint metadata fail with an actionable schema error.

Every model must appear exactly once in `ExtractionOutput` as a list field.
Entity keys are required/non-nullable; the supported ontology `_compose_<key>`
model-validator convention can synthesize an optional key, but a key still missing
at runtime fails the source rather than silently dropping its entity. An ontology
must declare exactly one `is_key=true` property per node type; `is_key` and
`required` flags must be booleans.

New generated relationship classes carry explicit `_start_field`/`_end_field`
bindings. Older classes remain supported when their first two fields are required,
non-null endpoint keys with matching key metadata, scalar type and constraints.
Required relationship properties are kept separate from endpoints. Integer/float
and boolean endpoint values keep their native types (including `0` and `False`)
so Cypher MATCH uses the same type as the corresponding entity key. String keys
retain case; configured validators remain responsible for normalization.

This is static model/key-definition validation, not inspection or creation of
existing Neo4j DDL constraints. It does not prove arbitrary Python validator
semantics or concurrent uniqueness. Schemas remain trusted executable Python;
runtime guards catch missing keys and invalid native scalar validator returns,
without JSON-stringifying temporal values or erasing NaN. Enum values are deliberately
unwrapped. A bounded AST check rejects obvious duplicate top-level classes/annotated
fields before execution, preserving inherited fields and annotation-plus-default
patterns. Normalizer-requested SKIP filtering remains supported. Generated descriptions and
enum literals are quoted as data rather than interpolated as executable code.
