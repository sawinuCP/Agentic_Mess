"""OpenAPI public surface: curated schema for external clients."""

from __future__ import annotations

from app.main import create_app
from tests.conftest import UNREACHABLE_SETTINGS


def _spec() -> dict:
    return create_app(UNREACHABLE_SETTINGS).openapi()


def test_openapi_documents_conventions() -> None:
    spec = _spec()
    assert spec["info"]["title"] == "AI Harness API"
    assert spec["info"]["version"]
    assert "idempotency_key" in spec["info"]["description"]
    assert "Retry-After" in spec["info"]["description"]


def test_openapi_excludes_the_prometheus_scrape_target() -> None:
    spec = _spec()
    assert "/metrics" not in spec["paths"]
    assert any(path.startswith("/api/") for path in spec["paths"])


def test_openapi_api_routes_have_operation_ids() -> None:
    spec = _spec()
    missing = [
        f"{method.upper()} {path}"
        for path, item in spec["paths"].items()
        if path.startswith("/api/")
        for method, op in item.items()
        if not op.get("operationId")
    ]
    assert missing == []
