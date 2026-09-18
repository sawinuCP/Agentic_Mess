"""HITL service: approval gates that fail closed (spec §25, SEC-004).

Lifecycle: ``pending`` → ``approved`` | ``rejected`` | ``modified`` (human),
``pending`` → ``timeout`` (fail-closed wait expiry — the ``expired`` state of
the wave-2 taxonomy), ``pending`` → ``cancelled`` (operator withdrawal).
Terminal states are never re-decided; waiters treat every non-``approved``
terminal state as rejection.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.db.models import HitlRequest

TERMINAL_STATUSES = ("approved", "rejected", "modified", "timeout", "cancelled")


def _request_or_404(request_id: uuid.UUID, db: Session) -> HitlRequest:
    request = db.get(HitlRequest, request_id)
    if request is None:
        raise DomainError("HITL request not found", 404)
    return request


def request_out(request: HitlRequest) -> dict[str, Any]:
    return {
        "id": str(request.id),
        "project_id": str(request.project_id) if request.project_id else None,
        "task_id": str(request.task_id) if request.task_id else None,
        "kind": request.kind,
        "question": request.question,
        "choices": [str(c) for c in (request.choices or [])],
        "risk": request.risk,
        "status": request.status,
        "decided_by": request.decided_by,
        "decision_note": request.decision_note,
        "created_at": request.created_at.isoformat(),
        "decided_at": request.decided_at.isoformat() if request.decided_at else None,
    }


def create_request(
    db: Session,
    *,
    project_id: uuid.UUID | None,
    task_id: uuid.UUID | None = None,
    kind: str = "approve_command",
    question: str,
    choices: list[str] | None = None,
    risk: str = "medium",
) -> HitlRequest:
    request = HitlRequest(
        project_id=project_id,
        task_id=task_id,
        kind=kind,
        question=question,
        choices=choices or ["approve", "reject"],
        risk=risk,
    )
    db.add(request)
    db.commit()
    return request


def list_requests(
    db: Session, project_id: uuid.UUID | None = None, status: str | None = None
) -> list[HitlRequest]:
    query = select(HitlRequest).order_by(HitlRequest.created_at.desc())
    if project_id:
        query = query.where(HitlRequest.project_id == project_id)
    if status:
        query = query.where(HitlRequest.status == status)
    return list(db.scalars(query.limit(200)).all())


def get_request(db: Session, request_id: uuid.UUID) -> HitlRequest:
    return _request_or_404(request_id, db)


def decide_request(
    db: Session, request_id: uuid.UUID, decision: str, decided_by: str, note: str | None
) -> HitlRequest:
    """Apply a human decision. Idempotent-safe: only pending requests are decidable."""
    request = _request_or_404(request_id, db)
    if decision not in ("approved", "rejected", "modified"):
        raise DomainError("decision must be approved | rejected | modified", 422)
    if request.status in TERMINAL_STATUSES:
        raise DomainError(f"Request already decided: {request.status}", 409)
    request.status = decision
    request.decided_by = decided_by
    request.decision_note = note
    request.decided_at = datetime.now(UTC)
    db.commit()
    return request


def cancel_request(db: Session, request_id: uuid.UUID, decided_by: str) -> HitlRequest:
    """Withdraw a pending request (operator cancel). A cancelled gate behaves
    like a rejection for every waiter — fail-closed. Terminal requests (incl.
    timed-out) cannot be cancelled."""
    request = _request_or_404(request_id, db)
    if request.status in TERMINAL_STATUSES:
        raise DomainError(f"Request already decided: {request.status}", 409)
    request.status = "cancelled"
    request.decided_by = decided_by
    request.decision_note = "withdrawn by operator"
    request.decided_at = datetime.now(UTC)
    db.commit()
    return request


def wait_decision(
    db: Session, request_id: uuid.UUID, timeout_seconds: float, poll_seconds: float
) -> tuple[HitlRequest, bool]:
    """Blocking poll used by the HITL gate activity. Returns (request, approved?).

    Fails closed: on timeout the request is marked ``timeout`` and treated as rejected.
    """
    deadline = datetime.now(UTC).timestamp() + timeout_seconds
    while True:
        request = _request_or_404(request_id, db)
        if request.status in TERMINAL_STATUSES:
            return request, request.status == "approved"
        if datetime.now(UTC).timestamp() >= deadline:
            request.status = "timeout"
            request.decided_at = datetime.now(UTC)
            request.decision_note = "fail-closed: HITL timeout"
            db.commit()
            return request, False
        db.expire(request)  # re-read fresh state on the next poll
        time.sleep(poll_seconds)
