"""Load an ontology from the Ontology DB and convert to ExtractionSchema + normalizer configs.

The Ontology DB graph schema is defined in `docs/ONTOLOGY_DB_SCHEMA.md`. This
module is the authoritative reader of that schema — every Cypher query here
must stay consistent with the documented contract.

Returns:
    (ExtractionSchema, normalizers)

where `normalizers` is keyed by `f"{NodeType}.{PropertyDef}"` (or
`f"{RelationshipType}.{PropertyDef}"`) and `f"{NodeType}.__model__"` for
model-level (compose_name_from_fields) configs.
"""

from __future__ import annotations

from typing import Any

from neo4j import AsyncDriver

from .models import (
    EntityTypeSchema,
    ExtractionSchema,
    PropertySchema,
    RelationshipTypeSchema,
)
from .normalizer_templates import NormalizerConfig


MODEL_KEY_SUFFIX = "__model__"


async def load_ontology(
    driver: AsyncDriver,
    database: str,
    ontology_name: str,
) -> tuple[ExtractionSchema, dict[str, list[NormalizerConfig]]]:
    """Read an ontology from the Ontology DB and return schema + normalizer configs."""

    async with driver.session(database=database) as session:
        # 1. Verify ontology exists
        result = await session.run(
            "MATCH (o:Ontology {name: $name}) RETURN o.name AS name LIMIT 1",
            name=ontology_name,
        )
        rec = await result.single()
        if rec is None:
            raise ValueError(
                f"Ontology '{ontology_name}' not found in database '{database}'. "
                f"Create it via :Ontology nodes first."
            )

        # 2. Fetch entity types with their properties
        node_types = await _fetch_node_types(session, ontology_name)

        # 3. Fetch relationship types
        relationship_types = await _fetch_relationship_types(session, ontology_name)

        # 4. Fetch alias maps and blocklists referenced by properties
        alias_maps = await _fetch_alias_maps(session, ontology_name)
        blocklists = await _fetch_blocklists(session, ontology_name)

    entity_schemas: list[EntityTypeSchema] = []
    normalizers: dict[str, list[NormalizerConfig]] = {}

    for nt in node_types:
        properties = []
        key_property: str | None = None
        compose_template: dict[str, Any] | None = None

        for p in nt["properties"]:
            properties.append(
                PropertySchema(
                    name=p["name"],
                    type=p.get("type") or "STRING",
                    description=p.get("description"),
                    required=bool(p.get("required", False)),
                )
            )
            if p.get("is_key"):
                key_property = p["name"]

            # pd.normalizers (array) takes priority; fall back to pd.normalizer (single string)
            raw_tags = p.get("normalizers") or ([p.get("normalizer")] if p.get("normalizer") else [])
            normalizer_tags = [t for t in raw_tags if t]

            if "compose_name_from_fields" in normalizer_tags:
                compose_template = {
                    "name_field": p["name"],
                    "template": p.get("name_template") or "",
                }
                normalizer_tags = [t for t in normalizer_tags if t != "compose_name_from_fields"]

            if normalizer_tags:
                normalizers[f"{nt['name']}.{p['name']}"] = [
                    _build_normalizer_config(tag, p, alias_maps, blocklists)
                    for tag in normalizer_tags
                ]

        if compose_template:
            normalizers[f"{nt['name']}.{MODEL_KEY_SUFFIX}"] = [NormalizerConfig(
                tag="compose_name_from_fields",
                name_template=compose_template["template"],
                # Stash the target field name in alias_map_name (reused as a string slot).
                alias_map_name=compose_template["name_field"],
            )]

        if key_property is None:
            raise ValueError(
                f"NodeType '{nt['name']}' has no PropertyDef with is_key=true. "
                f"Every entity type must have exactly one key property."
            )

        entity_schemas.append(
            EntityTypeSchema(
                label=nt["name"],
                description=nt.get("description") or f"A {nt['name']} entity",
                key_property=key_property,
                properties=properties,
            )
        )

    rel_schemas: list[RelationshipTypeSchema] = []
    for rt in relationship_types:
        rel_props = []
        for p in rt["properties"]:
            rel_props.append(
                PropertySchema(
                    name=p["name"],
                    type=p.get("type") or "STRING",
                    description=p.get("description"),
                    required=bool(p.get("required", False)),
                )
            )
            raw_tags = p.get("normalizers") or ([p.get("normalizer")] if p.get("normalizer") else [])
            normalizer_tags = [t for t in raw_tags if t and t != "compose_name_from_fields"]
            if normalizer_tags:
                normalizers[f"{rt['name']}.{p['name']}"] = [
                    _build_normalizer_config(tag, p, alias_maps, blocklists)
                    for tag in normalizer_tags
                ]

        rel_schemas.append(
            RelationshipTypeSchema(
                type=rt["name"],
                description=rt.get("description") or f"{rt['from']} to {rt['to']}",
                source_entity=rt["from"],
                target_entity=rt["to"],
                properties=rel_props,
            )
        )

    schema = ExtractionSchema(
        entity_types=entity_schemas,
        relationship_types=rel_schemas,
    )
    return schema, normalizers


# ── Cypher reads ─────────────────────────────────────────────────────────────

_NODE_TYPES_QUERY = """
MATCH (o:Ontology {name: $ontology_name})-[:CONTAINS]->(nt:NodeType)
OPTIONAL MATCH (nt)-[:HAS_PROPERTY]->(pd:PropertyDef)
OPTIONAL MATCH (pd)-[:USES_ALIAS_MAP]->(am:AliasMap)
OPTIONAL MATCH (pd)-[:USES_BLOCKLIST]->(bl:Blocklist)
WITH nt, pd, am, bl
ORDER BY nt.name, coalesce(pd.is_key, false) DESC, pd.name
RETURN
    nt.name AS node_type_name,
    nt.description AS node_type_description,
    collect({
        name: pd.name,
        type: pd.type,
        description: pd.description,
        required: pd.required,
        is_key: pd.is_key,
        normalizer: pd.normalizer,
        normalizers: pd.normalizers,
        regex_pattern: pd.regex_pattern,
        regex_replacement: pd.regex_replacement,
        enum_values: pd.enum_values,
        name_template: pd.name_template,
        alias_map_name: am.name,
        blocklist_name: bl.name
    }) AS properties
"""


async def _fetch_node_types(session, ontology_name: str) -> list[dict[str, Any]]:
    result = await session.run(_NODE_TYPES_QUERY, ontology_name=ontology_name)
    out = []
    async for rec in result:
        # Filter out null-padding properties (a NodeType with zero PropertyDef returns one null entry)
        props = [p for p in rec["properties"] if p.get("name") is not None]
        out.append({
            "name": rec["node_type_name"],
            "description": rec["node_type_description"],
            "properties": props,
        })
    return out


_REL_TYPES_QUERY = """
MATCH (o:Ontology {name: $ontology_name})-[:CONTAINS]->(rt:RelationshipType)
MATCH (rt)-[:FROM]->(src:NodeType)
MATCH (rt)-[:TO]->(tgt:NodeType)
OPTIONAL MATCH (rt)-[:HAS_PROPERTY]->(pd:PropertyDef)
OPTIONAL MATCH (pd)-[:USES_ALIAS_MAP]->(am:AliasMap)
OPTIONAL MATCH (pd)-[:USES_BLOCKLIST]->(bl:Blocklist)
WITH rt, src, tgt, pd, am, bl
ORDER BY rt.name, pd.name
RETURN
    rt.name AS rel_type_name,
    rt.description AS rel_type_description,
    src.name AS from_name,
    tgt.name AS to_name,
    collect({
        name: pd.name,
        type: pd.type,
        description: pd.description,
        required: pd.required,
        is_key: pd.is_key,
        normalizer: pd.normalizer,
        normalizers: pd.normalizers,
        regex_pattern: pd.regex_pattern,
        regex_replacement: pd.regex_replacement,
        enum_values: pd.enum_values,
        name_template: pd.name_template,
        alias_map_name: am.name,
        blocklist_name: bl.name
    }) AS properties
"""


async def _fetch_relationship_types(session, ontology_name: str) -> list[dict[str, Any]]:
    result = await session.run(_REL_TYPES_QUERY, ontology_name=ontology_name)
    out = []
    async for rec in result:
        props = [p for p in rec["properties"] if p.get("name") is not None]
        out.append({
            "name": rec["rel_type_name"],
            "description": rec["rel_type_description"],
            "from": rec["from_name"],
            "to": rec["to_name"],
            "properties": props,
        })
    return out


_ALIAS_MAPS_QUERY = """
MATCH (o:Ontology {name: $ontology_name})-[:DEFINES]->(am:AliasMap)
OPTIONAL MATCH (am)-[:HAS_ALIAS]->(a:Alias)
RETURN am.name AS map_name, collect({from: a.from, to: a.to}) AS aliases
"""


async def _fetch_alias_maps(session, ontology_name: str) -> dict[str, dict[str, str]]:
    result = await session.run(_ALIAS_MAPS_QUERY, ontology_name=ontology_name)
    out: dict[str, dict[str, str]] = {}
    async for rec in result:
        mapping = {
            a["from"]: a["to"]
            for a in rec["aliases"]
            if a.get("from") is not None and a.get("to") is not None
        }
        out[rec["map_name"]] = mapping
    return out


_BLOCKLISTS_QUERY = """
MATCH (o:Ontology {name: $ontology_name})-[:DEFINES]->(bl:Blocklist)
OPTIONAL MATCH (bl)-[:HAS_TERM]->(t:BlockedTerm)
RETURN bl.name AS list_name, collect(t.value) AS terms
"""


async def _fetch_blocklists(session, ontology_name: str) -> dict[str, frozenset[str]]:
    result = await session.run(_BLOCKLISTS_QUERY, ontology_name=ontology_name)
    out: dict[str, frozenset[str]] = {}
    async for rec in result:
        terms = frozenset(t for t in rec["terms"] if t is not None)
        out[rec["list_name"]] = terms
    return out


def _build_normalizer_config(
    tag: str,
    prop: dict[str, Any],
    alias_maps: dict[str, dict[str, str]],
    blocklists: dict[str, frozenset[str]],
) -> NormalizerConfig:
    """Build a NormalizerConfig from a property's metadata, resolving alias_map / blocklist refs."""

    cfg = NormalizerConfig(tag=tag)

    if tag == "alias_map":
        ref = prop.get("alias_map_name")
        if ref and ref in alias_maps:
            cfg.alias_map = alias_maps[ref]
            cfg.alias_map_name = ref
    elif tag == "blocklist":
        ref = prop.get("blocklist_name")
        if ref and ref in blocklists:
            cfg.blocklist = blocklists[ref]
            cfg.blocklist_name = ref
    elif tag == "regex_normalize":
        cfg.regex_pattern = prop.get("regex_pattern") or ""
        cfg.regex_replacement = prop.get("regex_replacement") or ""
    elif tag == "regex_skip":
        cfg.regex_pattern = prop.get("regex_pattern") or ""
    elif tag == "enum_validate":
        ev = prop.get("enum_values")
        cfg.enum_values = list(ev) if ev else []

    return cfg
