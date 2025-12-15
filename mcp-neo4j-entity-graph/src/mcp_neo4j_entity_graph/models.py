"""Pydantic models for entity extraction.

These models define the structure for:
- Extraction schemas (what to extract)
- Extracted entities and relationships
- Extraction results with provenance
"""

from typing import Any, Optional
from pydantic import BaseModel, Field


# ============================================
# Schema Definition Models
# ============================================

class PropertySchema(BaseModel):
    """Schema for an entity or relationship property."""
    name: str = Field(..., description="Property name in camelCase")
    type: str = Field(default="STRING", description="Neo4j property type (STRING, INTEGER, FLOAT, BOOLEAN)")
    description: Optional[str] = Field(None, description="Description to help LLM extract this property")
    required: bool = Field(default=False, description="Whether this property is required")


class EntityTypeSchema(BaseModel):
    """Schema for an entity type to extract."""
    label: str = Field(..., description="Node label in PascalCase (e.g., 'Person', 'Drug')")
    description: str = Field(..., description="Description to help LLM identify this entity type")
    key_property: str = Field(..., description="Property that uniquely identifies this entity")
    properties: list[PropertySchema] = Field(default_factory=list, description="Additional properties to extract")
    
    def get_property_names(self) -> list[str]:
        """Get all property names including key property."""
        return [self.key_property] + [p.name for p in self.properties]


class RelationshipTypeSchema(BaseModel):
    """Schema for a relationship type to extract."""
    type: str = Field(..., description="Relationship type in SCREAMING_SNAKE_CASE (e.g., 'TREATS', 'INTERACTS_WITH')")
    description: str = Field(..., description="Description to help LLM identify this relationship")
    source_entity: str = Field(..., description="Source entity label")
    target_entity: str = Field(..., description="Target entity label")
    properties: list[PropertySchema] = Field(default_factory=list, description="Relationship properties to extract")


class ExtractionSchema(BaseModel):
    """Complete schema for entity extraction."""
    entity_types: list[EntityTypeSchema] = Field(..., description="Entity types to extract")
    relationship_types: list[RelationshipTypeSchema] = Field(default_factory=list, description="Relationship types to extract")
    
    def get_entity_labels(self) -> list[str]:
        """Get all entity labels."""
        return [e.label for e in self.entity_types]
    
    def get_entity_schema(self, label: str) -> Optional[EntityTypeSchema]:
        """Get schema for a specific entity type."""
        for e in self.entity_types:
            if e.label == label:
                return e
        return None


# ============================================
# Extracted Data Models
# ============================================

class ExtractedEntity(BaseModel):
    """An entity extracted from text."""
    label: str = Field(..., description="Entity type label")
    properties: dict[str, Any] = Field(..., description="Entity properties including key property")
    
    def get_key_value(self, key_property: str) -> Optional[str]:
        """Get the key property value."""
        return self.properties.get(key_property)


class ExtractedRelationship(BaseModel):
    """A relationship extracted from text."""
    type: str = Field(..., description="Relationship type")
    source_label: str = Field(..., description="Source entity label")
    source_key: str = Field(..., description="Source entity key value")
    target_label: str = Field(..., description="Target entity label")
    target_key: str = Field(..., description="Target entity key value")
    properties: dict[str, Any] = Field(default_factory=dict, description="Relationship properties")


class ChunkExtractionResult(BaseModel):
    """Extraction result for a single chunk."""
    chunk_id: str = Field(..., description="ID of the source chunk")
    entities: list[ExtractedEntity] = Field(default_factory=list)
    relationships: list[ExtractedRelationship] = Field(default_factory=list)




# ============================================
# Progress Tracking
# ============================================

class ProgressUpdate(BaseModel):
    """Progress update for long-running operations."""
    stage: str
    current: int
    total: int
    message: str

