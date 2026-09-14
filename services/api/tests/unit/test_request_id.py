"""Request-ID middleware behaviour."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_request_id_generated_when_missing(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.headers["x-request-id"]


def test_request_id_preserved_when_provided(client: TestClient) -> None:
    response = client.get("/healthz", headers={"X-Request-ID": "test-123"})
    assert response.headers["x-request-id"] == "test-123"
