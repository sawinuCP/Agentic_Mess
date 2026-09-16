"""Review/debate/adjudication endpoints (Phase 8, FR-017, spec §24)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.errors import DomainError
from app.db.models import Decision, Review, Task
from app.schemas.quality import ReviewRequestIn
from app.services.quality import review as review_service

router = APIRouter(tags=["reviews"])


class ReviewOut(BaseModel):
    id: str
    decision_id: str | None
    task_id: str | None
    reviewer_role: str
    verdict: str
    summary: str | None
    rounds: int
    model: str | None


def _review_out(review: Review) -> ReviewOut:
    return ReviewOut(
        id=str(review.id),
        decision_id=str(review.decision_id) if review.decision_id else None,
        task_id=str(review.task_id) if review.task_id else None,
        reviewer_role=review.reviewer_role,
        verdict=review.verdict,
        summary=review.summary,
        rounds=review.rounds,
        model=review.model,
    )


@router.post("/api/tasks/{task_id}/reviews", status_code=201)
async def run_task_review(
    task_id: uuid.UUID, body: ReviewRequestIn, request: Request
) -> dict[str, Any]:
    """Run the bounded review pipeline (independent reviewers -> critic -> evidence
    verifier -> adjudicator) and persist the decision durably (FR-017)."""
    with request.app.state.session_factory() as session:
        task = session.get(Task, task_id)
        if task is None:
            raise DomainError("Task not found", 404)
        project_id = task.project_id
        outcome = await review_service.run_review(
            session,
            request.app.state.session_factory,
            proposal=body.proposal,
            proposal_title=body.title,
            evidence=body.evidence,
            task_id=task_id,
            project_id=project_id,
            reviewer_roles=body.reviewer_roles or None,
            max_rounds=body.max_rounds,
        )
    return {
        "decision_id": outcome.decision_id,
        "verdict": outcome.verdict,
        "rationale": outcome.rationale,
        "reviews": outcome.reviews,
        "findings": outcome.findings,
    }


@router.get("/api/tasks/{task_id}/reviews")
async def list_task_reviews(task_id: uuid.UUID, db: Session = Depends(get_db)) -> list[ReviewOut]:
    reviews = db.scalars(select(Review).where(Review.task_id == task_id)).all()
    return [_review_out(review) for review in reviews]


@router.get("/api/decisions/{decision_id}")
async def get_decision(decision_id: uuid.UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    decision = db.get(Decision, decision_id)
    if decision is None:
        raise DomainError("Decision not found", 404)
    reviews = db.scalars(select(Review).where(Review.decision_id == decision.id)).all()
    return {
        "id": str(decision.id),
        "task_id": str(decision.task_id) if decision.task_id else None,
        "title": decision.title,
        "rationale": decision.rationale,
        "kind": decision.kind,
        "status": decision.status,
        "made_by": decision.made_by,
        "reviews": [_review_out(review).model_dump() for review in reviews],
    }
