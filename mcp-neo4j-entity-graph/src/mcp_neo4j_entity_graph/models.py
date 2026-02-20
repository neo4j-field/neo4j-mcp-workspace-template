"""Pydantic models for entity extraction.

These models define the structure for:
- Extraction schemas (what to extract)
- Extracted entities and relationships
- Extraction results with provenance
- Job tracking and chunk classification
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ============================================
# Schema Definition Models
# ============================================


class PropertySchema(BaseModel):
    """Schema for an entity or relationship property."""

    name: str = Field(..., description="Property name in camelCase")
    type: str = Field(
        default="STRING",
        description="Neo4j property type (STRING, INTEGER, FLOAT, BOOLEAN)",
    )
    description: Optional[str] = Field(
        None, description="Description to help LLM extract this property"
    )
    required: bool = Field(
        default=False, description="Whether this property is required"
    )


class EntityTypeSchema(BaseModel):
    """Schema for an entity type to extract."""

    label: str = Field(
        ..., description="Node label in PascalCase (e.g., 'Person', 'Drug')"
    )
    description: str = Field(
        ..., description="Description to help LLM identify this entity type"
    )
    key_property: str = Field(
        ..., description="Property that uniquely identifies this entity"
    )
    properties: list[PropertySchema] = Field(
        default_factory=list, description="Additional properties to extract"
    )

    def get_property_names(self) -> list[str]:
        return [self.key_property] + [p.name for p in self.properties]


class RelationshipTypeSchema(BaseModel):
    """Schema for a relationship type to extract."""

    type: str = Field(
        ...,
        description="Relationship type in SCREAMING_SNAKE_CASE (e.g., 'TREATS')",
    )
    description: str = Field(
        ..., description="Description to help LLM identify this relationship"
    )
    source_entity: str = Field(..., description="Source entity label")
    target_entity: str = Field(..., description="Target entity label")
    properties: list[PropertySchema] = Field(
        default_factory=list, description="Relationship properties to extract"
    )


class ExtractionSchema(BaseModel):
    """Complete schema for entity extraction."""

    entity_types: list[EntityTypeSchema] = Field(
        ..., description="Entity types to extract"
    )
    relationship_types: list[RelationshipTypeSchema] = Field(
        default_factory=list, description="Relationship types to extract"
    )

    def get_entity_labels(self) -> list[str]:
        return [e.label for e in self.entity_types]

    def get_entity_schema(self, label: str) -> Optional[EntityTypeSchema]:
        for e in self.entity_types:
            if e.label == label:
                return e
        return None

    def get_relationship_schema(
        self, rel_type: str
    ) -> Optional[RelationshipTypeSchema]:
        for r in self.relationship_types:
            if r.type == rel_type:
                return r
        return None


# ============================================
# Extracted Data Models
# ============================================


class ExtractedEntity(BaseModel):
    """An entity extracted from a chunk."""

    label: str = Field(..., description="Entity type label")
    properties: dict[str, Any] = Field(
        ..., description="Entity properties including key property"
    )

    def get_key_value(self, key_property: str) -> Optional[str]:
        return self.properties.get(key_property)


class ExtractedRelationship(BaseModel):
    """A relationship extracted from a chunk."""

    type: str = Field(..., description="Relationship type")
    source_label: str = Field(..., description="Source entity label")
    source_key: str = Field(..., description="Source entity key value")
    target_label: str = Field(..., description="Target entity label")
    target_key: str = Field(..., description="Target entity key value")
    properties: dict[str, Any] = Field(
        default_factory=dict, description="Relationship properties"
    )


class ChunkExtractionResult(BaseModel):
    """Extraction result for a single chunk."""

    chunk_id: str = Field(..., description="ID of the source chunk")
    entities: list[ExtractedEntity] = Field(default_factory=list)
    relationships: list[ExtractedRelationship] = Field(default_factory=list)


# ============================================
# Chunk Classification
# ============================================


class ChunkType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    TABLE = "table"
    PAGE = "page"


class ClassifiedChunk(BaseModel):
    """A chunk classified for text or VLM extraction."""

    id: str
    chunk_type: ChunkType
    text: Optional[str] = None
    document_name: Optional[str] = None
    section_context: Optional[str] = None
    caption: Optional[str] = None
    image_base64: Optional[str] = None
    image_mime_type: Optional[str] = None
    text_as_html: Optional[str] = None

    @property
    def needs_vlm(self) -> bool:
        return self.chunk_type in (ChunkType.IMAGE, ChunkType.TABLE, ChunkType.PAGE) and self.image_base64 is not None


# ============================================
# Extraction Metadata (Multi-pass architecture)
# ============================================


class PassType(str, Enum):
    FULL = "full"
    ENTITIES_ONLY = "entities_only"
    RELATIONSHIPS_ONLY = "relationships_only"
    CORRECTIVE = "corrective"


class ExtractionMetadata(BaseModel):
    """Metadata stored on EXTRACTED_FROM relationships."""

    model: str = Field(..., description="LLM model used for extraction")
    timestamp: float = Field(default_factory=time.time, description="Unix timestamp")
    pass_number: int = Field(default=1, description="Pass number (1, 2, 3...)")
    pass_type: PassType = Field(default=PassType.FULL, description="Type of extraction pass")


# ============================================
# Progress Tracking
# ============================================


class ProgressUpdate(BaseModel):
    """Progress update for long-running operations."""

    stage: str
    current: int
    total: int
    message: str
