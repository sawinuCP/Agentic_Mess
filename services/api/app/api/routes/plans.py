"""Plans: requirement decomposition into a durable task graph (FR-006, spec §13)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.errors import DomainError
from app.db.models import Plan, Requirement, Task, TaskDependency
from app.events.recorder import record_event
from app.tasks.graph import find_cycle

router = APIRouter(tags=["plans"])


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
    id: uuid.UUID
    requirement_id: uuid.UUID
    version: int
    summary: str | None
    status: str
    task_ids: list[uuid.UUID]


def _requirement_or_404(requirement_id: uuid.UUID, db: Session) -> Requirement:
    requirement = db.get(Requirement, requirement_id)
    if requirement is None:
        raise DomainError("Requirement not found", 404)
    return requirement


@router.post("/api/requirements/{requirement_id}/plans", response_model=PlanOut, status_code=201)
async def create_plan(
    requirement_id: uuid.UUID,
    body: PlanIn,
    request: Request,
    db: Session = Depends(get_db),
) -> PlanOut:
    """Create a plan version and its tasks as a durable, acyclic task graph."""
    requirement = _requirement_or_404(requirement_id, db)
    if not body.tasks:
        raise DomainError("A plan needs at least one task", 422)

    plan = Plan(requirement_id=requirement.id, summary=body.summary)
    db.add(plan)
    db.flush()

    created: dict[str, uuid.UUID] = {}
    edges: list[tuple[uuid.UUID, uuid.UUID]] = []
    for spec in body.tasks:
        task = Task(
            project_id=requirement.project_id,
            plan_id=plan.id,
            requirement_id=requirement.id,
            title=spec.title,
            request=spec.request,
            expected_output=spec.expected_output,
            priority=spec.priority,
            payload=spec.payload,
            allowed_tools=spec.allowed_tools,
            retry_policy=spec.retry_policy,
        )
        db.add(task)
        db.flush()
        created[spec.title] = task.id
        for dep_title in spec.depends_on:
            if dep_title not in created:
                raise DomainError(
                    f"Unknown dependency '{dep_title}' (must be a title of an earlier task)", 422
                )
            edges.append((task.id, created[dep_title]))

    # Reject dependency cycles up-front (spec §18).
    for task_id, depends_on in edges:
        others = {tid: deps for tid, deps in _existing_edges(db, created).items() if tid != task_id}
        cycle = find_cycle(task_id=task_id, depends_on=[depends_on], existing=others)
        if cycle is not None:
            db.rollback()
            raise DomainError(_cycle_msg(cycle), 422)
        db.add(TaskDependency(task_id=task_id, depends_on_task_id=depends_on))
    db.commit()

    await record_event(
        request.app.state.session_factory,
        "PLAN_CREATED",
        project_id=requirement.project_id,
        payload={
            "plan_id": str(plan.id),
            "requirement_id": str(requirement.id),
            "tasks": len(body.tasks),
        },
    )
    task_ids = list(db.scalars(select(Task.id).where(Task.plan_id == plan.id)).all())
    return PlanOut(
        id=plan.id,
        requirement_id=plan.requirement_id,
        version=plan.version,
        summary=plan.summary,
        status=plan.status,
        task_ids=task_ids,
    )


def _existing_edges(
    db: Session, task_ids: dict[str, uuid.UUID]
) -> dict[uuid.UUID, list[uuid.UUID]]:
    result: dict[uuid.UUID, list[uuid.UUID]] = {}
    for tid in task_ids.values():
        deps = db.scalars(
            select(TaskDependency.depends_on_task_id).where(TaskDependency.task_id == tid)
        ).all()
        result[tid] = list(deps)
    return result


def _cycle_msg(cycle: list[uuid.UUID]) -> str:
    return "Task dependency cycle detected: " + " -> ".join(str(c)[:8] for c in cycle)
