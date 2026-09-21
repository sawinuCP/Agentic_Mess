"""Requirement/acceptance-criteria/plan DTOs (spec §13, §23)."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class CriterionIn(BaseModel):
    description: str
    kind: str = "manual"  # automated_test | command | manual
    mandatory: bool = True


class RequirementIn(BaseModel):
    title: str
    description: str
    desired_outcome: str | None = None
    priority: str = "should"  # must | should | could
    criteria: list[CriterionIn] = Field(default_factory=list)


class CriterionOut(BaseModel):
    id: UUID
    description: str
    kind: str
    mandatory: bool
    status: str


class RequirementOut(BaseModel):
    id: UUID
    project_id: UUID
    title: str
    description: str
    desired_outcome: str | None
    priority: str
    status: str
    version: int
    created_at: datetime
    criteria: list[CriterionOut]


class TaskSpecIn(BaseModel):
    title: str
    request: str
    expected_output: str | None = None
    priority: int = 5
    payload: dict = Field(default_factory=dict)
    allowed_tools: list[str] = Field(default_factory=list)
    retry_policy: dict = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)  # titles of earlier tasks


class PlanIn(BaseModel):
    summary: str | None = None
    tasks: list[TaskSpecIn] = Field(default_factory=list)


class PlanOut(BaseModel):
    id: UUID
    requirement_id: UUID
    version: int
    summary: str | None
    status: str
    task_ids: list[UUID]
