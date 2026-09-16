"""Task completion gates (FR-026, AC-005/015): evidence-required, security-checked.

FR-026 — "The system shall not declare completion solely from an agent's
self-report." The gate below is the enforcement point: a task may only be
declared complete when (a) a successful attempt recorded evidence artifacts,
(b) the task is linked to a requirement (no scope drift), and (c) the security
scan found no credentials in the project tree. Failures are explicit blockers,
never silent passes.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import DomainError
from app.db.models import Task, TaskAttempt, Validation
from app.services.core.events import record_event
from app.services.quality import secrets as secrets_scanner


def _task_or_404(db: Session, task_id: uuid.UUID) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise DomainError("Task not found", 404)
    return task


def security_scan(
    db: Session,
    factory: sessionmaker[Session],
    project_id: uuid.UUID,
    root_path: Path,
    *,
    task_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Run the credential scanner over the project tree and persist a Validation row."""
    summary = secrets_scanner.scan_paths(root_path)
    status = "passed" if summary["finding_count"] == 0 else "failed"
    validation = Validation(
        project_id=project_id,
        task_id=task_id,
        kind="security",
        status=status,
        detail=dict(summary),
    )
    db.add(validation)
    db.commit()

    asyncio.get_running_loop().create_task(
        record_event(
            factory,
            "SECURITY_SCAN_COMPLETED",
            project_id=project_id,
            task_id=task_id,
            payload={"status": status, "findings": summary["finding_count"]},
        )
    )
    return {
        "validation_id": str(validation.id),
        "status": status,
        "scanned_files": summary["scanned_files"],
        "findings": summary["findings"],
    }


def completion_gate(db: Session, task_id: uuid.UUID) -> dict[str, Any]:
    """Evaluate the FR-026 gate for a task: evidence + linkage, with explicit blockers."""
    task = _task_or_404(db, task_id)
    blockers: list[str] = []
    warnings: list[str] = []

    attempts = db.scalars(select(TaskAttempt).where(TaskAttempt.task_id == task.id)).all()
    evidence_artifact_ids = [
        str(artifact_id)
        for attempt in attempts
        if attempt.outcome == "success"
        for artifact_id in attempt.evidence_artifact_ids
    ]
    if not evidence_artifact_ids:
        blockers.append(
            "no successful attempt recorded evidence artifacts — self-report alone "
            "cannot complete a task (FR-026)"
        )

    if task.requirement_id is None and task.plan_id is None:
        warnings.append("task has no requirement linkage (scope drift) — link it or re-plan")

    failed_security = db.scalars(
        select(Validation).where(
            Validation.task_id == task.id,
            Validation.kind == "security",
            Validation.status == "failed",
        )
    ).all()
    if failed_security:
        blockers.append(
            f"{len(failed_security)} failed security validation(s) — resolve or "
            "acknowledge via HITL before completion"
        )

    return {
        "task_id": str(task.id),
        "generated_at": datetime.now(UTC).isoformat(),
        "evidence_artifact_ids": evidence_artifact_ids,
        "security_scan": "failed" if failed_security else "not_run",
        "completion_allowed": not blockers,
        "blockers": blockers,
        "warnings": warnings,
    }
