"""Recovery executor activities (Wave 2): the durable half of recovery.

The task workflow (``app.durable.workflows``) is the authoritative coordinator:
it computes a deterministic :func:`recovery_decision` (pure policy core in
``app.services.orchestration.recovery``) and executes the decided action
through the activities below. Every activity is idempotent — Temporal may retry
an activity after a worker crash, so durable effects are keyed by an
``idempotency_key`` stored on the event payload and checked before creating
anything (no duplicate agents, HITL requests, child tasks or events).

Only decision, concise rationale, evidence references and execution results are
persisted — never hidden chain-of-thought, never secrets.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from temporalio import activity

from app.core.observability import trace_activity
from app.db.models import Agent, AgentSession, Event, Task
from app.durable.activities._context import current_settings, load_task_row, refs


def _event_exists(session: Session, event_type: str, idempotency_key: str) -> Event | None:
    """Find a prior event carrying the same idempotency key (dedup on retry)."""
    return session.scalars(
        select(Event)
        .where(
            Event.event_type == event_type,
            Event.payload["idempotency_key"].astext == idempotency_key,
        )
        .limit(1)
    ).first()


def _task_event(session: Session, task: Task, event_type: str, payload: dict[str, Any]) -> None:
    from app.services.core.events import emit_event

    emit_event(
        session,
        event_type,
        source="temporal",
        project_id=task.project_id,
        task_id=task.id,
        payload=payload,
    )


@activity.defn
@trace_activity
async def recovery_budget_activity(input: dict[str, Any]) -> dict[str, Any]:
    """Check the remaining task token budget before an expensive recovery action.

    Reuses the model cost ledger (spec §32). Returns ``within_budget`` so the
    workflow can route insufficient-budget decisions through the durable HITL
    gate instead of executing them (prompt §9: recovery never bypasses cost
    control).
    """
    from app.services.intelligence import costs as cost_service  # noqa: PLC0415

    factory, _store = refs()

    def _check() -> dict[str, Any]:
        settings = current_settings()
        budget = int(getattr(settings, "model_budget_tokens_per_task", 0) or 0)
        if budget <= 0:
            return {"within_budget": True, "tokens_used": 0, "budget": 0}
        with factory() as session:
            used = cost_service.tokens_for_task(session, uuid.UUID(input["task_id"]))
            return {"within_budget": used < budget, "tokens_used": int(used), "budget": budget}

    return await asyncio.to_thread(_check)


@activity.defn
@trace_activity
async def spawn_child_task_activity(input: dict[str, Any]) -> dict[str, Any]:
    """Create a durable child task carrying structured failure evidence.

    Serves SPAWN_DEBUGGER and create_integration_task (merge conflicts): the
    child inherits project/requirement linkage and a bounded retry policy, and
    receives what a human debugger would ask for — failure class, concise
    detail, attempt id and evidence artifact ids. Idempotent per
    ``idempotency_key``: a retried activity returns the previously created task.
    """
    factory, _store = refs()
    idempotency_key = str(input["idempotency_key"])

    def _spawn() -> dict[str, Any]:
        with factory() as session:
            existing = _event_exists(session, "DEBUGGER_SPAWNED", idempotency_key)
            if existing is not None and existing.payload.get("child_task_id"):
                return {"child_task_id": str(existing.payload["child_task_id"]), "created": False}
            parent = load_task_row(session, uuid.UUID(input["task_id"]))
            child = Task(
                project_id=parent.project_id,
                requirement_id=parent.requirement_id,
                parent_task_id=parent.id,
                title=str(input.get("title", f"Debug: {parent.title}"))[:300],
                request=str(input.get("request", parent.request)),
                allowed_tools=list(parent.allowed_tools or []),
                payload={
                    **(parent.payload or {}),
                    "kind": input.get("child_kind", "debug"),
                    "failure_class": input.get("failure_class"),
                    "failure_detail": input.get("failure_detail"),
                    "source_attempt_id": input.get("attempt_id"),
                    "evidence_artifact_ids": input.get("evidence_artifact_ids", []),
                },
                retry_policy={"max_attempts": 2, "backoff_seconds": 1},
                priority=2,  # debug/integration follow-ups jump the queue
            )
            session.add(child)
            session.flush()
            _task_event(
                session,
                parent,
                "DEBUGGER_SPAWNED",
                {
                    "idempotency_key": idempotency_key,
                    "child_task_id": str(child.id),
                    "child_kind": input.get("child_kind", "debug"),
                    "failure_class": input.get("failure_class"),
                    "failure_detail": (input.get("failure_detail") or "")[:300],
                    "evidence_artifact_ids": input.get("evidence_artifact_ids", []),
                },
            )
            session.commit()
            return {"child_task_id": str(child.id), "created": True}

    return await asyncio.to_thread(_spawn)


@activity.defn
@trace_activity
async def replan_task_activity(input: dict[str, Any]) -> dict[str, Any]:
    """Create the durable REPLAN follow-up (REC-003, prompt §7 REPLAN_TASK).

    Called when the retry ladder is exhausted: a new child task carries the
    failure evidence and the request to re-plan; the original task then
    transitions to its terminal state (see :func:`terminal_failure_activity`).
    Idempotent per key.
    """
    factory, _store = refs()
    idempotency_key = str(input["idempotency_key"])

    def _replan() -> dict[str, Any]:
        with factory() as session:
            existing = _event_exists(session, "TASK_REPLANNED", idempotency_key)
            if existing is not None and existing.payload.get("replan_task_id"):
                return {"replan_task_id": str(existing.payload["replan_task_id"]), "created": False}
            parent = load_task_row(session, uuid.UUID(input["task_id"]))
            child = Task(
                project_id=parent.project_id,
                requirement_id=parent.requirement_id,
                plan_id=parent.plan_id,
                parent_task_id=parent.id,
                title=f"Replan: {parent.title}"[:300],
                request=(
                    "Recover from repeated failures and re-plan the remaining work. "
                    f"Failure class: {input.get('failure_class')}. "
                    f"Detail: {(input.get('failure_detail') or '')[:500]}"
                ),
                allowed_tools=list(parent.allowed_tools or []),
                payload={
                    **(parent.payload or {}),
                    "kind": "replan",
                    "failed_task_id": str(parent.id),
                    "failure_class": input.get("failure_class"),
                    "failure_detail": input.get("failure_detail"),
                    "evidence_artifact_ids": input.get("evidence_artifact_ids", []),
                },
                retry_policy={"max_attempts": 2, "backoff_seconds": 1},
                priority=2,
            )
            session.add(child)
            session.flush()
            _task_event(
                session,
                parent,
                "TASK_REPLAN_STARTED",
                {"idempotency_key": idempotency_key, "failure_class": input.get("failure_class")},
            )
            _task_event(
                session,
                parent,
                "TASK_REPLANNED",
                {"idempotency_key": idempotency_key, "replan_task_id": str(child.id)},
            )
            session.commit()
            return {"replan_task_id": str(child.id), "created": True}

    return await asyncio.to_thread(_replan)


@activity.defn
@trace_activity
async def terminal_failure_activity(input: dict[str, Any]) -> dict[str, Any]:
    """Record the durable terminal failure with evidence (prompt §7 FAIL_TERMINALLY).

    Writes the task's terminal summary (failure classification, recovery trail,
    evidence references, recommended next action) and emits
    TASK_TERMINALLY_FAILED. Idempotent: a second invocation with the same key
    finds the existing event and returns without duplicating.
    """
    factory, _store = refs()
    idempotency_key = str(input["idempotency_key"])

    def _terminal() -> dict[str, Any]:
        with factory() as session:
            existing = _event_exists(session, "TASK_TERMINALLY_FAILED", idempotency_key)
            if existing is not None:
                return {"recorded": False}
            task = load_task_row(session, uuid.UUID(input["task_id"]))
            payload = task.payload or {}
            recovery_trail = list(payload.get("recovery_trail", []))
            recovery_trail.append(
                {
                    "recovery_id": input.get("recovery_id"),
                    "action": input.get("action"),
                    "failure_class": input.get("failure_class"),
                }
            )
            task.payload = {
                **payload,
                "terminal": {
                    "failure_class": input.get("failure_class"),
                    "failure_detail": (input.get("failure_detail") or "")[:500],
                    "recovery_trail": recovery_trail,
                    "evidence_artifact_ids": input.get("evidence_artifact_ids", []),
                    "recommended_action": input.get("recommended_action", ""),
                },
            }
            _task_event(
                session,
                task,
                "TASK_TERMINALLY_FAILED",
                {
                    "idempotency_key": idempotency_key,
                    "failure_class": input.get("failure_class"),
                    "failure_detail": (input.get("failure_detail") or "")[:500],
                    "recommended_action": input.get("recommended_action", ""),
                    "recovery_id": input.get("recovery_id"),
                },
            )
            session.commit()
            return {"recorded": True}

    return await asyncio.to_thread(_terminal)


@activity.defn
@trace_activity
async def end_agent_session_activity(input: dict[str, Any]) -> dict[str, Any]:
    """Stop/drain the failed agent's session (prompt §11 replacement safety).

    The execution slot was already released by the execution activity's
    ``finally``; this closes the agent session row and moves the agent to a
    terminal lifecycle state so no stale session keeps running. Idempotent.
    """
    factory, _store = refs()

    def _end() -> dict[str, Any]:
        with factory() as session:
            session_id = str(input.get("session_id") or "")
            agent_id = str(input.get("agent_id") or "")
            if not session_id and not agent_id:
                return {"ended": False}  # nothing to drain (defensive; workflow passes real ids)
            if session_id:
                row = session.get(AgentSession, uuid.UUID(session_id))
                if row is not None and row.status == "running":
                    row.status = "ended"
                    row.finished_at = datetime.now(UTC)
            if agent_id:
                agent = session.get(Agent, uuid.UUID(agent_id))
                if agent is not None and agent.state not in ("failed", "cancelled"):
                    agent.state = "failed"
            session.commit()
            return {"ended": True}

    return await asyncio.to_thread(_end)


@activity.defn
@trace_activity
async def task_dependents_activity(input: dict[str, Any]) -> dict[str, Any]:
    """Ids of tasks that depend on the given task (for dependency-resume signals)."""
    factory, _store = refs()

    def _dependents() -> dict[str, Any]:
        with factory() as session:
            from app.db.models import TaskDependency  # noqa: PLC0415

            rows = session.scalars(
                select(TaskDependency.task_id).where(
                    TaskDependency.depends_on_task_id == uuid.UUID(input["task_id"])
                )
            ).all()
            return {"dependent_task_ids": [str(row) for row in rows]}

    return await asyncio.to_thread(_dependents)


#: Task statuses after which nothing will ever signal again.
_TERMINAL_TASK_STATUSES = frozenset({"completed", "failed", "cancelled"})


@activity.defn
@trace_activity
async def dependency_status_activity(input: dict[str, Any]) -> dict[str, Any]:
    """Unfinished blocking dependencies of a task (durable pre-wait check).

    A dependency that already completed before the waiter parks would never
    signal again — without this check the waiter would hang until its deadline.
    Read-only: safe to call on every wait entry.
    """
    factory, _store = refs()

    def _status() -> dict[str, Any]:
        with factory() as session:
            from app.db.models import TaskDependency  # noqa: PLC0415

            dep_ids = session.scalars(
                select(TaskDependency.depends_on_task_id).where(
                    TaskDependency.task_id == uuid.UUID(input["task_id"])
                )
            ).all()
            unfinished = [
                str(row.id)
                for row in session.scalars(select(Task).where(Task.id.in_(dep_ids))).all()
                if row.status not in _TERMINAL_TASK_STATUSES
            ]
            return {"unfinished_dependency_ids": unfinished}

    return await asyncio.to_thread(_status)


def _project_root(session: Session, task_id: uuid.UUID) -> tuple[Task, str | None]:
    """Task plus its project root (None when the project is gone)."""
    from app.db.models import Project  # noqa: PLC0415

    task = load_task_row(session, task_id)
    project = session.get(Project, task.project_id) if task.project_id else None
    root = str(project.root_path) if project and project.root_path else None
    return task, root


def _latest_snapshot(session: Session, task_id: uuid.UUID, attempt_id: str) -> Event | None:
    """Newest SNAPSHOT_CREATED event for an attempt (rollback source of truth)."""
    return session.scalars(
        select(Event)
        .where(
            Event.task_id == task_id,
            Event.event_type == "SNAPSHOT_CREATED",
            Event.payload["attempt_id"].astext == attempt_id,
        )
        .order_by(Event.occurred_at.desc(), Event.id.desc())
        .limit(1)
    ).first()


@activity.defn
@trace_activity
async def snapshot_attempt_activity(input: dict[str, Any]) -> dict[str, Any]:
    """Record the pre-attempt HEAD sha of the project repo (rollback anchor).

    Git repos only — anything else returns ``snapshotted: False`` and the
    rollback step later becomes a graceful no-op. Idempotent per key: a replay
    returns the originally recorded sha (the anchor must never move).
    """
    from app.gitops.client import GitClient, GitError  # noqa: PLC0415

    factory, _store = refs()
    task_id = uuid.UUID(input["task_id"])
    attempt_id = str(input["attempt_id"])
    idempotency_key = str(input["idempotency_key"])

    def _snapshot() -> dict[str, Any]:
        with factory() as session:
            task, root = _project_root(session, task_id)
            existing = _event_exists(session, "SNAPSHOT_CREATED", idempotency_key)
            if existing is not None and existing.payload.get("sha"):
                return {
                    "snapshotted": True,
                    "sha": str(existing.payload["sha"]),
                    "replayed": True,
                }
            if not root:
                return {"snapshotted": False, "reason": "no_project_root"}
            try:
                sha = asyncio.run(GitClient(Path(root)).head_sha())
            except GitError as exc:
                return {"snapshotted": False, "reason": exc.kind}
            _task_event(
                session,
                task,
                "SNAPSHOT_CREATED",
                {
                    "idempotency_key": idempotency_key,
                    "attempt_id": attempt_id,
                    "sha": sha,
                    "root": root,
                },
            )
            session.commit()
            return {"snapshotted": True, "sha": sha, "replayed": False}

    return await asyncio.to_thread(_snapshot)


@activity.defn
@trace_activity
async def rollback_attempt_activity(input: dict[str, Any]) -> dict[str, Any]:
    """Restore the project worktree to the pre-attempt snapshot (ROLLBACK).

    Evidence-preserving by construction: the pre-reset HEAD is kept on a
    ``recovery/<task>-<attempt>`` branch and referenced from ROLLBACK_COMPLETED
    — history and evidence are never deleted, only the working state is
    restored. No snapshot (or no git repo) is a graceful no-op, never an error.
    Idempotent per key: a replay after a crash between reset and event-commit
    reuses the evidence branch and converges on the same state.
    """
    from app.gitops.client import GitClient, GitError  # noqa: PLC0415

    factory, _store = refs()
    task_id = uuid.UUID(input["task_id"])
    attempt_id = str(input["attempt_id"])
    idempotency_key = str(input["idempotency_key"])

    def _rollback() -> dict[str, Any]:
        with factory() as session:
            task, root = _project_root(session, task_id)
            existing = _event_exists(session, "ROLLBACK_COMPLETED", idempotency_key)
            if existing is not None:
                return {
                    "rolled_back": True,
                    "replayed": True,
                    "to_sha": existing.payload.get("to_sha"),
                    "evidence_branch": existing.payload.get("evidence_branch"),
                }
            snapshot = _latest_snapshot(session, task_id, attempt_id)
            if snapshot is None or not snapshot.payload.get("sha") or not root:
                return {"rolled_back": False, "reason": "no_snapshot"}
            to_sha = str(snapshot.payload["sha"])
            branch = f"recovery/{task_id.hex[:8]}-{attempt_id[:8]}"
            client = GitClient(Path(root))
            try:
                current = asyncio.run(client.head_sha())
                if current == to_sha and not asyncio.run(client.status()).entries:
                    return {"rolled_back": True, "noop": True, "to_sha": to_sha}
                try:
                    asyncio.run(client.create_branch_at(branch, current))
                except GitError as exc:
                    if "already exists" not in str(exc.message).lower():
                        raise
                    # Retry after a crash between branch-create and reset: the
                    # branch is ours (same deterministic name) — converge.
                asyncio.run(client.reset_hard(to_sha))
            except GitError as exc:
                return {"rolled_back": False, "reason": exc.kind}
            _task_event(
                session,
                task,
                "ROLLBACK_COMPLETED",
                {
                    "idempotency_key": idempotency_key,
                    "attempt_id": attempt_id,
                    "from_sha": current,
                    "to_sha": to_sha,
                    "evidence_branch": branch,
                },
            )
            session.commit()
            return {"rolled_back": True, "to_sha": to_sha, "evidence_branch": branch}

    return await asyncio.to_thread(_rollback)
