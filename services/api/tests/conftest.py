"""Shared fixtures for the API test suite."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

# Settings that guarantee infrastructure is unreachable by construction (port 9 = discard),
# so unit tests are deterministic and fail fast. Explicit kwargs beat environment variables.
UNREACHABLE_SETTINGS = Settings(
    environment="test",
    database_url="postgresql+psycopg://harness:harness@localhost:9/harness",
    redis_url="redis://localhost:9/0",
    nats_url="nats://localhost:9",
    readiness_timeout_seconds=0.5,
    require_redis=False,
    require_nats=False,
    log_level="INFO",
    otel_enabled=False,
    nats_events_enabled=False,  # realtime live hop off; SSE replay-only in tests
)


@pytest.fixture()
def client() -> Iterator[TestClient]:
    app = create_app(UNREACHABLE_SETTINGS)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def app() -> FastAPI:
    """App wired for integration tests; uses HARNESS_DATABASE_URL or the compose default.

    Temporal is pinned off so the fail-closed execute test is deterministic.
    """
    settings = Settings(
        environment="test",
        readiness_timeout_seconds=2.0,
        require_redis=False,
        require_nats=False,
        log_level="INFO",
        otel_enabled=False,
        temporal_enabled=False,
        nats_events_enabled=False,  # live hop off: stream tests inject via gateway.broadcast
        realtime_heartbeat_seconds=0.5,  # fast heartbeats keep SSE tests snappy
    )
    return create_app(settings)


@pytest.fixture()
def project(app: FastAPI, tmp_path: Path) -> Iterator[tuple[FastAPI, TestClient, str, Path]]:
    """A registered project rooted at a throwaway directory, plus a live test client."""
    root = unique_repo_root(tmp_path)
    with TestClient(app) as client:
        response = client.post("/api/projects/open", json={"root_path": str(root)})
        yield app, client, response.json()["id"], root


@pytest.fixture()
def repo_root(tmp_path: Path) -> Path:
    """A globally-unique existing directory for ``/api/projects/open``.

    pytest's numbered temp dirs can repeat across sessions once old ones are
    cleaned up, and project open is idempotent by design — without a unique
    subdir a colliding run would silently reuse a stale project row.
    """
    return unique_repo_root(tmp_path)


def unique_repo_root(tmp_path: Path) -> Path:
    root = tmp_path / f"repo-{uuid.uuid4().hex[:8]}"
    root.mkdir()
    return root


@pytest.fixture()
def port_range() -> tuple[int, int]:
    """A run-unique 4-port window per test — the port ledger is global, so tests
    must never share a range (cross-test interference otherwise)."""
    base = 30000 + (int(uuid.uuid4().hex[:4], 16) % 20000)
    return base, base + 3


# --- Wave 3 realtime helpers ---------------------------------------------------


AUTH_TEST_TOKEN = "wave3-stream-token"


def auth_test_settings() -> Settings:
    """Token-protected settings for realtime auth tests."""
    return Settings(
        environment="test",
        readiness_timeout_seconds=2.0,
        require_redis=False,
        require_nats=False,
        log_level="INFO",
        otel_enabled=False,
        temporal_enabled=False,
        nats_events_enabled=False,  # live hop off: stream tests inject via gateway
        realtime_heartbeat_seconds=0.3,  # fast heartbeats keep SSE tests snappy
        api_token=AUTH_TEST_TOKEN,
    )


def parse_sse_frame(raw: bytes) -> dict[str, str]:
    frame: dict[str, str] = {}
    for line in raw.decode("utf-8").splitlines():
        if line.startswith(":"):
            frame["comment"] = line
            continue
        key, _, value = line.partition(": ")
        if value:
            frame[key] = value
    return frame


def sse_event_frames(frames: list[dict[str, str]]) -> list[dict[str, str]]:
    return [f for f in frames if "event" in f and f["event"] != "harness.control"]


def sse_control_frames(frames: list[dict[str, str]]) -> list[dict[str, object]]:
    import json

    return [json.loads(f["data"]) for f in frames if f.get("event") == "harness.control"]


def make_test_envelope(
    project_id: str, sequence: int, event_type: str = "AGENT_STATUS_CHANGED"
) -> Any:
    from app.realtime.envelope import EventEnvelope

    return EventEnvelope(
        event_id=str(uuid.uuid4()),
        event_type=event_type,
        timestamp="2026-09-17T00:00:00+00:00",
        project_id=project_id,
        sequence=sequence,
        payload={"to": "running"},
    )


def seed_project_events(client: Any, project_id: str, count: int) -> list[dict[str, Any]]:
    """Create ``count`` requirements (each records a durable, sequenced event)."""
    for index in range(count):
        client.post(
            f"/api/projects/{project_id}/requirements",
            json={
                "title": f"req {index}",
                "description": "Users must be able to sign in.",
                "desired_outcome": "Working login flow",
                "priority": "must",
                "criteria": [{"description": "It works", "kind": "automated_test"}],
            },
        )
    events = client.get(
        "/api/events", params={"project_id": project_id, "order": "asc", "limit": 500}
    ).json()
    return [e for e in events if e["project_seq"] is not None]


class SseTestClient:
    """Drive one SSE request against a live ASGI app.

    TestClient buffers whole responses (its transport waits for the ASGI call to
    return), so infinite SSE streams are driven through this minimal ASGI harness
    instead: it exercises the real middleware stack (auth included) and streaming
    semantics — headers on start, incremental body chunks, disconnect propagation.
    """

    def __init__(self, app: Any, path: str, headers: dict[str, str] | None = None) -> None:
        from urllib.parse import unquote, urlsplit

        parsed = urlsplit(path)
        self.scope: dict[str, Any] = {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "path": unquote(parsed.path),
            "raw_path": parsed.path.encode(),
            "root_path": "",
            "scheme": "http",
            "query_string": parsed.query.encode(),
            "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
        }
        self._app = app
        self._chunks: asyncio.Queue[bytes] = asyncio.Queue()
        self._disconnect = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._buffer = b""
        self.status_code: int | None = None
        self.headers: dict[str, str] = {}

    def start(self) -> None:
        self._task = asyncio.get_running_loop().create_task(self._run())

    async def _run(self) -> None:
        async def receive() -> dict[str, str]:
            await self._disconnect.wait()
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                self.status_code = int(message["status"])
                self.headers = {k.decode(): v.decode() for k, v in message.get("headers", [])}
            elif message["type"] == "http.response.body":
                body = message.get("body", b"")
                if body:
                    await self._chunks.put(body)
                if not message.get("more_body"):
                    self._disconnect.set()

        await self._app(self.scope, receive, send)

    async def frames(self, count: int = 1, timeout: float = 5.0) -> list[dict[str, str]]:
        """Collect ``count`` complete SSE frames (deadline-bounded, CI-stable)."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        frames: list[dict[str, str]] = []
        while len(frames) < count:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError(f"only {len(frames)}/{count} SSE frames arrived")
            try:
                self._buffer += await asyncio.wait_for(self._chunks.get(), timeout=remaining)
            except TimeoutError:
                break
            while b"\n\n" in self._buffer and len(frames) < count:
                raw, self._buffer = self._buffer.split(b"\n\n", 1)
                frames.append(parse_sse_frame(raw))
        return frames

    async def wait_status(self, timeout: float = 2.0) -> int | None:
        """Wait until response headers arrived (non-streaming responses, e.g. 401)."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while self.status_code is None and loop.time() < deadline:
            await asyncio.sleep(0.01)
        return self.status_code

    async def disconnect(self) -> None:
        self._disconnect.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(self._task), timeout=2.0)
            except (TimeoutError, asyncio.CancelledError):
                self._task.cancel()


@pytest.fixture()
def make_envelope() -> Any:
    """Factory for realtime wire envelopes (tests only)."""
    return make_test_envelope


@pytest.fixture()
def sse() -> type[SseTestClient]:
    """SSE test harness class (drives live ASGI streaming without buffering)."""
    return SseTestClient


@pytest.fixture()
def seed_events() -> Any:
    """Create durable sequenced events via the requirements API."""
    return seed_project_events


@pytest.fixture()
def event_frames_of() -> Any:
    return sse_event_frames


@pytest.fixture()
def control_frames_of() -> Any:
    return sse_control_frames


@pytest.fixture()
def auth_settings() -> Any:
    return auth_test_settings
