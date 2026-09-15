"""Scheduler DTOs (FR-009/011, PERF-003)."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel


class ScheduleEntryOut(BaseModel):
    task_id: UUID
    title: str
    role: str
    priority: int
    decision: str  # scheduled|skipped
    reason: str


class SchedulerTickOut(BaseModel):
    project_id: UUID
    running: int
    limits: dict[str, Any]
    scheduled: list[ScheduleEntryOut]
    skipped: list[ScheduleEntryOut]
    started_count: int
    start_errors: dict[str, str]


class SchedulerStateOut(BaseModel):
    tasks_by_status: dict[str, int]
    running: int
    running_by_role: dict[str, int]
    limits: dict[str, Any]
