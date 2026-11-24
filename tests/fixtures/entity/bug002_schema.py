"""Deterministic extraction schema for the BUG-002 relationship regression."""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field


class Bug002PersonEntity(BaseModel):
    _node_label: ClassVar[str] = "Bug002Person"
    _key_property: ClassVar[str] = "personId"

    personId: str = Field(..., description="Fixture person identifier")
    testRunId: str | None = Field(default=None, description="Fixture ownership marker")


class Bug002ProjectEntity(BaseModel):
    _node_label: ClassVar[str] = "Bug002Project"
    _key_property: ClassVar[str] = "projectId"

    projectId: str = Field(..., description="Fixture project identifier")
    testRunId: str | None = Field(default=None, description="Fixture ownership marker")


class Bug002AssignedToRel(BaseModel):
    _relationship_type: ClassVar[str] = "BUG002_ASSIGNED_TO"
    _start_node_label: ClassVar[str] = "Bug002Person"
    _end_node_label: ClassVar[str] = "Bug002Project"
    _start_key_property: ClassVar[str] = "personId"
    _end_key_property: ClassVar[str] = "projectId"

    bug002_person_person_id: str = Field(..., description="Fixture person identifier")
    bug002_project_project_id: str = Field(..., description="Fixture project identifier")


class ExtractionOutput(BaseModel):
    bug002_people: list[Bug002PersonEntity] = Field(default_factory=list)
    bug002_projects: list[Bug002ProjectEntity] = Field(default_factory=list)
    bug002_assigned_to: list[Bug002AssignedToRel] = Field(default_factory=list)
