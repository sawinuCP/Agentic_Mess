"""Model cost ledger (spec §32): per-call token accounting + budget gates.

Every model call is recorded as a durable ``model_invocations`` row (task, agent,
role, provider, tokens, latency). Budgets are enforced at the call site before
each model call: per-task tokens (the original gate), plus per-agent tokens,
per-task invocations, and per-agent invocations. A per-task gate also bounds a
single execution run's spend, because ledger rows are task-scoped across
workflow runs and attempts. Any exhausted budget fails closed with
``BUDGET_EXCEEDED`` (a non-retryable stop). All budgets are 0 = unlimited.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import ModelInvocation


def record_invocation(
    db: Session,
    *,
    project_id: uuid.UUID | None,
    task_id: uuid.UUID | None,
    agent_id: uuid.UUID | None,
    role: str,
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    latency_ms: int | None = None,
    cost_usd: float | None = None,
) -> ModelInvocation:
    total = int(prompt_tokens) + int(completion_tokens)
    row = ModelInvocation(
        project_id=project_id,
        task_id=task_id,
        agent_id=agent_id,
        role=role,
        provider=provider,
        model=model,
        prompt_tokens=int(prompt_tokens),
        completion_tokens=int(completion_tokens),
        total_tokens=total,
        latency_ms=latency_ms,
        cost_usd=cost_usd,
    )
    db.add(row)
    db.commit()
    return row


def tokens_for_task(db: Session, task_id: uuid.UUID) -> int:
    """Cumulative model tokens charged to a task so far."""
    return int(
        db.scalar(
            select(func.coalesce(func.sum(ModelInvocation.total_tokens), 0)).where(
                ModelInvocation.task_id == task_id
            )
        )
        or 0
    )


def tokens_for_agent(db: Session, agent_id: uuid.UUID) -> int:
    """Cumulative model tokens charged to an agent across all its tasks."""
    return int(
        db.scalar(
            select(func.coalesce(func.sum(ModelInvocation.total_tokens), 0)).where(
                ModelInvocation.agent_id == agent_id
            )
        )
        or 0
    )


def invocations_for_task(db: Session, task_id: uuid.UUID) -> int:
    """Model call count charged to a task (bounds tool-call volume per task)."""
    return int(
        db.scalar(
            select(func.count())
            .select_from(ModelInvocation)
            .where(ModelInvocation.task_id == task_id)
        )
        or 0
    )


def invocations_for_agent(db: Session, agent_id: uuid.UUID) -> int:
    """Model call count charged to an agent across all its tasks."""
    return int(
        db.scalar(
            select(func.count())
            .select_from(ModelInvocation)
            .where(ModelInvocation.agent_id == agent_id)
        )
        or 0
    )


def summary(db: Session, project_id: uuid.UUID, task_id: uuid.UUID | None = None) -> dict[str, Any]:
    """Aggregate the ledger: totals plus per-model and per-role breakdowns."""
    base = select(ModelInvocation).where(ModelInvocation.project_id == project_id)
    if task_id is not None:
        base = base.where(ModelInvocation.task_id == task_id)
    rows = db.scalars(base.order_by(ModelInvocation.created_at.desc()).limit(1000)).all()

    by_model: dict[str, int] = {}
    by_role: dict[str, int] = {}
    total_tokens = 0
    for row in rows:
        total_tokens += row.total_tokens
        key_model = f"{row.provider}:{row.model}"
        by_model[key_model] = by_model.get(key_model, 0) + row.total_tokens
        by_role[row.role] = by_role.get(row.role, 0) + row.total_tokens

    return {
        "invocations": len(rows),
        "total_tokens": total_tokens,
        "by_model": dict(sorted(by_model.items(), key=lambda kv: kv[1], reverse=True)),
        "by_role": dict(sorted(by_role.items(), key=lambda kv: kv[1], reverse=True)),
    }
