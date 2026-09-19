"""Durable execution metrics for evaluation (§12/§16/§42).

Pure read-only extractors over durable rows — no model calls, no judgments.
They answer "what happened" (counts, rates, correlations) for reports and the
CLI; verdicts stay in the scorecard and suite classifiers.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Agent, Event, Message, ModelInvocation, Task, TaskAttempt
from app.services.intelligence import costs as cost_service


def _event_types(db: Session, task_id: uuid.UUID) -> dict[str, int]:
    rows = db.execute(
        select(Event.event_type, func.count())
        .where(Event.task_id == task_id)
        .group_by(Event.event_type)
    ).all()
    return {event_type: int(count) for event_type, count in rows}


def execution_metrics(db: Session, task_id: uuid.UUID) -> dict[str, Any]:
    """Orchestration metrics for one task from durable records only."""
    task = db.get(Task, task_id)
    if task is None:
        raise ValueError(f"Task not found: {task_id}")
    attempts = db.scalars(select(TaskAttempt).where(TaskAttempt.task_id == task_id)).all()
    agent_ids = {a.agent_id for a in attempts if a.agent_id}
    agents = db.scalars(select(Agent).where(Agent.id.in_(agent_ids))).all() if agent_ids else []
    events = _event_types(db, task_id)
    recoveries = events.get("RECOVERY_SELECTED", 0)
    tool_started = events.get("TOOL_STARTED", 0)
    tool_ok = events.get("TOOL_COMPLETED", 0)
    tool_failed = events.get("TOOL_FAILED", 0)
    ledger = cost_service.summary(db, task.project_id, task_id) if task.project_id else {}
    model_cost = db.scalar(
        select(func.coalesce(func.sum(ModelInvocation.cost_usd), 0)).where(
            ModelInvocation.task_id == task_id
        )
    )
    retries = max(0, len(attempts) - 1)
    completed = task.status == "completed"
    return {
        "task_id": str(task_id),
        "task_status": task.status,
        "task_count": 1,
        "attempt_count": len(attempts),
        "agent_count": len(agents),
        "retry_count": retries,
        "retry_rate": (retries / len(attempts)) if attempts else 0.0,
        "recovery_count": recoveries,
        "recovery_success": bool(completed and recoveries),
        "replan_count": events.get("TASK_REPLANNED", 0),
        "agent_replacement_count": events.get("AGENT_REPLACED", 0),
        "debugger_spawn_count": events.get("DEBUGGER_SPAWNED", 0),
        "tool_call_count": tool_started,
        "tool_success_rate": (tool_ok / tool_started) if tool_started else None,
        "tool_failed_count": tool_failed,
        "model_call_count": int(ledger.get("invocations", 0)) if ledger else 0,
        "input_tokens": None,  # ledger tracks totals; split unavailable — not fabricated
        "total_tokens": int(ledger.get("total_tokens", 0)) if ledger else 0,
        "estimated_cost_usd": float(model_cost or 0),
        "hitl_request_count": events.get("HITL_REQUESTED", 0)
        + events.get("HITL_RECOVERY_REQUESTED", 0),
        "terminal_failure": task.status == "failed",
    }


def communication_health(db: Session, conversation_id: uuid.UUID) -> dict[str, Any]:
    """Structural health of one conversation (§16): orphans, duplicates,
    unanswered questions, undelivered — all from durable message rows."""
    messages = db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
    ).all()
    ids = {m.id for m in messages}
    by_type: dict[str, int] = {}
    for message in messages:
        by_type[message.type] = by_type.get(message.type, 0) + 1
    orphans = [str(m.id) for m in messages if m.reply_to is not None and m.reply_to not in ids]
    seen: dict[tuple[str | None, str | None, str], int] = {}
    for message in messages:
        key = (
            str(message.sender_agent_id),
            message.correlation_id,
            message.type,
        )
        seen[key] = seen.get(key, 0) + 1
    duplicates = sum(count - 1 for count in seen.values() if count > 1)
    correlations_with_response = {
        m.correlation_id for m in messages if m.type == "response" and m.correlation_id
    }
    unanswered = [
        str(m.id)
        for m in messages
        if m.type == "question"
        and m.correlation_id
        and m.correlation_id not in correlations_with_response
    ]
    undelivered = [str(m.id) for m in messages if m.delivered_at is None]
    return {
        "conversation_id": str(conversation_id),
        "message_count": len(messages),
        "by_type": by_type,
        "orphan_reply_count": len(orphans),
        "orphan_reply_ids": orphans,
        "duplicate_count": duplicates,
        "unanswered_question_count": len(unanswered),
        "unanswered_question_ids": unanswered,
        "undelivered_count": len(undelivered),
        "healthy": not orphans and not duplicates and not unanswered,
    }
