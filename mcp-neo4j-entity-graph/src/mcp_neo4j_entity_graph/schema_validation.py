"""Fail-fast contracts shared by file, modeling and ontology extraction schemas."""
from __future__ import annotations

import inspect
import keyword
import math
import re
from enum import Enum
from types import UnionType
from typing import Annotated, Literal, Union, get_args, get_origin

from pydantic import BaseModel

from .models import EntityTypeSchema, ExtractionSchema, PropertySchema, RelationshipTypeSchema

SCALARS = {str: 'STRING', int: 'INTEGER', float: 'FLOAT', bool: 'BOOLEAN'}
RESERVED_LABELS = {'Document', 'Chunk', 'Page', 'EntityExtractionRun', 'EntityExtractionClaim', 'EmbeddingPublicationLock'}
RESERVED_RELATIONSHIPS = {'EXTRACTED_FROM', 'PROCESSED_SOURCE', 'CLAIM_SOURCE'}


def safe_name(name, context, *, field=False):
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name):
        raise ValueError(f'{context}: unsafe identifier {name!r}')
    if field and (name.startswith('_') or keyword.iskeyword(name) or name in dir(BaseModel)):
        raise ValueError(f'{context}: private/reserved Python field {name!r}')
    if name.startswith(('__extraction', '__structured')):
        raise ValueError(f'{context}: reserved ownership metadata {name!r}')


def unique(values, context):
    if len(values) != len(set(values)):
        raise ValueError(f'{context}: duplicate names are not supported')


def validate_extraction_schema(schema: ExtractionSchema):
    if not schema.entity_types:
        raise ValueError('Extraction schema must declare at least one entity type')
    unique([e.label for e in schema.entity_types], 'entity types')
    unique([r.type for r in schema.relationship_types], 'relationship types')
    labels = {e.label for e in schema.entity_types}
    for entity in schema.entity_types:
        safe_name(entity.label, 'entity label')
        if entity.label in RESERVED_LABELS:
            raise ValueError(f'Reserved entity label: {entity.label}')
        safe_name(entity.key_property, f'{entity.label} key', field=True)
    for rel in schema.relationship_types:
        safe_name(rel.type, 'relationship type')
        if rel.type in RESERVED_RELATIONSHIPS:
            raise ValueError(f'Reserved relationship type: {rel.type}')
        if rel.source_entity not in labels or rel.target_entity not in labels:
            raise ValueError(f'{rel.type}: relationship endpoints must reference declared entity labels')
    for owner, properties in [(e.label, e.properties) for e in schema.entity_types] + [(r.type, r.properties) for r in schema.relationship_types]:
        unique([p.name for p in properties], f'{owner} properties')
        for prop in properties:
            safe_name(prop.name, f'{owner} property', field=True)
            if prop.type.upper() not in SCALARS.values():
                raise ValueError(f'{owner}.{prop.name}: unsupported property type {prop.type!r}; use STRING, INTEGER, FLOAT or BOOLEAN')
            prop.type = prop.type.upper()
    return schema


def scalar_type(annotation, context):
    """Return scalar storage type, nullability and declared finite value domain."""
    while get_origin(annotation) is Annotated:
        annotation = get_args(annotation)[0]
    nullable = False
    if get_origin(annotation) in (Union, UnionType):
        args = get_args(annotation)
        nullable = type(None) in args
        remaining = [a for a in args if a is not type(None)]
        if len(remaining) != 1:
            raise ValueError(f'{context}: heterogeneous unions are unsupported')
        annotation = remaining[0]
    allowed = None
    if get_origin(annotation) is Literal:
        values = get_args(annotation)
        types = {type(v) for v in values}
        if len(types) != 1 or not values:
            raise ValueError(f'{context}: Literal values must have one scalar type')
        annotation = next(iter(types))
        allowed = frozenset(values)
    elif inspect.isclass(annotation) and issubclass(annotation, Enum):
        values = [v.value for v in annotation]
        types = {type(v) for v in values}
        if len(types) != 1 or not values:
            raise ValueError(f'{context}: Enum values must have one scalar type')
        annotation = next(iter(types))
        allowed = frozenset(values)
    if allowed is not None and annotation is float and any(not math.isfinite(v) for v in allowed):
        raise ValueError(f'{context}: finite Literal/Enum values are required')
    if annotation not in SCALARS:
        raise ValueError(f'{context}: unsupported annotation {annotation!r}; use scalar str/int/float/bool, optional scalar, Literal or Enum')
    return SCALARS[annotation], nullable, allowed


def _fields(model):
    if getattr(model, '__pydantic_root_model__', False):
        raise ValueError(f'{model.__name__}: RootModel is unsupported; use an object BaseModel')
    aliases = []
    for name, info in model.model_fields.items():
        safe_name(name, model.__name__, field=True)
        if info.alias is not None:
            if not isinstance(info.alias, str):
                raise ValueError(f'{model.__name__}.{name}: non-string aliases are unsupported')
            aliases.append(info.alias)
        else:
            aliases.append(name)
    unique(aliases, f'{model.__name__} field aliases')


def endpoint_fields(model):
    """Explicit bindings for new schemas; validated first-two-field legacy layout."""
    start = getattr(model, '_start_field', None)
    end = getattr(model, '_end_field', None)
    if start is None and end is None:
        names = list(model.model_fields)
        if len(names) < 2:
            raise ValueError(f'{model.__name__}: two relationship endpoint fields are required')
        start, end = names[:2]
    if not isinstance(start, str) or not isinstance(end, str) or start == end:
        raise ValueError(f'{model.__name__}: invalid _start_field/_end_field bindings')
    if start not in model.model_fields or end not in model.model_fields:
        raise ValueError(f'{model.__name__}: endpoint bindings must name actual fields')
    return start, end


def schema_from_models(module):
    output = getattr(module, 'ExtractionOutput', None)
    if not inspect.isclass(output) or not issubclass(output, BaseModel):
        raise ValueError('ExtractionOutput must be a Pydantic BaseModel class')
    _fields(output)
    classes = []
    for name, info in output.model_fields.items():
        args = get_args(info.annotation)
        if get_origin(info.annotation) is not list or len(args) != 1 or not inspect.isclass(args[0]) or not issubclass(args[0], BaseModel):
            raise ValueError(f'ExtractionOutput.{name}: expected list[EntityModel or RelationshipModel]')
        classes.append(args[0])
    unique(classes, 'ExtractionOutput model bindings')
    declared = {c for c in vars(module).values() if inspect.isclass(c) and issubclass(c, BaseModel) and (hasattr(c, '_node_label') or hasattr(c, '_relationship_type'))}
    if declared != set(classes):
        raise ValueError('ExtractionOutput must bind every declared entity/relationship model exactly once')
    entities = {}
    entity_models = {}
    relationships = []
    for model in classes:
        _fields(model)
        node = hasattr(model, '_node_label')
        rel = hasattr(model, '_relationship_type')
        if node == rel:
            raise ValueError(f'{model.__name__}: declare exactly one entity or relationship metadata contract')
        if not node:
            continue
        label = model._node_label
        key = getattr(model, '_key_property', None)
        safe_name(label, f'{model.__name__} _node_label')
        if not isinstance(key, str):
            raise ValueError(f'{model.__name__}: _key_property must be ClassVar[str]')
        if label in entities:
            raise ValueError(f'Duplicate entity type: {label}')
        if key not in model.model_fields:
            raise ValueError(f'{label}: key property must name an actual model field')
        info = model.model_fields[key]
        _, nullable, _ = scalar_type(info.annotation, f'{label}.{key}')
        composed = f'_compose_{key}' in model.__pydantic_decorators__.model_validators
        if (nullable or not info.is_required()) and not composed:
            raise ValueError(f'{label}.{key}: key must be required and non-nullable (or use an explicit compose-key model validator)')
        properties = [PropertySchema(name=name, type=scalar_type(field.annotation, f'{label}.{name}')[0], description=field.description, required=field.is_required()) for name, field in model.model_fields.items()]
        entities[label] = EntityTypeSchema(label=label, key_property=key, description=(model.__doc__ or f'{label} entity').strip(), properties=properties)
        entity_models[label] = model
    for model in classes:
        if not hasattr(model, '_relationship_type'):
            continue
        start_label = getattr(model, '_start_node_label', None)
        end_label = getattr(model, '_end_node_label', None)
        if not isinstance(start_label, str) or not isinstance(end_label, str) or start_label not in entities or end_label not in entities:
            raise ValueError(f'{model.__name__}: relationship endpoints must reference declared entity labels')
        start, end = endpoint_fields(model)
        for field_name, label, metadata in [(start, start_label, '_start_key_property'), (end, end_label, '_end_key_property')]:
            key = entities[label].key_property
            if getattr(model, metadata, None) != key:
                raise ValueError(f'{model.__name__}: {metadata} must match {label}.{key}')
            field = model.model_fields[field_name]
            key_field = entity_models[label].model_fields[key]
            actual, nullable, domain = scalar_type(field.annotation, f'{model.__name__}.{field_name}')
            expected, _, key_domain = scalar_type(key_field.annotation, f'{label}.{key}')
            if nullable or not field.is_required() or actual != expected or domain != key_domain or field.metadata != key_field.metadata:
                raise ValueError(f'{model.__name__}.{field_name}: endpoint type/nullability/constraints must match required {label}.{key}')
        properties = [PropertySchema(name=name, type=scalar_type(info.annotation, f'{model.__name__}.{name}')[0], description=info.description, required=info.is_required()) for name, info in model.model_fields.items() if name not in (start, end)]
        relationships.append(RelationshipTypeSchema(type=model._relationship_type, description=(model.__doc__ or f'{start_label} to {end_label}').strip(), source_entity=start_label, target_entity=end_label, properties=properties))
    return validate_extraction_schema(ExtractionSchema(entity_types=list(entities.values()), relationship_types=relationships))


def validate_scalar(value, storage_type, context):
    expected = {v:k for k,v in SCALARS.items()}[storage_type]
    if type(value) is not expected or (isinstance(value, float) and not math.isfinite(value)):
        raise ValueError(f'{context}: expected finite {storage_type}, received {type(value).__name__}')
    return value
