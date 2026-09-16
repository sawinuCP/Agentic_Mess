"""Oversight endpoints (Phase 8, FR-026/027, spec §23): traceability + completion gate."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_project
from app.db.models import Artifact, Project
from app.schemas.quality import CriterionVerifyIn
from app.services.core.events import record_event
from app.services.quality import overseer

router = APIRouter(tags=["oversight"])


@router.get("/api/projects/{project_id}/oversight/traceability")
async def get_traceability(project_id: uuid.UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Requirement -> Criterion -> Task -> Attempt -> Evidence map (AC-011)."""
    return overseer.traceability_report(db, project_id)


@router.post("/api/requirements/{requirement_id}/criteria/{criterion_id}/verify")
async def verify_criterion(
    requirement_id: uuid.UUID,
    criterion_id: uuid.UUID,
    body: CriterionVerifyIn,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Record evidence-backed verification — missing evidence is a 404 (FR-026)."""
    _ = requirement_id  # criterion ids are globally unique; nesting is for readability
    return overseer.verify_criterion(
        db,
        criterion_id,
        evidence_artifact_id=uuid.UUID(body.evidence_artifact_id),
        task_id=uuid.UUID(body.task_id) if body.task_id else None,
        detail=body.detail,
    )


def _persist_report(request: Request, project: Project, report: dict[str, Any]) -> str:
    """Store the completion report as a durable artifact (FR-027)."""
    blob = request.app.state.artifacts.put(
        json.dumps(report, indent=2, default=str).encode("utf-8")
    )
    with request.app.state.session_factory() as session:
        artifact = Artifact(
            project_id=project.id,
            name="completion-report",
            kind="completion_report",
            mime="application/json",
            size=blob.size,
            sha256=blob.sha256,
            storage_path=blob.storage_path,
        )
        session.add(artifact)
        session.commit()
        return str(artifact.id)


@router.post("/api/projects/{project_id}/oversight/completion")
async def completion_gate(request: Request, project: Project = Depends(get_project)) -> Any:
    """Final evidence-backed completion report (FR-026/027, AC-015).

    Fail-closed: 409 with explicit blockers when any mandatory requirement is
    unverified/unimplemented; 200 with the durable report artifact when allowed.
    """
    report = await asyncio.to_thread(
        overseer.completion_report, request.app.state.session_factory, project.id
    )
    if report["scope_drift"]:
        await record_event(
            request.app.state.session_factory,
            "SCOPE_DRIFT_ALERT",
            project_id=project.id,
            payload={"orphan_task_ids": report["orphan_task_ids"]},
        )
    if not report["completion_allowed"]:
        return JSONResponse(
            status_code=409,
            content={
                "detail": "completion blocked by unmet acceptance criteria",
                "report": report,
            },
        )
    report["artifact_id"] = await asyncio.to_thread(_persist_report, request, project, report)
    return report
