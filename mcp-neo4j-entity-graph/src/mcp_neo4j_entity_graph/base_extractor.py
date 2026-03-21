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
import inspect
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Optional, Type, Union, get_args, get_origin

import litellm
import structlog
from pydantic import BaseModel

from .models import (
    ChunkExtractionResult,
    ClassifiedChunk,
    EntityTypeSchema,
    ExtractionSchema,
    ExtractedEntity,
    ExtractedRelationship,
    PropertySchema,
    RelationshipTypeSchema,
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


def schema_from_pydantic_module(module: ModuleType) -> ExtractionSchema:
    """Reconstruct an ExtractionSchema by introspecting a generated .py module.

    Reads ClassVars (_node_label, _key_property, _relationship_type, etc.) and
    model_fields from entity/relationship model classes. Used for pydantic-only mode
    so no JSON schema file is required.
    """

    def _unwrap_optional(annotation: Any) -> Any:
        """Unwrap Optional[X] -> X, leave other types as-is."""
        if get_origin(annotation) is Union:
            args = [a for a in get_args(annotation) if a is not type(None)]
            return args[0] if args else str
        return annotation

    def _python_to_neo4j_type(annotation: Any) -> str:
        annotation = _unwrap_optional(annotation)
        return {int: "INTEGER", float: "FLOAT", bool: "BOOLEAN"}.get(annotation, "STRING")

    entity_types: list[EntityTypeSchema] = []
    relationship_types: list[RelationshipTypeSchema] = []

    for _, cls in inspect.getmembers(module, inspect.isclass):
        if not (isinstance(cls, type) and issubclass(cls, BaseModel) and cls is not BaseModel):
            continue

        if hasattr(cls, "_node_label"):
            key_prop = cls._key_property  # type: ignore[attr-defined]
            properties = [
                PropertySchema(
                    name=fname,
                    type=_python_to_neo4j_type(finfo.annotation),
                    description=finfo.description,
                    required=finfo.is_required(),
                )
                for fname, finfo in cls.model_fields.items()
            ]
            entity_types.append(EntityTypeSchema(
                label=cls._node_label,  # type: ignore[attr-defined]
                description=(cls.__doc__ or f"A {cls._node_label} entity").strip(),
                key_property=key_prop,
                properties=properties,
            ))

        elif hasattr(cls, "_relationship_type"):
            # Relationship properties are the optional fields; required fields are endpoint keys
            rel_properties = [
                PropertySchema(
                    name=fname,
                    type=_python_to_neo4j_type(finfo.annotation),
                    description=finfo.description,
                )
                for fname, finfo in cls.model_fields.items()
                if not finfo.is_required()
            ]
            source_entity = cls._start_node_label  # type: ignore[attr-defined]
            target_entity = cls._end_node_label  # type: ignore[attr-defined]
            relationship_types.append(RelationshipTypeSchema(
                type=cls._relationship_type,  # type: ignore[attr-defined]
                description=(cls.__doc__ or f"{source_entity} to {target_entity}").strip(),
                source_entity=source_entity,
                target_entity=target_entity,
                properties=rel_properties,
            ))

    if not entity_types:
        raise ValueError("No entity model classes found in module (expected classes with _node_label ClassVar)")

    return ExtractionSchema(entity_types=entity_types, relationship_types=relationship_types)


def parse_extraction_response(
    content: str,
    schema: ExtractionSchema,
    chunk_id: str,
    output_model: Type[BaseModel],
) -> ChunkExtractionResult:
    """Parse LLM response into ChunkExtractionResult using the strongly-typed Pydantic model."""
    if not content:
        return ChunkExtractionResult(chunk_id=chunk_id)

    try:
        return _parse_typed_response(content, schema, chunk_id, output_model)
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

    # Ollama-specific: disable thinking mode and cap context window.
    # Thinking models (qwen3.5, deepseek-r1, etc.) route output to reasoning_content,
    # leaving content empty — structured output silently returns no entities.
    # Default num_ctx for some models is 262k, which pre-allocates a huge KV cache;
    # 8192 is more than enough for chunk extraction (typical chunks are 200-500 tokens).
    if model_lower.startswith("ollama/"):
        params["extra_body"] = {"think": False, "options": {"num_ctx": 8192}}

    return params
