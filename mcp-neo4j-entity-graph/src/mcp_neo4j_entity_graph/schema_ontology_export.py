"""Bounded, local Python extraction-contract export; never writes graph metadata.

The input is trusted Python, exactly as for extract_entities. This is not a
converter for arbitrary Python validation logic: unsupported semantics fail closed.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import get_args

from pydantic_core import PydanticUndefined

from .base_extractor import load_extraction_output_model, schema_from_pydantic_module
from .ontology_spec import EXTENSION, SCHEMA_URI, validate_document
from .schema_validation import endpoint_fields, scalar_type


def _fail(context, reason):
    raise ValueError(f"{context}: {reason}. Export supports scalar generated schemas with optional None defaults and strip()/strip().lower() validators; use the original ontology file or explicitly simplify the schema")


def _normalizer(function, context):
    """Recognize whole function bodies, including generated before-mode guards."""
    body = function.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        body = body[1:]
    args = function.args
    if (len(args.args) != 2 or args.posonlyargs or args.kwonlyargs or args.defaults
            or args.kw_defaults or args.vararg or args.kwarg):
        _fail(context, "unsupported validator signature")
    value = args.args[1].arg
    guarded = len(body) == 2 and isinstance(body[0], ast.If)
    if guarded:
        guard = body[0]
        expected = ast.parse(f"isinstance({value}, str)", mode="eval").body
        if (ast.dump(guard.test) != ast.dump(expected) or guard.orelse
                or not isinstance(body[1], ast.Return) or not isinstance(body[1].value, ast.Name)
                or body[1].value.id != value):
            _fail(context, "unsupported conditional validator")
        body = guard.body
    if len(body) != 1 or not isinstance(body[0], ast.Return):
        _fail(context, "custom validator cannot be represented losslessly")
    expr = ast.dump(body[0].value)
    for suffix, tags in [(".strip()", ["strip"]), (".strip().lower()", ["strip_lower"])]:
        if expr == ast.dump(ast.parse(value + suffix, mode="eval").body):
            # Existing whitespace/lowercase tags collapse internal whitespace.
            return dict(normalizers=tags), guarded
    _fail(context, "custom validator cannot be represented losslessly")


def _check_model(model, tree, *, wrapper=False):
    context = model.__name__
    declarations = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == context]
    if len(declarations) != 1 or len(declarations[0].bases) != 1 or ast.unparse(declarations[0].bases[0]) != "BaseModel" or declarations[0].decorator_list or declarations[0].keywords:
        _fail(context, "custom inheritance/class construction is unsupported")
    if model.model_config:
        _fail(context, "custom model_config is unsupported")
    decorators = model.__pydantic_decorators__
    for name in ("validators", "root_validators", "field_serializers", "model_serializers", "model_validators", "computed_fields"):
        if getattr(decorators, name):
            _fail(context, f"{name} cannot be represented")
    functions = {n.name: n for n in declarations[0].body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    if set(functions) != set(decorators.field_validators):
        _fail(context, "custom methods cannot be represented")
    policies = {}
    for name, validator in decorators.field_validators.items():
        node = functions[name]
        info = validator.info
        if wrapper or info.mode not in ("before", "after") or info.json_schema_input_type not in (None, PydanticUndefined):
            _fail(context + "." + name, "unsupported validator mode/input type")
        if len(node.decorator_list) != 2 or not any(isinstance(d, ast.Name) and d.id == 'classmethod' for d in node.decorator_list):
            _fail(context + "." + name, "unsupported validator decorators")
        calls = [d for d in node.decorator_list if isinstance(d, ast.Call)]
        if len(calls) != 1 or not isinstance(calls[0].func, ast.Name) or calls[0].func.id != 'field_validator' or any(k.arg not in {'mode', 'check_fields'} for k in calls[0].keywords):
            _fail(context + "." + name, "unsupported validator decorators")
        policy, guarded = _normalizer(node, context + "." + name)
        for field in info.fields:
            if field not in model.model_fields or field in policies:
                _fail(context + "." + name, "wildcard/stacked validators are unsupported")
            storage_type, nullable, _ = scalar_type(model.model_fields[field].annotation, context)
            if nullable and not guarded:
                _fail(context + '.' + field, 'unguarded nullable normalization changes null semantics')
            if storage_type != 'STRING' and not (guarded and info.mode == 'before'):
                _fail(context + "." + field, "string normalization on a non-string field")
            policies[field] = policy
    for name, field in model.model_fields.items():
        path = context + "." + name
        if field.metadata or field.alias or field.validation_alias or field.serialization_alias or field.exclude or field.discriminator or field.json_schema_extra or field.frozen or field.validate_default:
            _fail(path, "field constraints/aliases/serialization options are unsupported")
        # Catch every other Field option (including strict/fail_fast metadata)
        # instead of treating Pydantic's JSON schema as the validation contract.
        allowed_attributes = {'annotation', 'default', 'default_factory', 'description'}
        for attribute, value in field._attributes_set.items():
            if attribute not in allowed_attributes and value is not None:
                _fail(path, f"Field({attribute}=...) cannot be represented")
        if wrapper:
            if field.default_factory is not list or field.is_required():
                _fail(path, "output collections must use default_factory=list")
            continue
        _, nullable, domain = scalar_type(field.annotation, path)
        if domain is not None:
            _fail(path, "Literal/Enum restrictions cannot be represented")
        if field.default_factory or not field.is_required() and (field.default is not None or not nullable):
            _fail(path, "non-None defaults/default factories cannot be represented")
        if nullable and field.is_required():
            _fail(path, "required nullable fields cannot be represented by graph must_exist")
    return policies


def export_schema_document(schema_path: str) -> dict:
    """Export supported scalar Python contracts to validated Ontology Graph Spec."""
    path = Path(schema_path)
    if not path.is_absolute():
        raise ValueError("schema_path must be absolute")
    source = path.read_bytes()
    tree = ast.parse(source, filename=str(path))
    output = load_extraction_output_model(str(path), source_bytes=source)
    schema = schema_from_pydantic_module(sys.modules[output.__module__])
    _check_model(output, tree, wrapper=True)
    models = [get_args(f.annotation)[0] for f in output.model_fields.values()]
    policies = {model: _check_model(model, tree) for model in models}
    entities = {m._node_label: m for m in models if hasattr(m, '_node_label')}
    relationships = {m._relationship_type: m for m in models if hasattr(m, '_relationship_type')}
    document = dict(schema=SCHEMA_URI, version="1.0.0", id=path.stem, nodes={}, relationships={})

    def properties(model, rows, key=None):
        result = {}
        for prop in rows:
            value = dict(type=prop.type)
            if prop.description is not None:
                value['description'] = prop.description
            if prop.required:
                value['must_exist'] = True
            if prop.name == key:
                value['key'] = True
            if prop.name in policies[model]:
                value['extensions'] = {'custom': {EXTENSION: policies[model][prop.name]}}
            result[prop.name] = value
        return result

    for entity in schema.entity_types:
        model = entities[entity.label]
        document['nodes'][entity.label] = dict(label=entity.label, description=entity.description, properties=properties(model, entity.properties, entity.key_property))
    for rel in schema.relationship_types:
        model = relationships[rel.type]
        start, end = endpoint_fields(model)
        for field, label in [(start, rel.source_entity), (end, rel.target_entity)]:
            target = entities[label]
            if policies[model].get(field) != policies[target].get(target._key_property):
                _fail(model.__name__ + '.' + field, "endpoint normalizer differs from its entity key")
        document['relationships'][rel.type] = dict(type=rel.type, description=rel.description, properties=properties(model, rel.properties), **{'from': {'node': rel.source_entity}, 'to': {'node': rel.target_entity}})
    validate_document(document)
    return document
