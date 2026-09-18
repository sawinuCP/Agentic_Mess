"""Manual retention trigger (Wave 3, W3-RETAIN-1): bounded prune of event history
and artifact blobs per the configured windows. Authenticated like every /api route."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.realtime.retention import run_retention

router = APIRouter(tags=["retention"])


class RetentionOut(BaseModel):
    events_pruned: int
    artifact_blobs_pruned: int


@router.post("/api/retention/prune", response_model=RetentionOut)
async def trigger_retention(request: Request) -> RetentionOut:
    settings = request.app.state.settings
    factory = request.app.state.session_factory
    results = await asyncio.to_thread(run_retention, settings, factory)
    return RetentionOut(**results)
