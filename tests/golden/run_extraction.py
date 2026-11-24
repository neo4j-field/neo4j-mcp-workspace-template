"""Run the real text extractor on synthetic notes without writing to Neo4j.

Run from the repository root with the entity server's Python environment:
python -m tests.golden.run_extraction --output /absolute/path/candidate.json
Only source text and the extraction schema reach the model, never expected facts.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from mcp_neo4j_entity_graph.base_extractor import (
    load_extraction_output_model, schema_from_pydantic_module,
)
from mcp_neo4j_entity_graph.models import ChunkExtractionOutcome, ChunkType, ClassifiedChunk
from mcp_neo4j_entity_graph.text_extractor import TextExtractor
from tests.golden.evaluate import evaluate


DIRECTORY = Path(__file__).resolve().parent
ROOT = DIRECTORY.parents[1]


def candidate_case(result, schema):
    """Export only observed facts; do not pad missing entities from the reference."""
    return {
        'id': result.chunk_id,
        'entities': [
            {'label': entity.label,
             'key': str(entity.properties[schema.get_entity_schema(entity.label).key_property])}
            for entity in result.entities
        ],
        'relationships': [
            {'type': rel.type, 'source': [rel.source_label, rel.source_key],
             'target': [rel.target_label, rel.target_key]}
            for rel in result.relationships
        ],
    }


async def run(output: Path, baseline: Path | None = None):
    load_dotenv(ROOT / '.env')
    model = os.environ.get('EXTRACTION_MODEL')
    if not model:
        raise ValueError('EXTRACTION_MODEL must be configured; no model is substituted')
    reference_path = DIRECTORY / 'synthetic_extraction.json'
    schema_path = DIRECTORY / 'synthetic_schema.py'
    reference = json.loads(reference_path.read_text())
    previous = json.loads(baseline.read_text()) if baseline else None
    schema_hash = hashlib.sha256(schema_path.read_bytes()).hexdigest()
    reference_hash = hashlib.sha256(reference_path.read_bytes()).hexdigest()
    if previous and (
        previous.get('metadata', {}).get('schema_sha256') != schema_hash
        or previous.get('metadata', {}).get('reference_sha256') != reference_hash
    ):
        raise ValueError('Baseline schema/reference hashes do not match this run')
    output_model = load_extraction_output_model(str(schema_path))
    schema = schema_from_pydantic_module(sys.modules['extraction_models'])
    extractor = TextExtractor(model=model, max_retries=1)
    cases = []
    for case in reference['cases']:
        result = await extractor.extract_chunk(
            ClassifiedChunk(id=case['id'], chunk_type=ChunkType.TEXT, text=case['text']),
            schema, output_model,
        )
        if result.outcome == ChunkExtractionOutcome.FAILED:
            raise RuntimeError(f"{case['id']}: {result.error}")
        cases.append(candidate_case(result, schema))
    candidate = {
        'metadata': {
            'model': model, 'run_at': datetime.now(timezone.utc).isoformat(),
            'schema_sha256': schema_hash, 'reference_sha256': reference_hash,
            'source': 'live TextExtractor; no Neo4j writes; no reference facts sent to model',
        },
        'cases': cases,
    }
    report = evaluate(reference, candidate)
    if previous:
        prior_report = evaluate(reference, previous)
        report['delta_vs_baseline'] = {
            kind: {
                metric: round(report['totals'][kind][metric] - prior_report['totals'][kind][metric], 4)
                for metric in ('precision', 'recall', 'f1')
            }
            for kind in ('entities', 'relationships')
        }
    # Exclusive create prevents accidentally replacing a reviewed baseline.
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x') as stream:
        json.dump(candidate, stream, indent=2)
        stream.write('\n')
    print(json.dumps({'candidate': str(output), 'model': model, **report}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--baseline', type=Path)
    args = parser.parse_args()
    if not args.output.is_absolute():
        parser.error('--output must be an absolute path')
    if args.output.exists():
        parser.error('--output already exists; choose a new run filename')
    asyncio.run(run(args.output, args.baseline))


if __name__ == '__main__':
    main()
