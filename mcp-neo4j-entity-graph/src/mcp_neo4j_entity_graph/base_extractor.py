"""Base extractor with shared logic for text and VLM extraction.

Contains:
- Prompt building from ExtractionSchema
- LLM response parsing into internal models
- Retry logic with exponential backoff
- Model support checking
"""

from __future__ import annotations

import asyncio
import importlib.util
import json as json_module
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Optional, Type

import litellm
import structlog
from pydantic import BaseModel

from .models import (
    ChunkExtractionResult,
    ClassifiedChunk,
    ExtractionSchema,
    ExtractedEntity,
    ExtractedRelationship,
)

logger = structlog.get_logger()

DEFAULT_EXTRACTION_MODEL = "gpt-5-mini"


def build_system_prompt(schema: ExtractionSchema) -> str:
    """Build the system prompt for entity extraction."""

    entity_descriptions = []
    for entity in schema.entity_types:
        props = [entity.key_property] + [p.name for p in entity.properties if p.name != entity.key_property]
        props_str = ", ".join(props)
        entity_descriptions.append(
            f"- **{entity.label}**: {entity.description}\n"
            f"  Key property: `{entity.key_property}`\n"
            f"  Properties: {props_str}"
        )

    rel_descriptions = []
    for rel in schema.relationship_types:
        props_info = ""
        if rel.properties:
            props_names = ", ".join(p.name for p in rel.properties)
            props_info = f"\n  Properties: {props_names}"
        rel_descriptions.append(
            f"- **{rel.type}**: {rel.description}\n"
            f"  From: {rel.source_entity} -> To: {rel.target_entity}{props_info}"
        )

    return f"""You are an expert entity extractor. Extract entities and relationships from the given content.

## Entity Types to Extract:
{chr(10).join(entity_descriptions)}

## Relationship Types to Extract:
{chr(10).join(rel_descriptions) if rel_descriptions else "None specified"}

## Instructions:
1. Extract ONLY entities that match the types above
2. For each entity, fill in the properties you can identify from the content
3. The key property MUST always be provided for every entity
4. If a relationship exists between extracted entities, include it
5. Be precise - only extract what is explicitly stated or clearly implied
6. Normalize entity names consistently (e.g., "GLP-1" not "glucagon-like peptide-1" if the abbreviation is established)
7. For visual content (images, tables), extract information visible in both the image and the accompanying text
"""


def build_user_prompt_text(chunk: ClassifiedChunk) -> str:
    """Build user prompt for text-only extraction."""
    parts = []

    if chunk.document_name or chunk.section_context:
        context_parts = []
        if chunk.document_name:
            context_parts.append(chunk.document_name)
        if chunk.section_context:
            context_parts.append(chunk.section_context)
        parts.append(f"Context: {' > '.join(context_parts)}")
        parts.append("")

    parts.append("Extract entities and relationships from this text:")
    parts.append("")
    parts.append(chunk.text or "")

    return "\n".join(parts)


def build_user_prompt_vlm(chunk: ClassifiedChunk) -> list[dict[str, Any]]:
    """Build multimodal user prompt for VLM extraction.

    Returns a list of content blocks (text + image) for the user message.
    """
    text_parts = []

    if chunk.document_name or chunk.section_context:
        context_parts = []
        if chunk.document_name:
            context_parts.append(chunk.document_name)
        if chunk.section_context:
            context_parts.append(chunk.section_context)
        text_parts.append(f"Context: {' > '.join(context_parts)}")
        text_parts.append("")

    if chunk.caption:
        text_parts.append(f"Caption: {chunk.caption}")
        text_parts.append("")

    # Include extracted text (but NOT textDescription which is a VLM-generated summary)
    if chunk.text:
        text_parts.append("Extracted text:")
        text_parts.append(chunk.text)
        text_parts.append("")

    # Include HTML table representation if available
    if chunk.text_as_html:
        text_parts.append("Table HTML:")
        text_parts.append(chunk.text_as_html)
        text_parts.append("")

    text_parts.append(
        "Extract entities and relationships from the text above and the image below. "
        "Use the text for entity names and data. Use the image for layout, structure, "
        "and visual context (tables, figures, diagrams)."
    )

    content: list[dict[str, Any]] = [
        {"type": "text", "text": "\n".join(text_parts)},
        {
            "type": "image_url",
            "image_url": {
                "url": f"data:{chunk.image_mime_type or 'image/png'};base64,{chunk.image_base64}",
                "detail": "high",
            },
        },
    ]

    return content


def load_extraction_output_model(pydantic_model_path: str) -> Type[BaseModel]:
    """Dynamically load the ExtractionOutput class from a generated .py file.

    Args:
        pydantic_model_path: Path to the generated Pydantic model .py file

    Returns:
        The ExtractionOutput class from the file

    Raises:
        ValueError: If the file doesn't exist or doesn't contain ExtractionOutput
    """
    path = Path(pydantic_model_path)
    if not path.exists():
        raise ValueError(f"Pydantic model file not found: {pydantic_model_path}")

    spec = importlib.util.spec_from_file_location("extraction_models", path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Could not load module from: {pydantic_model_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules["extraction_models"] = module
    spec.loader.exec_module(module)

    if not hasattr(module, "ExtractionOutput"):
        raise ValueError(
            f"File {pydantic_model_path} does not contain an ExtractionOutput class"
        )

    return module.ExtractionOutput


def parse_extraction_response(
    content: str,
    schema: ExtractionSchema,
    chunk_id: str,
    output_model: Optional[Type[BaseModel]] = None,
) -> ChunkExtractionResult:
    """Parse LLM response into ChunkExtractionResult.

    If output_model is provided (strongly typed), it parses into that model
    and converts to our internal format using ClassVar metadata.
    Otherwise, falls back to generic parsing.
    """
    if not content:
        return ChunkExtractionResult(chunk_id=chunk_id)

    try:
        if output_model is not None:
            return _parse_typed_response(content, schema, chunk_id, output_model)
        else:
            return _parse_generic_response(content, schema, chunk_id)
    except Exception as e:
        logger.error(
            "Failed to parse extraction response",
            chunk_id=chunk_id,
            error=str(e),
            content_preview=content[:500],
        )
        return ChunkExtractionResult(chunk_id=chunk_id)


def _parse_typed_response(
    content: str,
    schema: ExtractionSchema,
    chunk_id: str,
    output_model: Type[BaseModel],
) -> ChunkExtractionResult:
    """Parse response using the strongly-typed ExtractionOutput model.

    This triggers Pydantic validators (normalization, etc.) on the data.
    """
    extraction = output_model.model_validate_json(content)

    entities: list[ExtractedEntity] = []
    relationships: list[ExtractedRelationship] = []

    # Iterate over entity fields (identified by _node_label ClassVar)
    for field_name, field_value in extraction:
        if isinstance(field_value, list):
            for item in field_value:
                if not isinstance(item, BaseModel):
                    continue

                item_class = type(item)

                # Entity model: has _node_label
                if hasattr(item_class, "_node_label"):
                    label = item_class._node_label  # type: ignore[attr-defined]
                    props = {
                        k: v
                        for k, v in item.model_dump().items()
                        if v is not None and not k.startswith("_")
                    }
                    if props:
                        entities.append(ExtractedEntity(label=label, properties=props))

                # Relationship model: has _relationship_type
                elif hasattr(item_class, "_relationship_type"):
                    rel_type = item_class._relationship_type  # type: ignore[attr-defined]
                    start_label = item_class._start_node_label  # type: ignore[attr-defined]
                    end_label = item_class._end_node_label  # type: ignore[attr-defined]
                    start_key_prop = item_class._start_key_property  # type: ignore[attr-defined]
                    end_key_prop = item_class._end_key_property  # type: ignore[attr-defined]

                    # Extract source/target keys and rel properties from fields
                    dumped = item.model_dump()
                    source_key = None
                    target_key = None
                    rel_props: dict[str, Any] = {}

                    for k, v in dumped.items():
                        if k.startswith("_") or v is None:
                            continue
                        # Heuristic: first field is source key, second is target key
                        # rest are relationship properties
                        if source_key is None:
                            source_key = str(v)
                        elif target_key is None:
                            target_key = str(v)
                        else:
                            rel_props[k] = v

                    if source_key and target_key:
                        relationships.append(
                            ExtractedRelationship(
                                type=rel_type,
                                source_label=start_label,
                                source_key=source_key,
                                target_label=end_label,
                                target_key=target_key,
                                properties=rel_props,
                            )
                        )

    return ChunkExtractionResult(
        chunk_id=chunk_id,
        entities=entities,
        relationships=relationships,
    )


def _parse_generic_response(
    content: str,
    schema: ExtractionSchema,
    chunk_id: str,
) -> ChunkExtractionResult:
    """Fallback parser when no typed model is available.

    Expects the generic ExtractionOutput format with label + properties_json.
    """
    data = json_module.loads(content)

    entities: list[ExtractedEntity] = []
    relationships: list[ExtractedRelationship] = []

    for e in data.get("entities", []):
        label = e.get("label", "")
        props_raw = e.get("properties_json", "{}")
        try:
            props = json_module.loads(props_raw) if isinstance(props_raw, str) else props_raw
        except json_module.JSONDecodeError:
            props = {"raw": props_raw}

        entity_schema = schema.get_entity_schema(label)
        if entity_schema:
            key_prop = entity_schema.key_property
            if key_prop in props and isinstance(props[key_prop], str):
                props[key_prop] = props[key_prop].strip()

        entities.append(ExtractedEntity(label=label, properties=props))

    for r in data.get("relationships", []):
        relationships.append(
            ExtractedRelationship(
                type=r.get("type", ""),
                source_label=r.get("source_label", ""),
                source_key=str(r.get("source_key", "")).strip(),
                target_label=r.get("target_label", ""),
                target_key=str(r.get("target_key", "")).strip(),
                properties=r.get("properties", {}),
            )
        )

    return ChunkExtractionResult(
        chunk_id=chunk_id,
        entities=entities,
        relationships=relationships,
    )


def build_llm_params(
    model: str,
    response_format: Any,
) -> dict[str, Any]:
    """Build base LLM API parameters with model-specific config."""
    params: dict[str, Any] = {
        "model": model,
        "response_format": response_format,
    }

    model_lower = model.lower()
    if "gpt-5" in model_lower:
        params["reasoning_effort"] = "low"
    elif "o1" in model_lower or "o3" in model_lower:
        pass  # no temperature for reasoning models
    else:
        params["temperature"] = 0.0

    return params
