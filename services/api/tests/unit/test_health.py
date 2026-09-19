"""Liveness/readiness endpoint behaviour."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_healthz_reports_liveness(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["environment"] == "test"
    assert body["version"]


def test_readyz_fails_closed_and_reports_components(client: TestClient) -> None:
    response = client.get("/readyz")
    # PostgreSQL is unreachable by construction in the unit environment -> fail closed.
    assert response.status_code == 503
    body = response.json()
    assert body["ready"] is False
    assert body["environment"] == "test"
    for component in ("postgres", "redis", "nats"):
        assert component in body["checks"]
        assert body["checks"][component]["status"] == "down"
    # Opt-in integrations report honestly instead of failing the gate.
    assert body["checks"]["temporal"]["status"] == "disabled"
    assert body["checks"]["artifacts"]["status"] == "ok"


def test_app_restarts_cleanly_twice() -> None:
    """Lifespan shutdown releases everything (bus, gateway, terminals,
    engine): a second session on a fresh app works — restart-safe."""
    from fastapi.testclient import TestClient as Client

    from app.main import create_app
    from tests.conftest import UNREACHABLE_SETTINGS

    for _ in range(2):
        app = create_app(UNREACHABLE_SETTINGS)
        with Client(app) as session:
            assert session.get("/healthz").status_code == 200
