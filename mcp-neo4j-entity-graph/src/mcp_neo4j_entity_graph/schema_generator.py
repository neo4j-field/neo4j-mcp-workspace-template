"""Generate extraction-ready Pydantic models from a data model schema.

Produces a .py file with:
- Per-entity models with explicit typed fields (key required, rest Optional)
- Per-relationship models with meaningful field names (strongly typed)
- ExtractionOutput wrapper containing lists of all entity/relationship types
- Basic validators (strip whitespace on key properties)
- ClassVar metadata for Neo4j write operations

The generated file is designed to be user-customizable: users can add
domain-specific validators (normalization, enum constraints, regex patterns)
before running extraction.
"""

from __future__ import annotations

import json
import re
import textwrap
from typing import Any

from .models import ExtractionSchema


def _to_snake_case(name: str) -> str:
    """Convert PascalCase or SCREAMING_SNAKE_CASE to snake_case."""
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    s = re.sub(r"([a-z\d])([A-Z])", r"\1_\2", s)
    return s.lower()


def _pluralize(name: str) -> str:
    """Naive English pluralization for field names."""
    if name.endswith("s") or name.endswith("x") or name.endswith("z"):
        return name + "es"
    if name.endswith("y") and len(name) > 1 and name[-2] not in "aeiou":
        return name[:-1] + "ies"
    return name + "s"


def _to_field_name(label: str, key_prop: str) -> str:
    """Create a readable field name for a relationship endpoint.

    E.g., ("Drug", "name") -> "drug_name"
         ("ClinicalStudy", "trialId") -> "clinical_study_trial_id"
    """
    label_snake = _to_snake_case(label)
    prop_snake = _to_snake_case(key_prop)
    return f"{label_snake}_{prop_snake}"


def _neo4j_type_to_python(neo4j_type: str) -> str:
    """Map Neo4j property type to Python type annotation string."""
    mapping = {
        "STRING": "str",
        "INTEGER": "int",
        "FLOAT": "float",
        "BOOLEAN": "bool",
    }
    return mapping.get(neo4j_type.upper(), "str")


def generate_extraction_models_code(schema: ExtractionSchema) -> str:
    """Generate Python code for extraction-ready Pydantic models.

    Args:
        schema: Validated ExtractionSchema

    Returns:
        Python source code as a string, ready to be written to a .py file
    """
    lines: list[str] = []

    # Header
    lines.append('"""Auto-generated Pydantic models for entity extraction.')
    lines.append("")
    lines.append("Generated from extraction schema. You can customize this file:")
    lines.append("- Add field_validator decorators for domain-specific normalization")
    lines.append("- Add Literal types or Enum constraints for controlled vocabularies")
    lines.append("- Adjust field descriptions to guide the LLM better")
    lines.append("")
    lines.append("The ExtractionOutput class at the bottom is the response_format")
    lines.append("sent to the LLM for structured extraction.")
    lines.append('"""')
    lines.append("")
    lines.append("from __future__ import annotations")
    lines.append("")
    lines.append("from typing import ClassVar, Optional")
    lines.append("")
    lines.append("from pydantic import BaseModel, Field, field_validator")
    lines.append("")
    lines.append("")

    # Build a lookup for entity key properties
    entity_key_props: dict[str, str] = {}
    entity_key_descs: dict[str, str] = {}
    for et in schema.entity_types:
        entity_key_props[et.label] = et.key_property
        # Find key property description
        key_desc = f"Key property for {et.label}"
        for p in et.properties:
            if p.name == et.key_property and p.description:
                key_desc = p.description
                break
        entity_key_descs[et.label] = key_desc

    # ---- Entity Models ----
    lines.append("# " + "=" * 60)
    lines.append("# Entity Models")
    lines.append("# " + "=" * 60)
    lines.append("")

    for et in schema.entity_types:
        class_name = f"{et.label}Entity"
        lines.append(f"class {class_name}(BaseModel):")
        if et.description:
            lines.append(f'    """{et.description}"""')
        lines.append("")
        lines.append(f'    _node_label: ClassVar[str] = "{et.label}"')
        lines.append(f'    _key_property: ClassVar[str] = "{et.key_property}"')
        lines.append("")

        # Key property (required)
        key_desc = entity_key_descs.get(et.label, f"{et.key_property}")
        py_type = "str"
        # Check if key prop has a type override
        for p in et.properties:
            if p.name == et.key_property:
                py_type = _neo4j_type_to_python(p.type)
                if p.description:
                    key_desc = p.description
                break

        lines.append(
            f"    {et.key_property}: {py_type} = "
            f'Field(..., description="{_escape(key_desc)}")'
        )

        # Additional properties (Optional)
        for prop in et.properties:
            if prop.name == et.key_property:
                continue
            py_type = _neo4j_type_to_python(prop.type)
            desc = _escape(prop.description or f"{prop.name} property")
            lines.append(
                f"    {prop.name}: Optional[{py_type}] = "
                f'Field(default=None, description="{desc}")'
            )

        # Basic validator for key property: strip whitespace
        lines.append("")
        lines.append(f'    @field_validator("{et.key_property}", mode="before")')
        lines.append("    @classmethod")
        lines.append(f"    def _normalize_{_to_snake_case(et.key_property)}(cls, v: object) -> object:")
        lines.append('        if isinstance(v, str):')
        lines.append('            return v.strip()')
        lines.append('        return v')
        lines.append("")
        lines.append("")

    # ---- Relationship Models (strongly typed) ----
    lines.append("# " + "=" * 60)
    lines.append("# Relationship Models")
    lines.append("# " + "=" * 60)
    lines.append("")

    for rel in schema.relationship_types:
        class_name = _pascal_from_screaming_snake(rel.type)

        source_key = entity_key_props.get(rel.source_entity, "id")
        target_key = entity_key_props.get(rel.target_entity, "id")
        source_field = _to_field_name(rel.source_entity, source_key)
        target_field = _to_field_name(rel.target_entity, target_key)

        # Handle self-referencing relationships (same label for source and target)
        if source_field == target_field:
            source_field = f"source_{source_field}"
            target_field = f"target_{target_field}"

        source_desc = entity_key_descs.get(
            rel.source_entity, f"Key of {rel.source_entity}"
        )
        target_desc = entity_key_descs.get(
            rel.target_entity, f"Key of {rel.target_entity}"
        )

        lines.append(f"class {class_name}Rel(BaseModel):")
        if rel.description:
            lines.append(f'    """{rel.description}"""')
        lines.append("")
        lines.append(f'    _relationship_type: ClassVar[str] = "{rel.type}"')
        lines.append(f'    _start_node_label: ClassVar[str] = "{rel.source_entity}"')
        lines.append(f'    _end_node_label: ClassVar[str] = "{rel.target_entity}"')
        lines.append(f'    _start_key_property: ClassVar[str] = "{source_key}"')
        lines.append(f'    _end_key_property: ClassVar[str] = "{target_key}"')
        lines.append("")

        # Source and target key fields
        source_py_type = "str"
        target_py_type = "str"
        for et in schema.entity_types:
            if et.label == rel.source_entity:
                for p in et.properties:
                    if p.name == source_key:
                        source_py_type = _neo4j_type_to_python(p.type)
            if et.label == rel.target_entity:
                for p in et.properties:
                    if p.name == target_key:
                        target_py_type = _neo4j_type_to_python(p.type)

        lines.append(
            f"    {source_field}: {source_py_type} = "
            f'Field(..., description="{_escape(source_desc)}")'
        )
        lines.append(
            f"    {target_field}: {target_py_type} = "
            f'Field(..., description="{_escape(target_desc)}")'
        )

        # Relationship properties (Optional)
        for prop in rel.properties:
            py_type = _neo4j_type_to_python(prop.type)
            desc = _escape(prop.description or f"{prop.name} property")
            lines.append(
                f"    {prop.name}: Optional[{py_type}] = "
                f'Field(default=None, description="{desc}")'
            )

        lines.append("")
        lines.append("")

    # ---- ExtractionOutput Wrapper ----
    lines.append("# " + "=" * 60)
    lines.append("# Extraction Output (response_format for LLM)")
    lines.append("# " + "=" * 60)
    lines.append("")
    lines.append("class ExtractionOutput(BaseModel):")
    lines.append('    """Complete extraction output for a single chunk or page.')
    lines.append("")
    lines.append("    This model is used as response_format for structured LLM extraction.")
    lines.append("    Each field is a list of extracted entities or relationships.")
    lines.append('    """')
    lines.append("")

    # Entity list fields
    for et in schema.entity_types:
        field_name = _pluralize(_to_snake_case(et.label))
        class_name = f"{et.label}Entity"
        lines.append(
            f"    {field_name}: list[{class_name}] = "
            f'Field(default_factory=list, description="Extracted {et.label} entities")'
        )

    lines.append("")

    # Relationship list fields
    for rel in schema.relationship_types:
        field_name = _to_snake_case(rel.type)
        class_name = _pascal_from_screaming_snake(rel.type) + "Rel"
        desc = _escape(rel.description or f"{rel.type} relationships")
        lines.append(
            f"    {field_name}: list[{class_name}] = "
            f'Field(default_factory=list, description="{desc}")'
        )

    lines.append("")

    return "\n".join(lines)


def generate_extraction_schema_json(schema: ExtractionSchema) -> dict[str, Any]:
    """Generate extraction schema JSON from a validated ExtractionSchema.

    This JSON is used by the server for Neo4j write operations (key property
    lookups, label mapping, etc.) and for prompt generation.
    """
    return schema.model_dump()


# ============================================
# Helpers
# ============================================


def _escape(s: str) -> str:
    """Escape a string for use inside double-quoted Python strings."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def _pascal_from_screaming_snake(name: str) -> str:
    """Convert SCREAMING_SNAKE_CASE to PascalCase.

    E.g., "INVESTIGATED_IN" -> "InvestigatedIn"
    """
    return "".join(word.capitalize() for word in name.split("_"))
