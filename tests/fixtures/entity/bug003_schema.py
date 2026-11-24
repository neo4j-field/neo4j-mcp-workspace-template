"""Deterministic extraction schema for BUG-003 coverage tests."""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field


class Bug003SentinelEntity(BaseModel):
    _node_label: ClassVar[str] = "Bug003Sentinel"
    _key_property: ClassVar[str] = "sentinelId"

    sentinelId: str = Field(..., description="Distinct source-unit sentinel")
    testRunId: str | None = Field(default=None, description="Fixture ownership marker")


class ExtractionOutput(BaseModel):
    bug003_sentinels: list[Bug003SentinelEntity] = Field(default_factory=list)
