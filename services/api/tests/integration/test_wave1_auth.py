"""Wave 1 security integration: HTTP/WS auth, CORS allow-list, host-binding
fail-closed posture, and the agent env allowlist wiring (SR-01/SR-02/SR-04)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.config import Settings
from app.main import create_app
from app.runtime.env_sandbox import build_agent_environment, configure_agent_env
from tests.conftest import UNREACHABLE_SETTINGS

pytestmark = pytest.mark.integration

TOKEN = "wave1-integration-token"  # test-only value, committed nowhere else


def _auth_settings(**overrides: object) -> Settings:
    return Settings(
        environment="test",
        readiness_timeout_seconds=2.0,
        require_redis=False,
        require_nats=False,
        log_level="INFO",
        otel_enabled=False,
        temporal_enabled=False,
        api_token=TOKEN,
        **overrides,  # type: ignore[arg-type]
    )


@pytest.fixture()
def auth_app() -> FastAPI:
    return create_app(_auth_settings())


@pytest.fixture()
def auth_client(auth_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(auth_app) as client:
        yield client


# --- HTTP authentication -------------------------------------------------------


def test_protected_endpoint_rejects_missing_token(auth_client: TestClient) -> None:
    response = auth_client.get("/api/projects")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {"detail": "unauthenticated"}


def test_protected_endpoint_rejects_invalid_token(auth_client: TestClient) -> None:
    response = auth_client.get(
        "/api/projects", headers={"Authorization": "Bearer definitely-wrong"}
    )
    assert response.status_code == 401


def test_protected_endpoint_accepts_valid_token(auth_client: TestClient) -> None:
    response = auth_client.get("/api/projects", headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 200


def test_health_endpoints_stay_public(auth_client: TestClient) -> None:
    assert auth_client.get("/healthz").status_code == 200
    assert auth_client.get("/readyz").status_code == 200  # readiness probe, unauthenticated


def test_auth_disabled_by_default(project: tuple[FastAPI, TestClient, str, Path]) -> None:
    """Local desktop posture: no token configured → endpoints stay open."""
    _app, client, _project_id, _root = project
    assert client.get("/api/projects").status_code == 200


def test_non_loopback_bind_without_token_refuses_startup() -> None:
    app = create_app(Settings(environment="test", host="0.0.0.0", api_token=""))
    with pytest.raises(RuntimeError, match="non-loopback"), TestClient(app):
        pass  # lifespan raises before serving


# --- CORS allow-list -----------------------------------------------------------


def test_cors_preflight_unauthenticated_and_allowed(auth_client: TestClient) -> None:
    response = auth_client.options(
        "/api/projects",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_cors_preflight_for_unknown_origin_is_denied(auth_client: TestClient) -> None:
    response = auth_client.options(
        "/api/projects",
        headers={
            "Origin": "http://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" not in response.headers


# --- WebSocket authentication --------------------------------------------------


def test_ws_rejects_missing_token(auth_client: TestClient) -> None:
    with (
        pytest.raises(WebSocketDisconnect) as excinfo,
        auth_client.websocket_connect("/api/ws/terminal/does-not-matter"),
    ):
        pass
    assert excinfo.value.code == 4401


def test_ws_rejects_invalid_token(auth_client: TestClient) -> None:
    with (
        pytest.raises(WebSocketDisconnect) as excinfo,
        auth_client.websocket_connect(
            "/api/ws/terminal/does-not-matter",
            subprotocols=["bearer.definitely-wrong"],
        ),
    ):
        pass
    assert excinfo.value.code == 4401


def test_ws_valid_token_reaches_the_route(auth_client: TestClient) -> None:
    """The middleware passes a valid token; the route then rejects the unknown
    session id (4404) — proving auth is not itself the failure."""
    with (
        pytest.raises(WebSocketDisconnect) as excinfo,
        auth_client.websocket_connect(
            "/api/ws/terminal/no-such-session",
            subprotocols=[f"bearer.{TOKEN}"],
        ),
    ):
        pass
    assert excinfo.value.code == 4404


# --- agent env allowlist wiring ------------------------------------------------


def test_agent_env_allow_config_wiring(tmp_path: Path) -> None:
    configure_agent_env(["HARNESS_TEST_EXTRA", "MY_TOKEN"])  # deny wins for MY_TOKEN
    try:
        env = build_agent_environment(
            environ={"HARNESS_TEST_EXTRA": "yes", "MY_TOKEN": "nope", "PATH": "/bin"}
        )
        assert env.get("HARNESS_TEST_EXTRA") == "yes"
        assert "MY_TOKEN" not in env
        assert env["PATH"] == "/bin"
    finally:
        configure_agent_env([])  # restore default for other tests
    # extra_allow EXTENDS the baseline+configured set per call (deny still wins).
    env = build_agent_environment(
        environ={"HARNESS_TEST_EXTRA": "yes"}, extra_allow=["HARNESS_TEST_EXTRA"]
    )
    assert env.get("HARNESS_TEST_EXTRA") == "yes"


def test_unreachable_settings_never_enable_auth() -> None:
    assert UNREACHABLE_SETTINGS.api_token == ""
