"""Source-scoped extraction contributions and conservative transactional cleanup.

Only properties introduced by this writer and objects created by it are owned.
Structured imports and subsequent external edits take precedence over deletion.
All methods run inside the caller's publication transaction.
"""
from __future__ import annotations

import json
import re


PREFIXES = ('__extraction', '__structured')
META = {'__extractionCreated', '__extractionLabel', '__extractionKeyProperty',
        '__extractionValues', '__extractionReconcileLock',
        '__structuredSource', '__structuredProperties'}


def identifier(value):
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', value):
        raise ValueError(f'Unsafe extraction identifier: {value!r}')
    return f'`{value}`'


def validate_properties(properties):
    for key in properties:
        identifier(key)
        if key.startswith(PREFIXES):
            raise ValueError(f'Reserved extraction property: {key}')


def encode(value):
    return json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)


def same(left, right):
    if type(left) is not type(right):
        return False
    if isinstance(left, list):
        return len(left) == len(right) and all(same(a, b) for a, b in zip(left, right))
    return left == right


async def track_properties(tx, kind, object_id, before, after, written):
    pattern = '(o)' if kind == 'node' else '()-[o]->()'
    record = await (await tx.run(f'MATCH {pattern} WHERE elementId(o)=$id RETURN properties(o) AS props', id=object_id)).single()
    values = json.loads(record['props'].get('__extractionValues', '{}'))
    protected = set(record['props'].get('__structuredProperties', []))
    key = after.get('__extractionKeyProperty')
    if kind == 'node' and after.get('__extractionCreated') and key and key not in values:
        values[key] = after[key]
    for name in written:
        if name in protected:
            values.pop(name, None)
        elif before.get(name) is None or name in values:
            values[name] = after[name]
    await (await tx.run(f'MATCH {pattern} WHERE elementId(o)=$id SET o.__extractionValues=$values',
                       id=object_id, values=encode(values))).consume()


async def write_entity(tx, source_label, label, key, entity, meta, policy, scope):
    validate_properties(entity['properties'])
    if label in {'EntityExtractionRun', 'EntityExtractionClaim', 'EmbeddingPublicationLock', 'Document', 'Chunk', 'Page'}:
        raise ValueError(f'Reserved entity label: {label}')
    result = await tx.run(f'''
        MATCH (c:{identifier(source_label)} {{id: $source}})
        MERGE (e:{identifier(label)} {{{identifier(key)}: $key}})
        ON CREATE SET e.__extractionCreated=true, e.__extractionLabel=$label,
                      e.__extractionKeyProperty=$key_name
        SET e.__extractionReconcileLock=coalesce(e.__extractionReconcileLock, 0) + 1
        WITH e, c, properties(e) AS before,
             [k IN keys($props) WHERE $policy='overwrite' OR e[k] IS NULL] AS written,
             [k IN keys($props) WHERE e[k] IS NOT NULL AND e[k] <> $props[k]] AS conflicts
        FOREACH (k IN written | SET e[k]=$props[k])
        MERGE (e)-[r:EXTRACTED_FROM {{extractionScope: $scope}}]->(c)
        SET r += $meta, r.ownershipVersion=1, r.proposedPropertiesJson=$proposed,
            r.conflictingProperties=conflicts, r.propertyPolicy=$policy
        RETURN elementId(e) AS id, before, properties(e) AS after, written
    ''', source=entity['chunk_id'], key=entity['key_value'], label=label, key_name=key,
        props=entity['properties'], policy=policy, scope=scope, meta=meta,
        proposed=entity['proposed_json'])
    rows = await result.data()
    if len(rows) != 1:
        raise RuntimeError('Entity/source identity must resolve to exactly one node')
    row = rows[0]
    await track_properties(tx, 'node', row['id'], row['before'], row['after'], row['written'])
    return row['id']


async def write_relationship(tx, source_label, relationship, meta, scope, policy):
    rel = relationship
    validate_properties(rel['properties'])
    if rel['type'] in {'EXTRACTED_FROM', 'PROCESSED_SOURCE', 'CLAIM_SOURCE'}:
        raise ValueError(f"Reserved relationship type: {rel['type']}")
    result = await tx.run(f'''
        MATCH (c:{identifier(source_label)} {{id: $source}})
        MATCH (a:{identifier(rel['source_label'])} {{{identifier(rel['source_key_property'])}: $a}})
        MATCH (b:{identifier(rel['target_label'])} {{{identifier(rel['target_key_property'])}: $b}})
        MERGE (a)-[r:{identifier(rel['type'])}]->(b)
        ON CREATE SET r.__extractionCreated=true
        SET r.__extractionReconcileLock=coalesce(r.__extractionReconcileLock, 0) + 1
        WITH r, c, properties(r) AS before,
             [k IN keys($props) WHERE $policy='overwrite' OR r[k] IS NULL] AS written,
             [k IN keys($props) WHERE r[k] IS NOT NULL AND r[k] <> $props[k]] AS conflicts
        FOREACH (k IN written | SET r[k]=$props[k])
        MERGE (claim:EntityExtractionClaim {{scopeId: $scope,
               sourceElementId: elementId(c), edgeId: elementId(r)}})
        SET claim.proposedPropertiesJson=$proposed, claim.extractedAt=$time,
            claim.sourceLabel=$source_label, claim.runId=$run_id,
            claim.extractionFingerprint=$fingerprint, claim.propertyPolicy=$policy,
            claim.conflictingProperties=conflicts
        MERGE (claim)-[:CLAIM_SOURCE]->(c)
        RETURN elementId(r) AS id, before, properties(r) AS after, written
    ''', source=rel['chunk_id'], a=rel['source_key_value'], b=rel['target_key_value'],
        props=rel['properties'], scope=scope, proposed=encode(rel['properties']),
        time=meta['extractedAt'], source_label=source_label,
        run_id=meta['runId'], fingerprint=meta['extractionFingerprint'], policy=policy)
    rows = await result.data()
    if len(rows) != 1:
        raise RuntimeError('Relationship persistence mismatch: endpoints/source must resolve exactly once')
    row = rows[0]
    await track_properties(tx, 'relationship', row['id'], row['before'], row['after'], row['written'])


async def reconcile(tx, kind, object_id):
    pattern = '(o)' if kind == 'node' else '()-[o]->()'
    row = await (await tx.run(f'''MATCH {pattern} WHERE elementId(o)=$id
        SET o.__extractionReconcileLock=coalesce(o.__extractionReconcileLock, 0) + 1
        RETURN properties(o) AS props''', id=object_id)).single()
    if row is None:
        return
    props = row['props']
    if kind == 'node':
        records = await (await tx.run('''MATCH (e)-[r:EXTRACTED_FROM]->(c)
            WHERE elementId(e)=$id RETURN r.proposedPropertiesJson AS proposed,
            r.ownershipVersion AS ownership ORDER BY r.extractedAt, c.id, r.extractionScope''', id=object_id)).data()
    else:
        records = await (await tx.run('''MATCH (c:EntityExtractionClaim {edgeId:$id})
            RETURN c.proposedPropertiesJson AS proposed, 1 AS ownership
            ORDER BY c.extractedAt, c.sourceElementId, c.scopeId''', id=object_id)).data()
    values = json.loads(props.get('__extractionValues', '{}'))
    protected = set(props.get('__structuredProperties', []))
    # Legacy proposals may support values, but never grant deletion ownership.
    # If support itself is unknown, do not silently report a clean replacement
    # while retaining a property we would otherwise remove or rematerialize.
    if any(r['proposed'] is None for r in records):
        if any(k != props.get('__extractionKeyProperty') and k not in protected
               and same(props.get(k), v) for k, v in values.items()):
            raise RuntimeError('Legacy property support lacks proposal metadata; reviewed ownership migration required')
        return
    proposals = [json.loads(r['proposed']) for r in records]
    keep = {}
    changes = {}
    for key, old in values.items():
        if key == props.get('__extractionKeyProperty'):
            keep[key] = old
            continue
        if key in protected or not same(props.get(key), old):
            continue  # external ownership/edit: relinquish, never delete it
        supporters = [p[key] for p in proposals if p.get(key) is not None]
        if supporters:
            chosen = next((v for v in supporters if same(v, old)), supporters[0])
            keep[key] = chosen
            changes[key] = chosen
        else:
            changes[key] = None
    await (await tx.run(f'''MATCH {pattern} WHERE elementId(o)=$id
        SET o += $changes, o.__extractionValues=$values''', id=object_id,
        changes=changes, values=encode(keep))).consume()
    if kind == 'relationship' and not records:
        current = {**props, **changes}
        remaining = {k: v for k, v in current.items() if v is not None and k not in META}
        if props.get('__extractionCreated') and not props.get('__structuredSource') and not remaining:
            await (await tx.run('MATCH ()-[r]->() WHERE elementId(r)=$id DELETE r', id=object_id)).consume()


async def remove_contributions(tx, source_label, source_ids, scope):
    """Detach only selected contributions, never infer ownership from labels."""
    rows = await (await tx.run(f'''
        MATCH (e)-[r:EXTRACTED_FROM]->(c:{identifier(source_label)})
        WHERE c.id IN $sources AND r.extractionScope=$scope
        WITH collect(DISTINCT elementId(e)) AS ids, collect(r) AS links
        FOREACH (r IN links | DELETE r) RETURN ids
    ''', sources=source_ids, scope=scope)).single()
    entity_ids = rows['ids'] if rows else []
    row = await (await tx.run(f'''
        MATCH (claim:EntityExtractionClaim)-[:CLAIM_SOURCE]->(c:{identifier(source_label)})
        WHERE c.id IN $sources AND claim.scopeId=$scope
        WITH collect(DISTINCT claim.edgeId) AS ids, collect(claim) AS claims
        FOREACH (claim IN claims | DETACH DELETE claim) RETURN ids
    ''', sources=source_ids, scope=scope)).single()
    for edge_id in (row['ids'] if row else []):
        await reconcile(tx, 'relationship', edge_id)
    for entity_id in entity_ids:
        await reconcile(tx, 'node', entity_id)
    return entity_ids


async def collect_unused_entities(tx, ids):
    for object_id in set(ids):
        row = await (await tx.run('''MATCH (e) WHERE elementId(e)=$id AND NOT (e)--()
            RETURN properties(e) AS props, labels(e) AS labels''', id=object_id)).single()
        if not row:
            continue
        props = row['props']
        if not props.get('__extractionCreated') or props.get('__structuredSource'):
            continue
        if set(row['labels']) != {props.get('__extractionLabel')}:
            continue
        values = json.loads(props.get('__extractionValues', '{}'))
        domain = {k: v for k, v in props.items() if k not in META}
        if all(k in values and same(v, values[k]) for k, v in domain.items()):
            await (await tx.run('MATCH (e) WHERE elementId(e)=$id DELETE e', id=object_id)).consume()


def coalesce_result(result, schema, policy):
    """Keep one complete contribution per source/entity or source/relationship.

    Preserve mode takes the first non-null assertion for a duplicate field;
    overwrite mode takes the last. Partial duplicates contribute all their fields.
    """
    entities = {}
    relationships = {}
    def merge(collection, identity, item):
        props = {k: v for k, v in item.properties.items() if v is not None}
        if identity not in collection:
            collection[identity] = item.model_copy(update={'properties': props})
        elif policy == 'overwrite':
            collection[identity].properties.update(props)
        else:
            for key, value in props.items():
                collection[identity].properties.setdefault(key, value)
    for entity in result.entities:
        entity_schema = schema.get_entity_schema(entity.label)
        if entity_schema is None:
            raise ValueError(f'Unknown extracted entity label: {entity.label}')
        key = entity.properties.get(entity_schema.key_property)
        if key is None or key == '':
            raise ValueError(f'Missing extracted entity key: {entity.label}')
        merge(entities, (entity.label, type(key).__name__, encode(key)), entity)
    for rel in result.relationships:
        merge(relationships, (rel.type, rel.source_label, rel.source_key,
                              rel.target_label, rel.target_key), rel)
    return result.model_copy(update={
        'entities': list(entities.values()), 'relationships': list(relationships.values()),
    })
