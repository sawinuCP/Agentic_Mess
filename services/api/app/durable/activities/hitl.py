"""HITL approval gate (SEC-004, spec §25): durable request + fail-closed wait.

The gate creates a durable ``hitl_requests`` row, emits HITL_REQUESTED, then polls
for the human decision. Timeout is treated as rejection — the gated action never
executes unapproved.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from temporalio import activity

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
    from app.services.orchestration import (
        hitl as hitl_service,  # noqa: PLC0415 — avoids an import cycle
    )

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


async def hitl_recovery_gate(
    *,
    project_id: str | None,
    task_id: uuid.UUID,
    decision: dict[str, Any],
    failure_detail: str,
    evidence_artifact_ids: list[str],
    timeout_seconds: float,
    poll_seconds: float,
) -> dict[str, Any]:
    """Durable HITL gate for a RECOVERY decision (Wave 2, prompt §13).

    Creates (once — idempotent per recovery id) a durable request that shows the
    human what failed, what the system detected, the proposed recovery action
    and its evidence; then waits fail-closed. Approval continues the recovery;
    rejection or timeout fails the task terminally. No hidden reasoning is
    exposed — only decision, rationale and evidence references.
    """
    from app.services.orchestration import (
        hitl as hitl_service,  # noqa: PLC0415 — avoids an import cycle
    )

    factory, _store = refs()
    recovery_id = str(decision.get("recovery_id", ""))
    idempotency_key = f"hitl-recovery:{recovery_id or task_id}"
    action = str(decision.get("action", ""))

    def _create() -> dict[str, Any]:
        from app.durable.activities.recovery import _event_exists  # noqa: PLC0415

        with factory() as session:
            existing = _event_exists(session, "HITL_RECOVERY_REQUESTED", idempotency_key)
            if existing is not None and existing.payload.get("request_id"):
                return {"request_id": str(existing.payload["request_id"])}
            request = hitl_service.create_request(
                session,
                project_id=uuid.UUID(project_id) if project_id else None,
                task_id=task_id,
                kind="recovery_decision",
                question=(
                    f"Recovery gate — {decision.get('action_reason', action)}. "
                    f"Class: {decision.get('failure_class')}. Detail: {failure_detail[:300]}"
                ),
                choices=["approve", "reject"],
                risk="high",
            )
            session.add(
                Event(
                    event_type="HITL_RECOVERY_REQUESTED",
                    source="temporal",
                    project_id=uuid.UUID(project_id) if project_id else None,
                    task_id=task_id,
                    payload={
                        "idempotency_key": idempotency_key,
                        "request_id": str(request.id),
                        "recovery_id": recovery_id,
                        "action": action,
                        "failure_class": decision.get("failure_class"),
                        "evidence_artifact_ids": evidence_artifact_ids,
                    },
                )
            )
            session.commit()
            return {"request_id": str(request.id)}

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
                    event_type="HITL_RECOVERY_RESPONDED",
                    source="temporal",
                    project_id=uuid.UUID(project_id) if project_id else None,
                    task_id=task_id,
                    payload={
                        "recovery_id": recovery_id,
                        "request_id": str(request_id),
                        "status": request.status,
                        "approved": approved,
                    },
                )
            )
            session.commit()

    await asyncio.to_thread(_responded)
    return {"request_id": str(request_id), "status": request.status, "approved": approved}


@activity.defn
async def hitl_recovery_gate_activity(input: dict[str, Any]) -> dict[str, Any]:
    """Activity wrapper for :func:`hitl_recovery_gate` (worker-registered)."""
    return await hitl_recovery_gate(
        project_id=input.get("project_id"),
        task_id=uuid.UUID(input["task_id"]),
        decision=input.get("decision", {}),
        failure_detail=str(input.get("failure_detail", "")),
        evidence_artifact_ids=list(input.get("evidence_artifact_ids", [])),
        timeout_seconds=float(input.get("timeout_seconds", 300.0)),
        poll_seconds=float(input.get("poll_seconds", 1.0)),
    )
