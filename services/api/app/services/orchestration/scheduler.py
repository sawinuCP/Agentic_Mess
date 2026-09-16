"""Scheduler (FR-009/011, PERF-003): bounded concurrency over the durable task graph.

Framework-free: planning is a pure read + limit accounting; the durable task-starter
is injected by the route (Temporal) or a test stub. Limits are global plus per-role
(FR-009: multiple concurrent instances of the same role are allowed up to the role
cap). Scheduling consumes the ready set of the dependency graph (spec §13/§18) and
honors resource leases (spec §18): a task whose required resources are actively
leased is skipped, never force-run. Tasks record ``role``/``spawn_depth`` in their
payload — durable facts, not agent claims (spec §48).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents_runtime.spawn_policy import may_schedule_depth
from app.core.errors import DomainError
from app.db.models import Event, Task
from app.services.orchestration import leases as lease_service

DEFAULT_ROLE = "implementer"
SCHEDULABLE_STATUSES = ("pending", "ready")  # "blocked" waits for its dependencies


@dataclass(frozen=True, slots=True)
class SchedulingLimits:
    """Configured bounds (FR-011/PERF-003). ``role_limits`` empty = global-only."""

    max_concurrency: int
    role_limits: Mapping[str, int]
    spawn_max_depth: int

    @classmethod
    def from_settings(cls, settings: Any) -> SchedulingLimits:
        raw = getattr(settings, "scheduler_role_limits", "") or ""
        role_limits: dict[str, int] = {}
        if raw.strip():
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise DomainError(
                    f"HARNESS_SCHEDULER_ROLE_LIMITS is not valid JSON: {exc}", 500
                ) from None
            if not isinstance(parsed, dict) or not all(
                isinstance(k, str) and isinstance(v, int) and v >= 1 for k, v in parsed.items()
            ):
                raise DomainError(
                    "HARNESS_SCHEDULER_ROLE_LIMITS must be a JSON object of role -> positive int",
                    500,
                )
            role_limits = parsed
        return SchedulingLimits(
            max_concurrency=max(1, int(getattr(settings, "scheduler_max_concurrency", 4))),
            role_limits=role_limits,
            spawn_max_depth=max(0, int(getattr(settings, "spawn_max_depth", 2))),
        )


@dataclass(frozen=True, slots=True)
class ScheduleEntry:
    task_id: uuid.UUID
    title: str
    role: str
    priority: int
    decision: str  # scheduled|skipped
    reason: str


@dataclass(frozen=True, slots=True)
class ScheduleTick:
    project_id: uuid.UUID
    running: int
    limits: SchedulingLimits
    entries: list[ScheduleEntry] = field(default_factory=list)

    @property
    def scheduled(self) -> list[ScheduleEntry]:
        return [e for e in self.entries if e.decision == "scheduled"]

    @property
    def skipped(self) -> list[ScheduleEntry]:
        return [e for e in self.entries if e.decision == "skipped"]


def _task_role(task: Task) -> str:
    role = task.payload.get("role") if isinstance(task.payload, dict) else None
    return str(role) if role else DEFAULT_ROLE


def _task_depth(task: Task) -> int:
    depth = task.payload.get("spawn_depth") if isinstance(task.payload, dict) else None
    try:
        return max(0, int(depth)) if depth is not None else 0
    except (TypeError, ValueError):
        return 0


def _required_resources(task: Task) -> list[tuple[str, str]]:
    """Task-declared exclusive resources (spec §13 ``resource_requirements``):
    ``[{"kind": "branch", "key": "..."}]`` in the task payload."""
    req = task.payload.get("resource_requirements") if isinstance(task.payload, dict) else None
    out: list[tuple[str, str]] = []
    for item in req or []:
        if isinstance(item, dict) and item.get("kind") and item.get("key"):
            out.append((str(item["kind"]), str(item["key"])))
    return out


def scheduler_state(db: Session, project_id: uuid.UUID, limits: SchedulingLimits) -> dict[str, Any]:
    """Durable counts for the scheduler dashboard / entry-criteria checks."""
    rows = db.execute(
        select(Task.status, func.count()).where(Task.project_id == project_id).group_by(Task.status)
    ).all()
    by_status: dict[str, int] = {status: int(count) for status, count in rows}
    running_rows = db.scalars(
        select(Task).where(Task.project_id == project_id, Task.status == "running")
    ).all()
    running_by_role: dict[str, int] = {}
    for task in running_rows:
        running_by_role[_task_role(task)] = running_by_role.get(_task_role(task), 0) + 1
    return {
        "tasks_by_status": by_status,
        "running": by_status.get("running", 0),
        "running_by_role": running_by_role,
        "limits": {
            "max_concurrency": limits.max_concurrency,
            "role_limits": dict(limits.role_limits),
            "spawn_max_depth": limits.spawn_max_depth,
        },
    }


def plan_schedule(db: Session, project_id: uuid.UUID, limits: SchedulingLimits) -> ScheduleTick:
    """One read-only scheduling pass: pick ready tasks that fit the limits.

    No durable mutation — the caller starts the chosen tasks and records them via
    ``commit_scheduled`` so a failed start strands nothing.
    """
    running_rows = db.scalars(
        select(Task).where(Task.project_id == project_id, Task.status == "running")
    ).all()
    running = len(running_rows)
    running_by_role: dict[str, int] = {}
    for task in running_rows:
        running_by_role[_task_role(task)] = running_by_role.get(_task_role(task), 0) + 1

    candidates = db.scalars(
        select(Task)
        .where(Task.project_id == project_id, Task.status.in_(SCHEDULABLE_STATUSES))
        .order_by(Task.priority, Task.created_at)
    ).all()

    def _entry(task: Task, role: str, priority: int, decision: str, reason: str) -> ScheduleEntry:
        return ScheduleEntry(
            task_id=task.id,
            title=task.title,
            role=role,
            priority=priority,
            decision=decision,
            reason=reason,
        )

    entries: list[ScheduleEntry] = []
    slots = limits.max_concurrency - running
    scheduled_roles: dict[str, int] = {}
    for task in candidates:
        role = _task_role(task)
        depth = _task_depth(task)
        priority = int(task.priority)

        if slots <= 0:
            entries.append(
                _entry(
                    task,
                    role,
                    priority,
                    "skipped",
                    f"global concurrency limit reached ({limits.max_concurrency})",
                )
            )
            continue
        role_cap = limits.role_limits.get(role)
        if (
            role_cap is not None
            and running_by_role.get(role, 0) + scheduled_roles.get(role, 0) >= role_cap
        ):
            entries.append(
                _entry(
                    task, role, priority, "skipped", f"role limit reached for {role!r} ({role_cap})"
                )
            )
            continue
        if not may_schedule_depth(depth, limits.spawn_max_depth):
            reason = (
                f"spawn depth {depth} exceeds the configured maximum ({limits.spawn_max_depth})"
            )
            entries.append(_entry(task, role, priority, "skipped", reason))
            continue
        required = _required_resources(task)
        if required:
            conflicts = [
                (kind, key)
                for kind, key in required
                if lease_service.active_leases_for(db, kind, [key])
            ]
            if conflicts:
                pretty = ", ".join(f"{kind}/{key}" for kind, key in conflicts)
                entries.append(
                    _entry(
                        task,
                        role,
                        priority,
                        "skipped",
                        f"required resources are actively leased: {pretty}",
                    )
                )
                continue

        entries.append(_entry(task, role, priority, "scheduled", "within limits"))
        scheduled_roles[role] = scheduled_roles.get(role, 0) + 1
        slots -= 1

    return ScheduleTick(project_id=project_id, running=running, limits=limits, entries=entries)


def commit_scheduled(db: Session, project_id: uuid.UUID, started: Mapping[uuid.UUID, str]) -> int:
    """Record successfully started tasks as ``running`` (durable fact, TASK-002) and
    emit ``TASK_SCHEDULED`` events. ``started`` maps task_id -> workflow_id."""
    committed = 0
    for task_id, workflow_id in started.items():
        task = db.get(Task, task_id)
        if task is None or task.project_id != project_id:
            continue
        if task.status in SCHEDULABLE_STATUSES:
            task.status = "running"
            db.add(task)
            db.add(
                Event(
                    event_type="TASK_SCHEDULED",
                    source="scheduler",
                    project_id=project_id,
                    task_id=task.id,
                    payload={"workflow_id": workflow_id, "role": _task_role(task)},
                )
            )
            committed += 1
    if committed:
        db.commit()
    return committed
