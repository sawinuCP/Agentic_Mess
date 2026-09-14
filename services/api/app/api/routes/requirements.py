"""Requirements and acceptance criteria (FR-005, FR-013 traceability roots)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_project
from app.core.errors import DomainError
from app.db.models import AcceptanceCriterion, Project, Requirement
from app.events.recorder import record_event

router = APIRouter(tags=["requirements"])


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
    id: uuid.UUID
    description: str
    kind: str
    mandatory: bool
    status: str


class RequirementOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    description: str
    desired_outcome: str | None
    priority: str
    status: str
    version: int
    criteria: list[CriterionOut]


def _requirement_or_404(requirement_id: uuid.UUID, db: Session) -> Requirement:
    requirement = db.get(Requirement, requirement_id)
    if requirement is None:
        raise DomainError("Requirement not found", 404)
    return requirement


def _criteria_out(db: Session, requirement_id: uuid.UUID) -> list[CriterionOut]:
    rows = db.scalars(
        select(AcceptanceCriterion)
        .where(AcceptanceCriterion.requirement_id == requirement_id)
        .order_by(AcceptanceCriterion.created_at)
    ).all()
    return [
        CriterionOut(
            id=c.id, description=c.description, kind=c.kind, mandatory=c.mandatory, status=c.status
        )
        for c in rows
    ]


def requirement_out(db: Session, requirement: Requirement) -> RequirementOut:
    return RequirementOut(
        id=requirement.id,
        project_id=requirement.project_id,
        title=requirement.title,
        description=requirement.description,
        desired_outcome=requirement.desired_outcome,
        priority=requirement.priority,
        status=requirement.status,
        version=requirement.version,
        criteria=_criteria_out(db, requirement.id),
    )


@router.post(
    "/api/projects/{project_id}/requirements",
    response_model=RequirementOut,
    status_code=201,
)
async def create_requirement(
    body: RequirementIn,
    request: Request,
    project: Project = Depends(get_project),
    db: Session = Depends(get_db),
) -> RequirementOut:
    if not body.criteria:
        raise DomainError("A requirement needs at least one acceptance criterion (TASK-001)", 422)
    requirement = Requirement(
        project_id=project.id,
        title=body.title,
        description=body.description,
        desired_outcome=body.desired_outcome,
        priority=body.priority,
    )
    db.add(requirement)
    db.flush()
    for criterion in body.criteria:
        db.add(
            AcceptanceCriterion(
                requirement_id=requirement.id,
                description=criterion.description,
                kind=criterion.kind,
                mandatory=criterion.mandatory,
            )
        )
    db.commit()
    await record_event(
        request.app.state.session_factory,
        "REQUIREMENT_CREATED",
        project_id=project.id,
        payload={"requirement_id": str(requirement.id), "title": requirement.title[:200]},
    )
    return requirement_out(db, requirement)


@router.get("/api/projects/{project_id}/requirements", response_model=list[RequirementOut])
def list_requirements(
    project: Project = Depends(get_project), db: Session = Depends(get_db)
) -> list[RequirementOut]:
    rows = db.scalars(
        select(Requirement)
        .where(Requirement.project_id == project.id)
        .order_by(Requirement.created_at)
    ).all()
    return [requirement_out(db, r) for r in rows]


@router.get("/api/requirements/{requirement_id}", response_model=RequirementOut)
def get_requirement(requirement_id: uuid.UUID, db: Session = Depends(get_db)) -> RequirementOut:
    return requirement_out(db, _requirement_or_404(requirement_id, db))
