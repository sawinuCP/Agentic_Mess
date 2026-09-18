"""Task DTOs (Task Protocol reads, attempts, execution)."""

from uuid import UUID

from pydantic import BaseModel, Field


class TaskIn(BaseModel):
    """Human-authored task creation (Wave 7 completion): title is required,
    everything else optional. Dependencies must reference existing tasks of
    the same project; cycles are impossible for a fresh task (nothing points
    at it yet), so no graph check is needed here."""

    title: str = Field(min_length=1, max_length=300)
    request: str = ""
    requirement_id: UUID | None = None
    parent_task_id: UUID | None = None
    priority: int = Field(default=5, ge=1)
    depends_on: list[UUID] = []


class AttemptOut(BaseModel):
    id: UUID
    attempt_number: int
    agent_id: UUID | None
    outcome: str | None
    failure_class: str | None
    failure_detail: str | None
    evidence_artifact_ids: list[str]


class TaskOut(BaseModel):
    id: UUID
    project_id: UUID
    plan_id: UUID | None
    requirement_id: UUID | None
    parent_task_id: UUID | None
    title: str
    request: str
    expected_output: str | None
    priority: int
    status: str
    payload: dict
    retry_policy: dict
    depends_on: list[UUID]
    attempts: list[AttemptOut]


class ExecuteOut(BaseModel):
    started: bool
    workflow_id: str | None = None
    detail: str | None = None
