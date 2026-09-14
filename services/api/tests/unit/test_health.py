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
