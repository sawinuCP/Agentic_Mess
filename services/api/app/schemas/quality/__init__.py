"""Quality & oversight DTOs (Phase 8, spec §23/§24)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CriterionVerifyIn(BaseModel):
    evidence_artifact_id: str  # VERIFIED only with evidence (FR-026)
    task_id: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


class ReviewRequestIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    proposal: str = Field(min_length=1)
    evidence: list[str] = Field(default_factory=list)
    reviewer_roles: list[str] = Field(default_factory=list)  # default: 2 independent
    max_rounds: int = Field(1, ge=1, le=3)


class SecurityScanIn(BaseModel):
    task_id: str | None = None
