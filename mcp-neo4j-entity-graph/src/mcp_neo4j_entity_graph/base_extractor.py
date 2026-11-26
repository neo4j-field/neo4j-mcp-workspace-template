"""Base extractor with shared logic for text and VLM extraction.

Contains:
- Prompt building from ExtractionSchema
- LLM response parsing into internal models
- Retry logic with exponential backoff
- Model support checking
"""

from __future__ import annotations

import ast
import asyncio
import importlib.util
import inspect
import sys
from enum import Enum
from pathlib import Path
from types import ModuleType
from typing import Any, Optional, Type, Union, get_args, get_origin

import litellm
import structlog
from pydantic import BaseModel

from .models import (
    ChunkExtractionOutcome,
    ChunkExtractionResult,
    ClassifiedChunk,
    EntityTypeSchema,
    ExtractionSchema,
    ExtractedEntity,
    ExtractedRelationship,
    PropertySchema,
    RelationshipTypeSchema,
)

from .schema_validation import schema_from_models, endpoint_fields, validate_scalar

logger = structlog.get_logger()

DEFAULT_EXTRACTION_MODEL = "gpt-6-luna"


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


def _validate_source_declarations(code, filename):
    """Catch declarations Python would overwrite before contract inspection."""
    tree = ast.parse(code, filename=filename)
    names = set()
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        if node.name in names:
            raise ValueError(f"Duplicate top-level schema class declaration: {node.name}")
        names.add(node.name)
        fields = set()
        for declaration in node.body:
            if not isinstance(declaration, ast.AnnAssign) or not isinstance(declaration.target, ast.Name):
                continue
            name = declaration.target.id
            if name in fields:
                raise ValueError(f"Duplicate annotated schema field: {node.name}.{name}")
            fields.add(name)


def load_extraction_output_model(
    pydantic_model_path: str, *, source_bytes: bytes | None = None,
) -> Type[BaseModel]:
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
    # Read source directly: timestamp/size-based bytecode caches can otherwise
    # load stale validators after a rapid schema edit of the same file length.
    code = source_bytes if source_bytes is not None else path.read_bytes()
    _validate_source_declarations(code, str(path))
    exec(compile(code, str(path), "exec"), module.__dict__)

    if not hasattr(module, "ExtractionOutput"):
        raise ValueError(
            f"File {pydantic_model_path} does not contain an ExtractionOutput class"
        )

    return module.ExtractionOutput


def schema_from_pydantic_module(module: ModuleType) -> ExtractionSchema:
    """Validate the complete Pydantic output contract before graph/model work."""
    return schema_from_models(module)


def parse_extraction_response(
    content: str,
    schema: ExtractionSchema,
    chunk_id: str,
    output_model: Type[BaseModel],
) -> ChunkExtractionResult:
    """Parse LLM response into ChunkExtractionResult using the strongly-typed Pydantic model."""
    if not content:
        return ChunkExtractionResult(
            chunk_id=chunk_id,
            outcome=ChunkExtractionOutcome.FAILED,
            error="Model returned a blank structured response",
        )

    try:
        result = _parse_typed_response(content, schema, chunk_id, output_model)
        if not result.entities and not result.relationships:
            result.outcome = ChunkExtractionOutcome.EMPTY
        return result
    except Exception as e:
        logger.error(
            "Failed to parse extraction response",
            chunk_id=chunk_id,
            error=str(e),
            content_preview=content[:500],
        )
        return ChunkExtractionResult(
            chunk_id=chunk_id,
            outcome=ChunkExtractionOutcome.FAILED,
            error=f"Failed to parse structured response: {e}",
        )


def _storage_dump(model):
    # JSON mode may serialize an invalid validator return (e.g. date -> string)
    # before scalar guards see it. Preserve native values; Enum is deliberate.
    return {name: value.value if isinstance(value, Enum) else value
            for name, value in model.model_dump(mode="python").items()}


def _validate_properties(values, properties, context):
    declared = {p.name:p for p in properties}
    for name, value in values.items():
        if name not in declared:
            raise ValueError(f"{context}: undeclared property {name}")
        validate_scalar(value, declared[name].type, f"{context}.{name}")
    for prop in properties:
        if prop.required and prop.name not in values:
            raise ValueError(f"{context}: required property {prop.name} is missing")


_SKIP_SENTINEL = "__SKIP__"


def _parse_typed_response(
    content: str,
    schema: ExtractionSchema,
    chunk_id: str,
    output_model: Type[BaseModel],
) -> ChunkExtractionResult:
    """Parse response using the strongly-typed ExtractionOutput model.

    This triggers Pydantic validators (normalization, etc.) on the data.

    Entities and relationships whose key property contains the SKIP sentinel
    (set by ontology-generated validators when a value should be dropped — e.g.
    blocklisted terms, enum-validation failures) are filtered out here.
    """
    extraction = output_model.model_validate_json(content)

    entities: list[ExtractedEntity] = []
    relationships: list[ExtractedRelationship] = []
    skip_count = 0

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
                    key_property = getattr(item_class, "_key_property", None)
                    props = {
                        k: v
                        for k, v in _storage_dump(item).items()
                        if v is not None and not k.startswith("_")
                    }
                    # Drop entities whose key property is missing or marked SKIP.
                    key_value = props.get(key_property) if key_property else None
                    if any(v == _SKIP_SENTINEL for v in props.values()):
                        skip_count += 1
                        continue
                    if key_value is None or key_value == "":
                        raise ValueError(f"{label}: extracted entity key {key_property!r} is missing/empty")
                    entity_schema = schema.get_entity_schema(label)
                    if entity_schema is None:
                        raise ValueError(f"Unknown entity label {label}")
                    _validate_properties(props, entity_schema.properties, f"entity {label}")
                    entities.append(ExtractedEntity(label=label, properties=props))

                # Relationship model: has _relationship_type
                elif hasattr(item_class, "_relationship_type"):
                    rel_type = item_class._relationship_type  # type: ignore[attr-defined]
                    start_label = item_class._start_node_label  # type: ignore[attr-defined]
                    end_label = item_class._end_node_label  # type: ignore[attr-defined]
                    start_key_prop = item_class._start_key_property  # type: ignore[attr-defined]
                    end_key_prop = item_class._end_key_property  # type: ignore[attr-defined]

                    # Bind endpoints explicitly, with a validated first-two-field
                    # compatibility path for older generated schemas.
                    start_field, end_field = endpoint_fields(item_class)
                    dumped = _storage_dump(item)
                    source_key = dumped.pop(start_field, None)
                    target_key = dumped.pop(end_field, None)
                    if source_key == _SKIP_SENTINEL or target_key == _SKIP_SENTINEL:
                        skip_count += 1
                        continue
                    if source_key is None or source_key == "" or target_key is None or target_key == "":
                        raise ValueError(f"{rel_type}: extracted relationship endpoint key is missing/empty")
                    for key_value, entity_label in [(source_key, start_label), (target_key, end_label)]:
                        entity_schema = schema.get_entity_schema(entity_label)
                        if entity_schema is None:
                            raise ValueError(f"{rel_type}: undeclared endpoint label {entity_label}")
                        storage = next((p.type for p in entity_schema.properties if p.name == entity_schema.key_property), "STRING")
                        validate_scalar(key_value, storage, f"{rel_type} endpoint {entity_label}")
                    rel_props = {k:v for k,v in dumped.items() if v is not None}
                    if any(v == _SKIP_SENTINEL for v in rel_props.values()):
                        skip_count += 1
                        continue
                    rel_schema = schema.get_relationship_schema(rel_type)
                    if rel_schema is None:
                        raise ValueError(f"Unknown relationship type {rel_type}")
                    _validate_properties(rel_props, rel_schema.properties, f"relationship {rel_type}")

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

    if skip_count:
        logger.info(
            "Filtered SKIP entities/relationships",
            chunk_id=chunk_id,
            skipped=skip_count,
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
    if "gpt-6" in model_lower:
        params["reasoning_effort"] = "low"
        # The pinned LiteLLM registry predates GPT-6. Allow this OpenAI parameter
        # for these requests without changing parameter handling for other models.
        params["allowed_openai_params"] = ["reasoning_effort"]
    elif "gpt-5" in model_lower:
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
