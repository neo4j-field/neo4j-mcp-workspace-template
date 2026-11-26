"""Exact embedding cache identity and single-index vector-space guards."""
from __future__ import annotations

import hashlib
import json
import math
import os
import struct
from dataclasses import dataclass

import litellm


LOCK_CONSTRAINT = 'neo4j_mcp_embedding_lock_unique'


def input_hash(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


@dataclass(frozen=True)
class EmbeddingSpace:
    model: str
    provider: str
    fingerprint: str
    requested_dimensions: int | None


def embedding_space(model: str, dimensions: int | None = None) -> EmbeddingSpace:
    if dimensions is not None and dimensions < 1:
        raise ValueError('dimensions must be positive')
    _resolved_model, provider, _key, api_base = litellm.get_llm_provider(model=model)
    # Credentials are never stored. Routing affects identity, but only its hash
    # is persisted because endpoint URLs can themselves contain sensitive data.
    configuration = {
        'contract': 1, 'model': model, 'provider': provider,
        'dimensions': dimensions, 'api_base': api_base,
        'litellm_api_base': getattr(litellm, 'api_base', None),
        'routes': {k: v for k, v in os.environ.items() if k.endswith((
            'API_BASE', 'BASE_URL', 'API_VERSION', 'ENDPOINT', 'ENDPOINT_URL',
        )) or k in {'AWS_REGION', 'AWS_REGION_NAME', 'AWS_DEFAULT_REGION',
                    'VERTEXAI_PROJECT', 'VERTEXAI_LOCATION', 'GOOGLE_CLOUD_PROJECT'}},
    }
    fingerprint = hashlib.sha256(json.dumps(configuration, sort_keys=True).encode()).hexdigest()
    return EmbeddingSpace(model, provider, fingerprint, dimensions)


def cache_matches(row, space: EmbeddingSpace) -> bool:
    actual = row.get('vector_dims')
    return bool(
        isinstance(actual, int) and actual > 0
        and row.get('space') == space.fingerprint
        and row.get('cached_model') == space.model
        and row.get('provider') == space.provider
        and row.get('dims') == actual
        and row.get('input_hash') == input_hash(row['text'])
        and (space.requested_dimensions is None or actual == space.requested_dimensions)
    )


def validate_vectors(records, embedded, requested_dimensions=None):
    expected = {row['eid'] for row in records}
    ids = [eid for eid, _ in embedded]
    if len(ids) != len(expected) or set(ids) != expected:
        raise RuntimeError('Embedding response did not cover every selected node exactly once; no vectors were written')
    dimensions = {len(vector) for _, vector in embedded}
    if len(dimensions) != 1 or next(iter(dimensions), 0) < 1:
        raise RuntimeError('Embedding response has empty or mixed dimensions')
    dims = next(iter(dimensions))
    if requested_dimensions is not None and dims != requested_dimensions:
        raise RuntimeError('Embedding response dimensions do not match the requested dimensions')
    for _, vector in embedded:
        try:
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in vector):
                raise RuntimeError('Embedding response contains non-finite or non-numeric values')
            stored = [struct.unpack('f', struct.pack('f', v))[0] for v in vector]
        except (OverflowError, struct.error) as exc:
            raise RuntimeError('Embedding response is not representable as finite FLOAT32') from exc
        if not all(math.isfinite(v) for v in stored):
            raise RuntimeError('Embedding response is not representable as finite FLOAT32')
        if not any(v != 0 for v in stored):
            raise RuntimeError('Embedding response becomes a zero FLOAT32 vector, invalid for cosine search')
    return dims


def check_preserved_space(rows, replacing_ids, space, dimensions=None):
    preserved_dims = set()
    for row in rows:
        if row['eid'] in replacing_ids:
            continue
        actual = row.get('vector_dims')
        if (row.get('space') != space.fingerprint or row.get('cached_model') != space.model
                or row.get('provider') != space.provider or row.get('dims') != actual
                or not isinstance(actual, int) or actual < 1):
            raise RuntimeError(
                'This refresh would mix unverifiable or different embedding spaces in one vector index. '
                'Refresh the whole label (include_inactive=true when needed), or use separate physical nodes/storage and index.'
            )
        preserved_dims.add(actual)
    if len(preserved_dims) > 1 or (dimensions is not None and preserved_dims - {dimensions}):
        raise RuntimeError('Preserved vectors have incompatible dimensions; refresh all indexed nodes or use separate physical nodes/storage and index')
    return preserved_dims


async def index_info(session, name):
    record = await (await session.run(
        'SHOW VECTOR INDEXES YIELD name, labelsOrTypes, properties, entityType, options '
        'WHERE name=$name RETURN name, labelsOrTypes, properties, entityType, options', name=name,
    )).single()
    return dict(record) if record else None


def check_index(index, label, dimensions=None):
    if index is None:
        return
    if (index.get('entityType') != 'NODE' or index.get('labelsOrTypes') != [label]
            or 'text_embedding' not in (index.get('properties') or [])):
        raise RuntimeError('The named vector index targets a different label/property; use separate physical nodes/storage and index')
    config = (index.get('options') or {}).get('indexConfig') or {}
    actual = config.get('vector.dimensions')
    if dimensions is not None and actual is not None and actual != dimensions:
        raise RuntimeError(
            f'Existing vector index is {actual}d but this embedding space is {dimensions}d. '
            'Use separate physical nodes/storage and index or explicitly recreate the index before a whole-label refresh; no vectors were written.'
        )
    similarity = config.get('vector.similarity_function')
    if similarity and similarity.lower() != 'cosine':
        raise RuntimeError('Existing vector index does not use cosine similarity; use separate physical nodes/storage and index')


async def ensure_publication_constraint(session):
    # A schema uniqueness guarantee is needed before a temporary per-index lock
    # can safely serialize simultaneous first publications.
    try:
        await (await session.run(
            f'CREATE CONSTRAINT {LOCK_CONSTRAINT} IF NOT EXISTS '
            'FOR (lock:EmbeddingPublicationLock) REQUIRE lock.indexName IS UNIQUE'
        )).consume()
        record = await (await session.run(
            'SHOW CONSTRAINTS YIELD name, labelsOrTypes, properties, type '
            'WHERE name=$name RETURN labelsOrTypes, properties, type', name=LOCK_CONSTRAINT,
        )).single()
    except Exception as exc:
        raise RuntimeError(
            f'Unable to create/inspect embedding publication uniqueness constraint: {exc}. '
            'No provider request or vector write was made. For schema privileges, ask the database '
            'administrator to grant SHOW CONSTRAINT on the target database and either grant '
            'CREATE CONSTRAINT or precreate the reserved '
            f'{LOCK_CONSTRAINT} uniqueness constraint on :EmbeddingPublicationLock(indexName). '
            'Embedding also needs graph read/write, name and index privileges; '
            'if privileges are already correct, check connectivity.'
        ) from exc
    if (record is None or record['labelsOrTypes'] != ['EmbeddingPublicationLock']
            or record['properties'] != ['indexName'] or 'UNIQUENESS' not in record['type']):
        raise RuntimeError('Reserved embedding lock constraint has an incompatible definition; no provider request or vector write was made')


async def overlapping_indexes(session, name, records):
    labels = {label for row in records for label in row.get('labels', [])}
    indexes = await (await session.run(
        'SHOW VECTOR INDEXES YIELD name, labelsOrTypes, properties, entityType, options '
        'RETURN name, labelsOrTypes, properties, entityType, options'
    )).data()
    return [dict(i) for i in indexes if i['name'] != name and i['entityType'] == 'NODE'
            and 'text_embedding' in (i['properties'] or [])
            and labels.intersection(i['labelsOrTypes'] or [])]


def check_overlaps(indexes, pending, space, dimensions=None):
    if not indexes:
        return
    if any(r.get('space') != space.fingerprint or r.get('cached_model') != space.model
           or r.get('provider') != space.provider or r.get('dims') != r.get('vector_dims')
           or not r.get('vector_dims') for r in pending):
        raise RuntimeError(
            'Selected nodes also participate in another text_embedding vector index. '
            'A new/model-space embedding could corrupt that index. Use separate physical nodes/storage, '
            'not an added label on the same nodes, or explicitly reconcile overlapping indexes.'
        )
    for index in indexes:
        config = (index.get('options') or {}).get('indexConfig') or {}
        actual = config.get('vector.dimensions')
        if dimensions is not None and actual is not None and actual != dimensions:
            raise RuntimeError('An overlapping text_embedding index has incompatible dimensions; no vectors were written')
