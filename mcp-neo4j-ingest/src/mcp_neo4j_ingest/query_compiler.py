"""Compile validated graph-model metadata into executable CSV ingest Cypher.

The upstream modeling server's ingest-query helpers are intentionally not trusted:
they currently discard ``source.column_name`` mappings and can write relationship
properties to the end node.  This module is the owned safety boundary used by the
workspace before a query reaches the database-facing ingest tool.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any


_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_TYPE_EXPRESSIONS = {
    "ANY": "{value}",
    "BOOLEAN": "toBoolean({value})",
    "DATE": "date({value})",
    "DATETIME": "datetime({value})",
    "DURATION": "duration({value})",
    "FLOAT": "toFloat({value})",
    "INTEGER": "toInteger({value})",
    "LOCALDATETIME": "localdatetime({value})",
    "LOCALTIME": "localtime({value})",
    "POINT": "point({value})",
    "STRING": "{value}",
    "TIME": "time({value})",
}


class IngestModelError(ValueError):
    """Raised when model metadata cannot be compiled safely."""


def _mapping(value: Mapping[str, Any] | str, field: str) -> Mapping[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise IngestModelError(f"{field} must be valid JSON: {exc.msg}") from exc
    if not isinstance(value, Mapping):
        raise IngestModelError(f"{field} must be an object")
    return value


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _SAFE_IDENTIFIER.fullmatch(value):
        raise IngestModelError(
            f"{field} must match {_SAFE_IDENTIFIER.pattern!r}; got {value!r}"
        )
    return value


def _property(raw: Any, field: str) -> tuple[str, str, str]:
    prop = _mapping(raw, field)
    name = _identifier(prop.get("name"), f"{field}.name")
    if name.startswith(("__extraction", "__structured")):
        raise IngestModelError(f"{field}.name uses reserved ownership metadata")
    source = prop.get("source")
    if source is None:
        column = name
    else:
        source = _mapping(source, f"{field}.source")
        column = source.get("column_name") or name
    column = _identifier(column, f"{field}.source.column_name")
    neo4j_type = prop.get("type") or "ANY"
    if not isinstance(neo4j_type, str):
        raise IngestModelError(f"{field}.type must be a string")
    normalized_type = neo4j_type.replace("_", "").replace(" ", "").upper()
    if normalized_type not in _TYPE_EXPRESSIONS:
        raise IngestModelError(
            f"{field}.type {neo4j_type!r} is unsupported; expected one of "
            f"{', '.join(sorted(_TYPE_EXPRESSIONS))}"
        )
    return name, column, normalized_type


def _record_expression(column: str, neo4j_type: str) -> str:
    value = f"record.{column}"
    return _TYPE_EXPRESSIONS[neo4j_type].format(value=value)


def _properties(raw: Any, field: str) -> list[tuple[str, str, str]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise IngestModelError(f"{field} must be a list")
    result = [_property(prop, f"{field}[{index}]") for index, prop in enumerate(raw)]
    names = [name for name, _, _ in result]
    if len(names) != len(set(names)):
        raise IngestModelError(f"{field} contains duplicate property names")
    return result


def _set_clause(variable: str, properties: list[tuple[str, str, str]]) -> str:
    if not properties:
        return ""
    assignments = [
        f"{variable}.{name} = {_record_expression(column, neo4j_type)}"
        for name, column, neo4j_type in properties
    ]
    return "\nSET " + ",\n    ".join(assignments)


def compile_node_ingest_query(node: Mapping[str, Any] | str) -> str:
    """Compile one node definition, honoring every declared CSV column mapping."""

    node = _mapping(node, "node")
    label = _identifier(node.get("label"), "node.label")
    if label in {"EntityExtractionRun", "EntityExtractionClaim", "EmbeddingPublicationLock"}:
        raise IngestModelError("node.label is reserved for extraction metadata")
    key = _property(node.get("key_property"), "node.key_property")
    properties = _properties(node.get("properties", []), "node.properties")
    if key[0] in {name for name, _, _ in properties}:
        raise IngestModelError("node key property must not be repeated in node.properties")

    key_name, key_column, key_type = key
    query = (
        "UNWIND $records AS record\n"
        f"MERGE (node:{label} "
        f"{{{key_name}: {_record_expression(key_column, key_type)}}})"
    )
    ownership = json.dumps([key_name] + [name for name, _, _ in properties])
    return query + _set_clause("node", properties) + (
        "\nSET node.__structuredSource = true,"
        f" node.__structuredProperties = reduce(owned = coalesce(node.__structuredProperties, []),"
        f" key IN {ownership} | CASE WHEN key IN owned THEN owned ELSE owned + key END)"
    )


def compile_relationship_ingest_query(
    data_model: Mapping[str, Any] | str,
    relationship: Mapping[str, Any] | str,
) -> str:
    """Compile a relationship query with bound endpoints and relationship writes."""

    data_model = _mapping(data_model, "data_model")
    relationship = _mapping(relationship, "relationship")
    relationship_type = _identifier(relationship.get("type"), "relationship.type")
    start_label = _identifier(
        relationship.get("start_node_label"), "relationship.start_node_label"
    )
    end_label = _identifier(
        relationship.get("end_node_label"), "relationship.end_node_label"
    )

    if {start_label, end_label} & {"EntityExtractionRun", "EntityExtractionClaim", "EmbeddingPublicationLock"} or relationship_type in {"EXTRACTED_FROM", "PROCESSED_SOURCE", "CLAIM_SOURCE"}:
        raise IngestModelError("relationship uses reserved extraction metadata")

    raw_nodes = data_model.get("nodes")
    if not isinstance(raw_nodes, list):
        raise IngestModelError("data_model.nodes must be a list")
    nodes = [_mapping(node, f"data_model.nodes[{index}]") for index, node in enumerate(raw_nodes)]

    def find_node(label: str) -> Mapping[str, Any]:
        matches = [node for node in nodes if node.get("label") == label]
        if len(matches) != 1:
            raise IngestModelError(
                f"relationship endpoint {label!r} must match exactly one data-model node"
            )
        return matches[0]

    start_key = _property(find_node(start_label).get("key_property"), "start.key_property")
    end_key = _property(find_node(end_label).get("key_property"), "end.key_property")
    key_raw = relationship.get("key_property")
    relationship_key = _property(key_raw, "relationship.key_property") if key_raw else None
    properties = _properties(relationship.get("properties", []), "relationship.properties")
    if relationship_key and relationship_key[0] in {name for name, _, _ in properties}:
        raise IngestModelError(
            "relationship key property must not be repeated in relationship.properties"
        )

    start_name, start_column, start_type = start_key
    end_name, end_column, end_type = end_key
    if relationship_key:
        rel_name, rel_column, rel_type = relationship_key
        merge_relationship = (
            f"[relationship:{relationship_type} "
            f"{{{rel_name}: {_record_expression(rel_column, rel_type)}}}]"
        )
    else:
        merge_relationship = f"[relationship:{relationship_type}]"

    query = (
        "UNWIND $records AS record\n"
        f"MATCH (start:{start_label} "
        f"{{{start_name}: {_record_expression(start_column, start_type)}}})\n"
        f"MATCH (end:{end_label} "
        f"{{{end_name}: {_record_expression(end_column, end_type)}}})\n"
        f"MERGE (start)-{merge_relationship}->(end)"
    )
    ownership = json.dumps(([relationship_key[0]] if relationship_key else []) + [name for name, _, _ in properties])
    return query + _set_clause("relationship", properties) + (
        "\nSET relationship.__structuredSource = true,"
        f" relationship.__structuredProperties = reduce(owned = coalesce(relationship.__structuredProperties, []),"
        f" key IN {ownership} | CASE WHEN key IN owned THEN owned ELSE owned + key END)"
    )
