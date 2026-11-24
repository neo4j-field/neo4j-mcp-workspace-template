"""Extraction schema for the synthetic maintenance golden set."""

from typing import ClassVar

from pydantic import BaseModel, Field, field_validator


class TechnicianEntity(BaseModel):
    _node_label: ClassVar[str] = "Technician"
    _key_property: ClassVar[str] = "name"
    name: str = Field(..., description="Named technician who performed work")

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return value.strip().casefold()


class EquipmentEntity(BaseModel):
    _node_label: ClassVar[str] = "Equipment"
    _key_property: ClassVar[str] = "equipmentId"
    equipmentId: str = Field(..., description="Explicit pump identifier, such as PX-17")

    @field_validator("equipmentId")
    @classmethod
    def normalize_id(cls, value: str) -> str:
        return value.strip().casefold()


class FacilityEntity(BaseModel):
    _node_label: ClassVar[str] = "Facility"
    _key_property: ClassVar[str] = "name"
    name: str = Field(..., description="Explicitly named facility")

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return value.strip().casefold()


class InspectedRel(BaseModel):
    _relationship_type: ClassVar[str] = "INSPECTED"
    _start_node_label: ClassVar[str] = "Technician"
    _end_node_label: ClassVar[str] = "Equipment"
    _start_key_property: ClassVar[str] = "name"
    _end_key_property: ClassVar[str] = "equipmentId"
    technician_name: str = Field(..., description="Technician name")
    equipment_equipment_id: str = Field(..., description="Inspected equipment ID")

    @field_validator("technician_name", "equipment_equipment_id")
    @classmethod
    def normalize_endpoint(cls, value: str) -> str:
        return value.strip().casefold()


class LocatedAtRel(BaseModel):
    _relationship_type: ClassVar[str] = "LOCATED_AT"
    _start_node_label: ClassVar[str] = "Equipment"
    _end_node_label: ClassVar[str] = "Facility"
    _start_key_property: ClassVar[str] = "equipmentId"
    _end_key_property: ClassVar[str] = "name"
    equipment_equipment_id: str = Field(..., description="Equipment ID")
    facility_name: str = Field(..., description="Facility name")

    @field_validator("equipment_equipment_id", "facility_name")
    @classmethod
    def normalize_endpoint(cls, value: str) -> str:
        return value.strip().casefold()


class ExtractionOutput(BaseModel):
    technicians: list[TechnicianEntity] = Field(default_factory=list)
    equipment: list[EquipmentEntity] = Field(default_factory=list)
    facilities: list[FacilityEntity] = Field(default_factory=list)
    inspected: list[InspectedRel] = Field(default_factory=list)
    located_at: list[LocatedAtRel] = Field(default_factory=list)
