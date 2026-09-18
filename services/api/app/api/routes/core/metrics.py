"""Prometheus metrics endpoint (Wave 3, W3-METRICS-1).

Renders the process registry in Prometheus text format. Not in ``PUBLIC_PATHS``:
when a bearer token is configured, scraping requires it (Wave 1 posture).
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from app.core.metrics import MetricsRegistry

router = APIRouter(tags=["metrics"])


@router.get("/metrics", include_in_schema=False)
def prometheus_metrics(request: Request) -> Response:
    """Prometheus scrape target (text format, not a JSON API route)."""
    registry: MetricsRegistry | None = getattr(request.app.state, "metrics", None)
    body = registry.render_prometheus() if registry is not None else ""
    return Response(content=body, media_type="text/plain; version=0.0.4; charset=utf-8")
