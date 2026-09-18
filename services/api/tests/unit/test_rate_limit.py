"""Per-IP rate-limit middleware behaviour (W1-RATE-1)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.conftest import UNREACHABLE_SETTINGS


def _limited_settings(**overrides: object) -> Settings:
    base = UNREACHABLE_SETTINGS.model_dump()
    base.update(
        {
            "rate_limit_enabled": True,
            "rate_limit_requests_per_window": 3,
            "rate_limit_window_seconds": 60.0,
        }
    )
    base.update(overrides)  # type: ignore[typeddict-item]
    return Settings(**base)  # type: ignore[arg-type]


def test_rate_limit_returns_429_with_retry_after() -> None:
    app = create_app(_limited_settings())
    with TestClient(app) as client:
        statuses = [client.get("/api/no-such-route-xyz").status_code for _ in range(5)]
    assert statuses[:3] != [429, 429, 429]  # first window passes through (404s, no DB)
    assert statuses[3] == 429
    assert statuses[4] == 429


def test_rate_limit_retry_after_header_present() -> None:
    app = create_app(_limited_settings())
    with TestClient(app) as client:
        for _ in range(3):
            client.get("/api/no-such-route-xyz")
        response = client.get("/api/no-such-route-xyz")
    assert response.status_code == 429
    assert response.json() == {"detail": "rate limit exceeded"}
    assert int(response.headers["retry-after"]) >= 1
    # Rejected requests still carry request-id correlation.
    assert response.headers["x-request-id"]


def test_rate_limit_exempts_public_paths() -> None:
    app = create_app(_limited_settings())
    with TestClient(app) as client:
        for _ in range(5):
            response = client.get("/healthz")
            assert response.status_code == 200
        # Health probes consumed no budget: the first API call still passes.
        assert client.get("/api/no-such-route-xyz").status_code == 404


def test_rate_limit_disabled_passes_everything() -> None:
    app = create_app(_limited_settings(rate_limit_enabled=False))
    with TestClient(app) as client:
        statuses = [client.get("/api/no-such-route-xyz").status_code for _ in range(6)]
    assert 429 not in statuses
