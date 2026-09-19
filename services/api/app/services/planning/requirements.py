"""Requirement and acceptance-criteria service (FR-005, TASK-001, FR-013)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.db.models import AcceptanceCriterion, Requirement
from app.schemas.planning.requirements import CriterionOut, RequirementIn, RequirementOut


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
    return [_criterion_out(c) for c in rows]


def _criterion_out(c: AcceptanceCriterion) -> CriterionOut:
    return CriterionOut(
        id=c.id, description=c.description, kind=c.kind, mandatory=c.mandatory, status=c.status
    )


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


def create_requirement(db: Session, project_id: uuid.UUID, body: RequirementIn) -> Requirement:
    """Persist a requirement with its acceptance criteria (TASK-001: never vague)."""
    if not body.criteria:
        raise DomainError("A requirement needs at least one acceptance criterion (TASK-001)", 422)
    requirement = Requirement(
        project_id=project_id,
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
    return requirement


def list_requirements(
    db: Session, project_id: uuid.UUID, limit: int = 100, offset: int = 0
) -> list[RequirementOut]:
    """One page of requirements with criteria batched in two queries total
    (never N+1): requirements page, then all criteria for the page's ids."""
    from collections import defaultdict

    rows = db.scalars(
        select(Requirement)
        .where(Requirement.project_id == project_id)
        .order_by(Requirement.created_at, Requirement.id)
        .limit(max(1, limit))
        .offset(max(0, offset))
    ).all()
    if not rows:
        return []
    page_ids = [r.id for r in rows]  # bounded by the page size by construction
    criteria: dict[uuid.UUID, list[CriterionOut]] = defaultdict(list)
    for criterion in db.scalars(
        select(AcceptanceCriterion)
        .where(AcceptanceCriterion.requirement_id.in_(page_ids))
        .order_by(AcceptanceCriterion.created_at)
    ).all():
        criteria[criterion.requirement_id].append(_criterion_out(criterion))
    return [
        RequirementOut(
            id=r.id,
            project_id=r.project_id,
            title=r.title,
            description=r.description,
            desired_outcome=r.desired_outcome,
            priority=r.priority,
            status=r.status,
            version=r.version,
            criteria=criteria[r.id],
        )
        for r in rows
    ]


def get_requirement(db: Session, requirement_id: uuid.UUID) -> RequirementOut:
    return requirement_out(db, _requirement_or_404(requirement_id, db))
