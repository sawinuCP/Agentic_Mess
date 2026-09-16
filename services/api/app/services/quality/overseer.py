"""Requirement overseer (FR-026/027, AC-011/015, spec §23): machine-checked traceability.

Chain: Requirement -> AcceptanceCriterion -> Task -> Agent Attempt -> Code Change
-> Test -> Evidence -> VERIFIED / FAILED / UNKNOWN.

Rules enforced here (not negotiable by agents):
- A criterion is VERIFIED only with evidence (a durable validation record backed
  by an artifact).
- Unverified mandatory requirements block final completion — agent self-reports
  never satisfy the gate (FR-026).
- Scope drift (tasks without requirement linkage) produces an alert event, not a
  silent pass; user-approved scope changes become durable decisions.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import DomainError
from app.db.models import (
    AcceptanceCriterion,
    Artifact,
    Requirement,
    Task,
    TaskAttempt,
    Validation,
)


def criterion_state(db: Session, criterion: AcceptanceCriterion) -> str:
    """Resolve a criterion's state from its own status + durable validations."""
    validations = db.scalars(
        select(Validation).where(Validation.acceptance_criterion_id == criterion.id)
    ).all()
    if criterion.status == "failed" or any(v.status == "failed" for v in validations):
        return "failed"
    if criterion.status == "verified" or any(v.status == "passed" for v in validations):
        return "verified"
    return "unknown"


def _requirement_entry(db: Session, requirement: Requirement) -> dict[str, Any]:
    tasks = db.scalars(select(Task).where(Task.requirement_id == requirement.id)).all()
    criteria = db.scalars(
        select(AcceptanceCriterion).where(AcceptanceCriterion.requirement_id == requirement.id)
    ).all()
    criterion_ids = {criterion.id for criterion in criteria}
    validations = (
        db.scalars(
            select(Validation).where(Validation.acceptance_criterion_id.in_(criterion_ids))
        ).all()
        if criterion_ids
        else []
    )
    criterion_entries = [
        {
            "id": str(criterion.id),
            "description": criterion.description,
            "kind": criterion.kind,
            "mandatory": criterion.mandatory,
            "state": criterion_state(db, criterion),
        }
        for criterion in criteria
    ]
    mandatory_states = [entry["state"] for entry in criterion_entries if entry["mandatory"]]
    if tasks and mandatory_states and all(state == "verified" for state in mandatory_states):
        state = "VERIFIED"
    elif any(state == "failed" for state in mandatory_states):
        state = "FAILED"
    else:
        state = "UNKNOWN"
    evidence = [
        str(validation.evidence_artifact_id)
        for validation in validations
        if validation.evidence_artifact_id is not None
    ]
    return {
        "id": str(requirement.id),
        "title": requirement.title,
        "priority": requirement.priority,  # must = mandatory (spec §23)
        "status": state,
        "implemented": bool(tasks),
        "task_ids": [str(task.id) for task in tasks],
        "criteria": criterion_entries,
        "validation_evidence_artifact_ids": evidence,
    }


def _tasks_with_evidence(db: Session, project_id: uuid.UUID) -> dict[str, list[str]]:
    """Successful attempts' evidence artifact ids, keyed by task id (spec §23 chain)."""
    task_ids = list(db.scalars(select(Task.id).where(Task.project_id == project_id)).all())
    evidence: dict[str, list[str]] = {}
    if not task_ids:
        return evidence
    attempts = db.scalars(select(TaskAttempt).where(TaskAttempt.task_id.in_(task_ids))).all()
    for attempt in attempts:
        if attempt.outcome == "success" and attempt.evidence_artifact_ids:
            evidence.setdefault(str(attempt.task_id), []).extend(
                str(a) for a in attempt.evidence_artifact_ids
            )
    return evidence


def traceability_report(db: Session, project_id: uuid.UUID) -> dict[str, Any]:
    """Full Requirement -> Criterion -> Task -> Attempt -> Evidence map (AC-011)."""
    requirements = db.scalars(select(Requirement).where(Requirement.project_id == project_id)).all()
    entries = [_requirement_entry(db, requirement) for requirement in requirements]

    orphan_tasks = db.scalars(
        select(Task).where(
            Task.project_id == project_id, Task.requirement_id.is_(None), Task.plan_id.is_(None)
        )
    ).all()
    evidence_by_task = _tasks_with_evidence(db, project_id)
    for entry in entries:
        entry["evidence_artifact_ids"] = [
            artifact_id
            for task_id in entry["task_ids"]
            for artifact_id in evidence_by_task.get(task_id, [])
        ]

    coverage = {
        "total": len(entries),
        "verified": sum(1 for entry in entries if entry["status"] == "VERIFIED"),
        "failed": sum(1 for entry in entries if entry["status"] == "FAILED"),
        "unknown": sum(1 for entry in entries if entry["status"] == "UNKNOWN"),
    }
    return {
        "project_id": str(project_id),
        "generated_at": datetime.now(UTC).isoformat(),
        "requirements": entries,
        "coverage": coverage,
        "orphan_task_ids": [str(task.id) for task in orphan_tasks],
        "scope_drift": bool(orphan_tasks),
    }


def verify_criterion(
    db: Session,
    criterion_id: uuid.UUID,
    *,
    evidence_artifact_id: uuid.UUID,
    task_id: uuid.UUID | None = None,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record an evidence-backed verification for a criterion (VERIFIED only with evidence).

    Creates a durable ``Validation`` (kind=requirement, status=passed) referencing the
    evidence artifact and flips the criterion status. Missing evidence = 404 — the gate
    can never be satisfied by a claim alone (FR-026).
    """
    criterion = db.get(AcceptanceCriterion, criterion_id)
    if criterion is None:
        raise DomainError("Acceptance criterion not found", 404)
    artifact = db.get(Artifact, evidence_artifact_id)
    if artifact is None:
        raise DomainError("Evidence artifact not found — verification requires evidence", 404)

    validation = Validation(
        project_id=artifact.project_id,
        task_id=task_id,
        acceptance_criterion_id=criterion.id,
        kind="requirement",
        status="passed",
        evidence_artifact_id=artifact.id,
        detail={"artifact_name": artifact.name, **(detail or {})},
    )
    db.add(validation)
    criterion.status = "verified"
    db.commit()
    return {
        "criterion_id": str(criterion.id),
        "state": "verified",
        "validation_id": str(validation.id),
        "evidence_artifact_id": str(artifact.id),
    }


def completion_report(factory: sessionmaker[Session], project_id: uuid.UUID) -> dict[str, Any]:
    """Evidence-backed completion gate (FR-026/027, AC-015).

    Fail-closed: completion is allowed only when every mandatory (``must``) requirement
    is implemented and every mandatory criterion is VERIFIED with evidence. Anything
    else produces explicit blockers; scope drift surfaces as warnings plus an alert.
    """
    with factory() as session:
        report = traceability_report(session, project_id)

    blockers: list[str] = []
    warnings: list[str] = []
    if not report["requirements"]:
        blockers.append(
            "no requirements registered — evidence-backed completion "
            "requires at least one tracked requirement"
        )
    for entry in report["requirements"]:
        mandatory = entry["priority"] == "must"
        if not entry["implemented"]:
            message = f"requirement '{entry['title']}' has no tasks (unimplemented)"
            (blockers if mandatory else warnings).append(message)
            continue
        for criterion in entry["criteria"]:
            if criterion["mandatory"] and criterion["state"] != "verified":
                message = f"criterion '{criterion['description'][:80]}' is {criterion['state']}"
                (blockers if mandatory else warnings).append(message)

    if report["scope_drift"]:
        warnings.append(
            f"{len(report['orphan_task_ids'])} task(s) without requirement linkage — "
            "approve as durable decisions or re-plan"
        )

    report["completion_allowed"] = not blockers
    report["blockers"] = blockers
    report["warnings"] = warnings
    return report
