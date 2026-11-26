"""Bounded Ontology Graph Spec 1.1.0 interchange for extraction ontologies.

The bundled normative schema is copied unchanged from SCHEMA_URI. Runtime validation
is offline. This adapter never installs graph constraints from a spec, replaces an
ontology, or silently drops unsupported semantics. Its custom extension is private
to this template; it is not part of the Neo4j specification.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

from .models import ExtractionSchema
from .normalizer_templates import (
    NormalizerConfig,
    _GENERIC_RUNTIME,
    _PARAMETERIZED_RUNTIME,
)
from .ontology_loader import (
    _fetch_node_types,
    _fetch_relationship_types,
    _fetch_alias_maps,
    _fetch_blocklists,
    _build_normalizer_config,
)
from .schema_generator import generate_extraction_models_code

SCHEMA_URI = "https://neo4j.com/docs/ontology-graph-spec/1.1.0/schema.json"
EXTENSION = "neo4j-mcp-workspace-template"
_SCHEMA = json.loads(
    (Path(__file__).parent / "schemas" / "ontology-graph-spec-1.1.0.json").read_text()
)
_VALIDATOR = Draft202012Validator(_SCHEMA)
_SCALARS = {"STRING", "INTEGER", "FLOAT", "BOOLEAN"}
_NORMALIZER_FIELDS = {
    "normalizers",
    "regex_pattern",
    "regex_replacement",
    "enum_values",
    "name_template",
    "alias_map_name",
    "blocklist_name",
}


class _UniqueLoader(yaml.SafeLoader):
    """YAML mappings must not silently discard duplicate keys or recursive aliases."""

    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            raise ValueError(
                "YAML aliases are unsupported; use explicit JSON-compatible values"
            )
        return super().compose_node(parent, index)


def _mapping(loader, node):
    pairs = loader.construct_pairs(node, deep=True)
    result = {}
    for key, value in pairs:
        if not isinstance(key, str):
            raise ValueError("Ontology mapping keys must be strings")
        if key in result:
            raise ValueError(f"Duplicate mapping key: {key}")
        result[key] = value
    return result


_UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def _only(value, allowed, path):
    extra = set(value) - set(allowed)
    if extra:
        raise ValueError(
            f"{path}.{sorted(extra)[0]}: unsupported by the extraction adapter"
        )


def _custom(value, path):
    extensions = value.get("extensions", {})
    _only(extensions, {"custom"}, path + ".extensions")
    custom = extensions.get("custom", {})
    _only(custom, {EXTENSION}, path + ".extensions.custom")
    result = custom.get(EXTENSION, {})
    if not isinstance(result, dict):
        raise ValueError(f"{path}.extensions.custom.{EXTENSION}: expected an object")
    return result


def validate_document(document: dict) -> dict:
    """Validate normative structure and return the supported, normalized DB payload."""
    errors = sorted(
        _VALIDATOR.iter_errors(document), key=lambda e: str(list(e.absolute_path))
    )
    if errors:
        error = errors[0]
        path = ".".join(map(str, error.absolute_path)) or "$"
        raise ValueError(f"{path}: {error.message}")
    if document["schema"] != SCHEMA_URI:
        raise ValueError(f"schema: expected pinned schema URI {SCHEMA_URI}")
    _only(
        document,
        {
            "schema",
            "version",
            "id",
            "name",
            "description",
            "nodes",
            "relationships",
            "extensions",
        },
        "$",
    )
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", document["id"]):
        raise ValueError(
            "id: use a nonempty filename-safe identifier (letters, digits, underscore, dot, hyphen)"
        )
    custom = _custom(document, "$")
    _only(custom, {"alias_maps", "blocklists"}, "$.extensions.custom." + EXTENSION)
    aliases = custom.get("alias_maps", {})
    blocks = custom.get("blocklists", {})
    if not isinstance(aliases, dict) or not all(
        isinstance(n, str)
        and n
        and isinstance(v, dict)
        and all(isinstance(k, str) and isinstance(x, str) for k, x in v.items())
        for n, v in aliases.items()
    ):
        raise ValueError(
            "alias_maps: expected named objects mapping strings to strings"
        )
    if not isinstance(blocks, dict) or not all(
        isinstance(n, str)
        and n
        and isinstance(v, list)
        and all(isinstance(x, str) for x in v)
        for n, v in blocks.items()
    ):
        raise ValueError("blocklists: expected named arrays of strings")
    nodes = []
    labels = {}
    normalizers: dict[str, list[NormalizerConfig]] = {}

    def properties(owner, raw, constraints, path, *, node):
        out = []
        for pid, prop in raw.items():
            _only(
                prop,
                {"name", "type", "description", "must_exist", "key", "extensions"},
                f"{path}.properties.{pid}",
            )
            name = prop.get("name") or pid
            if prop.get("type") not in _SCALARS:
                raise ValueError(
                    f"{path}.properties.{pid}.type: use STRING, INTEGER, FLOAT or BOOLEAN"
                )
            cfg = _custom(prop, f"{path}.properties.{pid}")
            _only(
                cfg,
                _NORMALIZER_FIELDS,
                f"{path}.properties.{pid}.extensions.custom.{EXTENSION}",
            )
            if "normalizers" in cfg and (
                not isinstance(cfg["normalizers"], list)
                or not all(isinstance(t, str) for t in cfg["normalizers"])
            ):
                raise ValueError(
                    f"{path}.properties.{pid}.normalizers: expected string array"
                )
            for field in [
                "regex_pattern",
                "regex_replacement",
                "name_template",
                "alias_map_name",
                "blocklist_name",
            ]:
                if field in cfg and not isinstance(cfg[field], str):
                    raise ValueError(
                        f"{path}.properties.{pid}.{field}: expected string"
                    )
            if "enum_values" in cfg and (
                not isinstance(cfg["enum_values"], list)
                or not all(isinstance(t, str) for t in cfg["enum_values"])
            ):
                raise ValueError(
                    f"{path}.properties.{pid}.enum_values: expected string array"
                )
            entry = dict(
                name=name,
                type=prop["type"],
                description=prop.get("description"),
                required=bool(prop.get("must_exist") or prop.get("key")),
                is_key=bool(prop.get("key")),
                **cfg,
            )
            if entry["is_key"] and not node:
                raise ValueError(
                    f"{path}.properties.{pid}.key: relationship keys are unsupported"
                )
            out.append(entry)
        for cid, constraint in constraints.items():
            _only(constraint, {"type", "properties"}, f"{path}.constraints.{cid}")
            keys = constraint["properties"]
            if (
                len(keys) != 1
                or keys[0] not in raw
                or constraint["type"] not in {"KEY", "EXISTS"}
            ):
                raise ValueError(
                    f"{path}.constraints.{cid}: only single-property KEY/EXISTS constraints are supported"
                )
            entry = out[list(raw).index(keys[0])]
            entry["required"] = True
            if constraint["type"] == "KEY":
                if not node:
                    raise ValueError(
                        f"{path}.constraints.{cid}: relationship keys are unsupported"
                    )
                entry["is_key"] = True
        for entry in out:
            tags = entry.get("normalizers", [])
            known = (
                set(_GENERIC_RUNTIME)
                | set(_PARAMETERIZED_RUNTIME)
                | {"compose_name_from_fields"}
            )
            if any(t not in known for t in tags):
                raise ValueError(f"{path}.{entry['name']}: unknown normalizer tag")
            if any(t in tags for t in ["regex_normalize", "regex_skip"]):
                if not entry.get("regex_pattern"):
                    raise ValueError(
                        f"{path}.{entry['name']}: regex_pattern is required"
                    )
                try:
                    pattern = re.compile(entry["regex_pattern"])
                    if "regex_normalize" in tags:
                        if "regex_replacement" not in entry:
                            raise ValueError(
                                f"{path}.{entry['name']}: regex_replacement is required"
                            )
                        pattern.sub(entry["regex_replacement"], "")
                except re.error as exc:
                    raise ValueError(
                        f"{path}.{entry['name']}: invalid regex: {exc}"
                    ) from exc
            if "enum_validate" in tags and not entry.get("enum_values"):
                raise ValueError(
                    f"{path}.{entry['name']}: enum_values must not be empty"
                )
            if "alias_map" in tags and entry.get("alias_map_name") not in aliases:
                raise ValueError(
                    f"{path}.{entry['name']}: missing alias_map_name reference"
                )
            if "blocklist" in tags and entry.get("blocklist_name") not in blocks:
                raise ValueError(
                    f"{path}.{entry['name']}: missing blocklist_name reference"
                )
            if "compose_name_from_fields" in tags:
                if not node or not entry.get("name_template"):
                    raise ValueError(
                        f"{path}.{entry['name']}: composed names require a node and name_template"
                    )
                if f"{owner}.__model__" in normalizers:
                    raise ValueError(
                        f"{path}: only one compose_name_from_fields target is supported"
                    )
                normalizers[f"{owner}.__model__"] = [
                    NormalizerConfig(
                        tag="compose_name_from_fields",
                        name_template=entry["name_template"],
                        alias_map_name=entry["name"],
                    )
                ]
            chain = [
                _build_normalizer_config(
                    t, entry, aliases, {n: frozenset(v) for n, v in blocks.items()}
                )
                for t in tags
                if t != "compose_name_from_fields"
            ]
            if chain:
                normalizers[f"{owner}.{entry['name']}"] = chain
        return out

    for nid, raw in document.get("nodes", {}).items():
        path = f"nodes.{nid}"
        _only(
            raw, {"label", "labels", "description", "properties", "constraints"}, path
        )
        if raw.get("label") and raw.get("labels"):
            raise ValueError(f"{path}: use label or labels.identifier, not both")
        label = raw.get("label")
        if raw.get("labels"):
            _only(raw["labels"], {"identifier"}, path + ".labels")
            label = raw["labels"].get("identifier")
        if not label:
            raise ValueError(f"{path}.label: one identifying label is required")
        labels[nid] = label
        props = properties(
            label,
            raw.get("properties", {}),
            raw.get("constraints", {}),
            path,
            node=True,
        )
        keys = [p["name"] for p in props if p["is_key"]]
        if len(keys) != 1:
            raise ValueError(f"{path}: exactly one key property is required")
        nodes.append(
            dict(
                name=label,
                description=raw.get("description") or f"A {label} entity",
                properties=props,
            )
        )
    rels = []
    for rid, raw in document.get("relationships", {}).items():
        path = f"relationships.{rid}"
        _only(
            raw,
            {"type", "from", "to", "description", "properties", "constraints"},
            path,
        )
        ends = []
        for end in ["from", "to"]:
            endpoint = raw[end]
            _only(endpoint, {"node", "label"}, f"{path}.{end}")
            nid = endpoint.get("node")
            if nid not in labels:
                raise ValueError(f"{path}.{end}.node: unknown node reference {nid!r}")
            if endpoint.get("label") and endpoint["label"] != labels[nid]:
                raise ValueError(f"{path}.{end}.label: does not match node identifier")
            ends.append(labels[nid])
        props = properties(
            raw["type"],
            raw.get("properties", {}),
            raw.get("constraints", {}),
            path,
            node=False,
        )
        rels.append(
            dict(
                name=raw["type"],
                description=raw.get("description") or f"{ends[0]} to {ends[1]}",
                properties=props,
                **{"from": ends[0], "to": ends[1]},
            )
        )
    schema = ExtractionSchema.model_validate(
        dict(
            entity_types=[
                dict(
                    label=n["name"],
                    description=n["description"],
                    key_property=next(
                        p["name"] for p in n["properties"] if p["is_key"]
                    ),
                    properties=n["properties"],
                )
                for n in nodes
            ],
            relationship_types=[
                dict(
                    type=r["name"],
                    description=r["description"],
                    source_entity=r["from"],
                    target_entity=r["to"],
                    properties=r["properties"],
                )
                for r in rels
            ],
        )
    )
    # The same validator/code generator as the existing ontology path catches unsafe
    # identifiers, reserved fields, invalid normalizers and generated-name collisions.
    compile(
        generate_extraction_models_code(schema, normalizers),
        "<ontology-spec-preflight>",
        "exec",
    )
    return dict(
        name=document["id"],
        version=document["version"],
        displayName=document.get("name"),
        description=document.get("description"),
        nodes=nodes,
        relationships=rels,
        alias_maps=aliases,
        blocklists=blocks,
    )


def parse_document(content: str) -> dict:
    """JSON is a YAML subset; one safe loader gives both formats duplicate checks."""
    try:
        document = yaml.load(content, Loader=_UniqueLoader)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML/JSON ontology: {exc}") from exc
    if not isinstance(document, dict):
        raise ValueError("Ontology must be a YAML/JSON object")
    validate_document(document)
    return document


async def import_document(driver, database: str, document: dict) -> dict:
    """Create a NEW ontology atomically; existing names are never overwritten."""
    payload = validate_document(document)

    async def write(tx):
        # Global uniqueness is the existing ontology DB contract. Refuse all name
        # collisions, even identically named types in another ontology.
        checks = [
            ("Ontology", [payload["name"]]),
            ("NodeType", [n["name"] for n in payload["nodes"]]),
            ("RelationshipType", [r["name"] for r in payload["relationships"]]),
            ("AliasMap", list(payload["alias_maps"])),
            ("Blocklist", list(payload["blocklists"])),
        ]
        for label, names in checks:
            result = await tx.run(
                f"MATCH (n:{label}) WHERE n.name IN $names RETURN n.name AS name LIMIT 1",
                names=names,
            )
            collision = await result.single()
            if collision:
                raise ValueError(
                    f"{label} name {collision['name']!r} already exists; import requires fresh names/a fresh ontology database"
                )
        await tx.run(
            "CREATE (o:Ontology) SET o = $metadata",
            metadata={
                k: payload[k]
                for k in ["name", "version", "displayName", "description"]
                if payload[k] is not None
            },
        )
        for kind, rows in [
            ("NodeType", payload["nodes"]),
            ("RelationshipType", payload["relationships"]),
        ]:
            for row in rows:
                result = await tx.run(
                    f"MATCH (o:Ontology {{name:$ontology}}) CREATE (o)-[:CONTAINS]->(t:{kind} {{name:$name, description:$description}}) RETURN elementId(t) AS id",
                    ontology=payload["name"],
                    name=row["name"],
                    description=row["description"],
                )
                tid = (await result.single())["id"]
                for prop in row["properties"]:
                    values = {
                        k: v
                        for k, v in prop.items()
                        if k not in {"alias_map_name", "blocklist_name"}
                        and v is not None
                    }
                    await tx.run(
                        "MATCH (t) WHERE elementId(t)=$id CREATE (t)-[:HAS_PROPERTY]->(p:PropertyDef) SET p=$properties",
                        id=tid,
                        properties=values,
                    )
                if kind == "RelationshipType":
                    await tx.run(
                        "MATCH (r:RelationshipType {name:$name}), (a:NodeType {name:$source}), (b:NodeType {name:$target}) CREATE (r)-[:FROM]->(a), (r)-[:TO]->(b)",
                        name=row["name"],
                        source=row["from"],
                        target=row["to"],
                    )
        for name, aliases in payload["alias_maps"].items():
            await tx.run(
                "MATCH (o:Ontology {name:$ontology}) CREATE (o)-[:DEFINES]->(a:AliasMap {name:$name}) WITH a UNWIND $entries AS entry CREATE (a)-[:HAS_ALIAS]->(:Alias {from:entry.source, to:entry.target})",
                ontology=payload["name"],
                name=name,
                entries=[dict(source=k, target=v) for k, v in aliases.items()],
            )
        for name, terms in payload["blocklists"].items():
            await tx.run(
                "MATCH (o:Ontology {name:$ontology}) CREATE (o)-[:DEFINES]->(b:Blocklist {name:$name}) WITH b UNWIND $terms AS term CREATE (b)-[:HAS_TERM]->(:BlockedTerm {value:term})",
                ontology=payload["name"],
                name=name,
                terms=terms,
            )
        for kind, row in [
            (kind, row)
            for kind, rows in [
                ("NodeType", payload["nodes"]),
                ("RelationshipType", payload["relationships"]),
            ]
            for row in rows
        ]:
            for prop in row["properties"]:
                for field, label, rel in [
                    ("alias_map_name", "AliasMap", "USES_ALIAS_MAP"),
                    ("blocklist_name", "Blocklist", "USES_BLOCKLIST"),
                ]:
                    if prop.get(field):
                        await tx.run(
                            f"MATCH (t:{kind} {{name:$owner}})-[:HAS_PROPERTY]->(p:PropertyDef {{name:$property}}), (v:{label} {{name:$value}}) CREATE (p)-[:{rel}]->(v)",
                            owner=row["name"],
                            property=prop["name"],
                            value=prop[field],
                        )

    async with driver.session(database=database) as session:
        await session.execute_write(write)
    return {
        "status": "success",
        "ontology_name": payload["name"],
        "nodes": len(payload["nodes"]),
        "relationships": len(payload["relationships"]),
        "schema": SCHEMA_URI,
    }


async def export_document(driver, database: str, ontology_name: str) -> dict:
    """Export current DB state, rejecting semantics the adapter cannot represent."""

    async def read(tx):
        result = await tx.run(
            "MATCH (o:Ontology {name:$name}) RETURN properties(o) AS metadata",
            name=ontology_name,
        )
        record = await result.single()
        if record is None:
            raise ValueError(f"Ontology {ontology_name!r} not found")
        return (
            record["metadata"],
            await _fetch_node_types(tx, ontology_name),
            await _fetch_relationship_types(tx, ontology_name),
            await _fetch_alias_maps(tx, ontology_name),
            await _fetch_blocklists(tx, ontology_name),
        )

    async with driver.session(database=database) as session:
        metadata, nodes, rels, aliases, blocks = await session.execute_read(read)
    document = dict(
        schema=SCHEMA_URI,
        version=metadata.get("version") or "1",
        id=ontology_name,
        nodes={},
        relationships={},
    )
    for field, source in [("name", "displayName"), ("description", "description")]:
        if metadata.get(source):
            document[field] = metadata[source]
    if aliases or blocks:
        document["extensions"] = {
            "custom": {
                EXTENSION: {
                    "alias_maps": aliases,
                    "blocklists": {n: sorted(v) for n, v in blocks.items()},
                }
            }
        }

    def props(rows):
        out = {}
        for p in rows:
            value = dict(type=p["type"] or "STRING")
            if p.get("description"):
                value["description"] = p["description"]
            if p.get("is_key"):
                value["key"] = True
            if p.get("required"):
                value["must_exist"] = True
            cfg = {
                k: v for k, v in p.items() if k in _NORMALIZER_FIELDS and v is not None
            }
            if not cfg.get("normalizers") and p.get("normalizer"):
                cfg["normalizers"] = [p["normalizer"]]
            if cfg:
                value["extensions"] = {"custom": {EXTENSION: cfg}}
            out[p["name"]] = value
        return out

    for node in nodes:
        document["nodes"][node["name"]] = dict(
            label=node["name"],
            description=node["description"] or "",
            properties=props(node["properties"]),
        )
    for rel in rels:
        document["relationships"][rel["name"]] = dict(
            type=rel["name"],
            description=rel["description"] or "",
            properties=props(rel["properties"]),
            **{"from": {"node": rel["from"]}, "to": {"node": rel["to"]}},
        )
    validate_document(document)
    return document


def serialize_document(document: dict, format: str = "yaml") -> str:
    validate_document(document)
    if format == "json":
        return json.dumps(document, indent=2, ensure_ascii=False)
    if format != "yaml":
        raise ValueError("format: use yaml or json")
    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
