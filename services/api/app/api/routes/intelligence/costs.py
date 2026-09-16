"""Model cost ledger endpoints (spec §32): cumulative token accounting per project/task."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.intelligence import CostsOut
from app.services import costs as cost_service

router = APIRouter(tags=["costs"])


@router.get("/api/projects/{project_id}/intelligence/costs", response_model=CostsOut)
async def costs(
    request: Request,
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    task_id: uuid.UUID | None = Query(None, description="Scope the summary to one task"),
) -> CostsOut:
    """Model invocation ledger summary (totals + per-model/per-role breakdowns)."""
    summary = cost_service.summary(db, project_id, task_id)
    return CostsOut(
        invocations=summary["invocations"],
        total_tokens=summary["total_tokens"],
        by_model=summary["by_model"],
        by_role=summary["by_role"],
        task_id=task_id,
        budget_tokens_per_task=request.app.state.settings.model_budget_tokens_per_task,
    )
