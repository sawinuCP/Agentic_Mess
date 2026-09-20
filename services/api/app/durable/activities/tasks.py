"""Task-lifecycle activities: durable attempt records and task status (TASK-002/003)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from temporalio import activity

from app.core.observability import trace_activity
from app.db.models import Artifact, Event, Project, Task, TaskAttempt
from app.durable.activities._context import (
    EVIDENCE_MIN_BYTES,
    current_settings,
    load_task_row,
    refs,
)
from app.runtime.runner import run_process


@activity.defn
@trace_activity
async def load_task_activity(task_id: str) -> dict[str, Any]:
    """Load the durable task for orchestration (TASK-002: state lives in the DB)."""
    factory, _store = refs()

    def _load() -> dict[str, Any]:
        with factory() as session:
            task = load_task_row(session, uuid.UUID(task_id))
            settings = current_settings()
            return {
                "id": str(task.id),
                "project_id": str(task.project_id) if task.project_id else None,
                "requirement_id": str(task.requirement_id) if task.requirement_id else None,
                "plan_id": str(task.plan_id) if task.plan_id else None,
                "title": task.title,
                "status": task.status,
                "payload": task.payload or {},
                "retry_policy": task.retry_policy or {},
                "recovery_policy": {
                    "base_backoff": float(
                        getattr(settings, "recovery_backoff_base_seconds", 2.0) or 2.0
                    ),
                    "factor": float(getattr(settings, "recovery_backoff_factor", 2.0) or 2.0),
                    "max_backoff": float(
                        getattr(settings, "recovery_backoff_max_seconds", 60.0) or 60.0
                    ),
                    "jitter_ratio": float(getattr(settings, "recovery_jitter_ratio", 0.25) or 0.0),
                    "hitl_timeout_seconds": float(
                        getattr(settings, "hitl_timeout_seconds", 300.0) or 300.0
                    ),
                    "hitl_poll_seconds": float(getattr(settings, "hitl_poll_seconds", 1.0) or 1.0),
                    "dependency_wait_seconds": float(
                        getattr(settings, "recovery_dependency_wait_seconds", 900.0) or 900.0
                    ),
                },
            }

    return await asyncio.to_thread(_load)


@activity.defn
@trace_activity
async def start_attempt_activity(input: dict[str, Any]) -> dict[str, Any]:
    """Record the start of attempt N (spec §11: Attempt 1 -> Agent-12 -> ...)."""
    factory, _store = refs()

    def _start() -> dict[str, Any]:
        with factory() as session:
            task_id = uuid.UUID(input["task_id"])
            number = session.scalar(select(func.count()).where(TaskAttempt.task_id == task_id)) or 0
            attempt = TaskAttempt(task_id=task_id, attempt_number=int(number) + 1)
            session.add(attempt)
            session.commit()
            return {"id": str(attempt.id), "attempt_number": attempt.attempt_number}

    return await asyncio.to_thread(_start)


@activity.defn
@trace_activity
async def execute_work_activity(input: dict[str, Any]) -> dict[str, Any]:
    """Direct command work unit (Phase-2 path; the agent path is ``agent_execute_activity``).

    ``payload.command`` executes at the project root; raw stdout/stderr are preserved
    as evidence artifacts (TASK-003).
    """
    payload: dict[str, Any] = input.get("payload") or {}
    command = payload.get("command")
    if not command or not isinstance(command, list):
        return {
            "outcome": "failed",
            "failure_class": "TASK_FAILURE",
            "failure_detail": (
                "No executable work on this task: payload.command is missing. Supply a "
                "command payload, or use the agent-driven path."
            ),
            "evidence_artifact_ids": [],
        }

    factory, store = refs()
    project_id = input.get("project_id")

    def _project_root() -> str:
        if not project_id:
            return "."
        with factory() as session:
            project = session.get(Project, uuid.UUID(project_id))
            return project.root_path if project else "."

    cwd = str(payload.get("cwd") or (await asyncio.to_thread(_project_root)) or ".")
    result = await run_process(
        [str(arg) for arg in command],
        cwd,
        timeout_seconds=float(payload.get("timeout_seconds", 300)),
    )

    evidence: list[str] = []

    def _store_evidence() -> None:
        for name, mime, text in (
            ("stdout.log", "text/plain", result.stdout),
            ("stderr.log", "text/plain", result.stderr),
        ):
            if len(text.encode("utf-8")) < EVIDENCE_MIN_BYTES:
                continue
            blob = store.put(text.encode("utf-8"))
            with factory() as session:
                artifact = Artifact(
                    project_id=uuid.UUID(project_id) if project_id else None,
                    name=f"attempt-{input['attempt_id'][:8]}-{name}",
                    kind="raw_output",
                    mime=mime,
                    size=blob.size,
                    sha256=blob.sha256,
                    storage_path=blob.storage_path,
                )
                session.add(artifact)
                session.commit()
                evidence.append(str(artifact.id))

    await asyncio.to_thread(_store_evidence)

    if result.timed_out:
        outcome, failure_class, detail = "timeout", "TIMEOUT", "Work exceeded its time budget"
    elif result.exit_code == 0:
        outcome, failure_class, detail = "success", None, None
    else:
        outcome = "failed"
        failure_class = "TOOL_FAILURE" if payload.get("kind") == "tool" else "TASK_FAILURE"
        detail = f"exit_code={result.exit_code}; see evidence artifacts"
    return {
        "outcome": outcome,
        "failure_class": failure_class,
        "failure_detail": detail,
        "evidence_artifact_ids": evidence,
        "exit_code": result.exit_code,
        "duration_ms": result.duration_ms,
    }


@activity.defn
@trace_activity
async def finish_attempt_activity(input: dict[str, Any]) -> None:
    factory, _store = refs()

    def _finish() -> None:
        with factory() as session:
            attempt = session.get(TaskAttempt, uuid.UUID(input["attempt_id"]))
            if attempt is None:
                raise RuntimeError(f"Attempt not found: {input['attempt_id']}")
            attempt.outcome = input["outcome"]
            attempt.failure_class = input.get("failure_class")
            attempt.failure_detail = input.get("failure_detail")
            attempt.evidence_artifact_ids = input.get("evidence_artifact_ids", [])
            attempt.finished_at = datetime.now(UTC)
            session.commit()

    await asyncio.to_thread(_finish)


@activity.defn
@trace_activity
async def set_task_status_activity(input: dict[str, Any]) -> None:
    factory, _store = refs()

    def _set() -> None:
        from app.services.planning.tasks import assert_task_transition  # noqa: PLC0415

        with factory() as session:
            task = load_task_row(session, uuid.UUID(input["task_id"]))
            assert_task_transition(task.status, input["status"])
            task.status = input["status"]
            session.commit()

    await asyncio.to_thread(_set)


@activity.defn
@trace_activity
async def record_event_activity(input: dict[str, Any]) -> None:
    factory, _store = refs()

    def _record() -> None:
        with factory() as session:
            task_id = uuid.UUID(input["task_id"])
            task = session.get(Task, task_id)
            session.add(
                Event(
                    event_type=input["event_type"],
                    source="temporal",
                    project_id=task.project_id if task else None,
                    task_id=task_id,
                    payload=input.get("payload", {}),
                )
            )
            session.commit()

    await asyncio.to_thread(_record)
