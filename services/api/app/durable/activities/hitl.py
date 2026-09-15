"""HITL approval gate (SEC-004, spec §25): durable request + fail-closed wait.

The gate creates a durable ``hitl_requests`` row, emits HITL_REQUESTED, then polls
for the human decision. Timeout is treated as rejection — the gated action never
executes unapproved.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from app.db.models import Event
from app.durable.activities._context import refs


async def hitl_gate(
    *,
    project_id: str | None,
    task_id: uuid.UUID,
    command: list[str],
    timeout_seconds: float,
    poll_seconds: float,
) -> dict[str, Any]:
    """Create a durable HITL request and wait (fail-closed) for the decision."""
    from app.services import hitl as hitl_service  # noqa: PLC0415 — avoids an import cycle

    factory, _store = refs()

    def _create() -> dict[str, Any]:
        with factory() as session:
            request = hitl_service.create_request(
                session,
                project_id=uuid.UUID(project_id) if project_id else None,
                task_id=task_id,
                kind="approve_command",
                question="Approve execution of a policy-gated command?",
                choices=["approve", "reject"],
                risk="high",
            )
            session.add(
                Event(
                    event_type="HITL_REQUESTED",
                    source="temporal",
                    project_id=uuid.UUID(project_id) if project_id else None,
                    task_id=task_id,
                    payload={
                        "request_id": str(request.id),
                        "command": " ".join(command),
                    },
                )
            )
            session.commit()
            return {"request_id": str(request.id), "command": " ".join(command)}

    created = await asyncio.to_thread(_create)
    request_id = uuid.UUID(created["request_id"])

    def _wait() -> tuple[Any, bool]:
        with factory() as session:
            return hitl_service.wait_decision(session, request_id, timeout_seconds, poll_seconds)

    request, approved = await asyncio.to_thread(_wait)

    def _responded() -> None:
        with factory() as session:
            session.add(
                Event(
                    event_type="HITL_RESPONDED",
                    source="temporal",
                    project_id=uuid.UUID(project_id) if project_id else None,
                    task_id=task_id,
                    payload={
                        "request_id": str(request_id),
                        "status": request.status,
                        "approved": approved,
                    },
                )
            )
            session.commit()

    await asyncio.to_thread(_responded)
    return {"request_id": str(request_id), "status": request.status, "approved": approved}
