"""Quality-gate endpoints (Phase 8): security scan + task completion gate (FR-026)."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_project
from app.db.models import Project
from app.schemas.quality import SecurityScanIn
from app.services.quality import gates

router = APIRouter(tags=["quality-gates"])


@router.post("/api/projects/{project_id}/quality/security-scan")
async def run_security_scan(
    request: Request,
    project_id: uuid.UUID,
    body: SecurityScanIn | None = None,
    project: Project = Depends(get_project),
) -> dict[str, Any]:
    """Credential scan over the project tree, persisted as a security Validation."""
    with request.app.state.session_factory() as session:
        return gates.security_scan(
            session,
            request.app.state.session_factory,
            project.id,
            Path(project.root_path),
            task_id=uuid.UUID(body.task_id) if body and body.task_id else None,
        )


@router.post("/api/tasks/{task_id}/completion-gate")
async def task_completion_gate(task_id: uuid.UUID, db: Session = Depends(get_db)) -> Any:
    """FR-026 enforcement: evidence + linkage gate for declaring a task complete."""
    report = gates.completion_gate(db, task_id)
    if not report["completion_allowed"]:
        return JSONResponse(
            status_code=409,
            content={"detail": "task completion blocked", "report": report},
        )
    return report
