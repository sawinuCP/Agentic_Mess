"""Task DTOs (Task Protocol reads, attempts, execution)."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class TaskIn(BaseModel):
    """Human-authored task creation (Wave 7 completion): title is required,
    everything else optional. Dependencies must reference existing tasks of
    the same project; cycles are impossible for a fresh task (nothing points
    at it yet), so no graph check is needed here.

    ``payload`` carries the executable work (e.g. ``command`` + timeouts).
    Without it the task is created but has nothing to execute. Execution stays
    policy-gated downstream (allowlist, capabilities, HITL), so accepting a
    payload here grants no privilege by itself.
    """

    title: str = Field(min_length=1, max_length=300)
    request: str = ""
    requirement_id: UUID | None = None
    parent_task_id: UUID | None = None
    priority: int = Field(default=5, ge=1)
    depends_on: list[UUID] = []
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("payload")
    @classmethod
    def _validate_payload(cls, payload: dict[str, Any]) -> dict[str, Any]:
        command = payload.get("command")
        if command is not None and (
            not isinstance(command, list)
            or not command
            or not all(isinstance(part, str) for part in command)
        ):
            raise ValueError("payload.command must be a non-empty list of strings")
        timeout = payload.get("timeout_seconds")
        if timeout is not None and (
            not isinstance(timeout, (int, float)) or not 1 <= timeout <= 3600
        ):
            raise ValueError("payload.timeout_seconds must be between 1 and 3600")
        return payload


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
