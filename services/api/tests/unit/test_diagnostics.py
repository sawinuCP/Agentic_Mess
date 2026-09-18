"""Diagnostics endpoint: fail-soft probes that never block the event loop."""

from __future__ import annotations

import asyncio
import time

from fastapi.testclient import TestClient

from app.api.routes.core.diagnostics import _probe


def test_sync_probe_timeout_is_enforced_off_loop() -> None:
    def _hang() -> str:
        time.sleep(10)  # would stall the endpoint if run on the event loop
        return "never"

    # A bare loop (no asyncio.run executor shutdown) measures only the probe.
    loop = asyncio.new_event_loop()
    try:
        started = time.monotonic()
        status, detail = loop.run_until_complete(_probe(0.05, _hang))
        elapsed = time.monotonic() - started
    finally:
        loop.close()
    assert status == "down"
    assert "TimeoutError" in detail
    assert elapsed < 5  # returned after the timeout, not after the 30s work


def test_sync_probe_success_passes_through() -> None:
    status, detail = asyncio.run(_probe(5.0, lambda: {"a": 1}))
    assert (status, detail) == ("ok", {"a": 1})


def test_diagnostics_endpoint_is_fail_soft(client: TestClient) -> None:
    # UNREACHABLE_SETTINGS: every backend probe reports down, endpoint stays 200.
    response = client.get("/api/diagnostics")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "app",
        "database",
        "counts",
        "artifact_store",
        "temp_dir",
        "redis",
        "nats",
        "config",
    }
    assert body["database"]["status"] == "down"
    assert body["redis"]["status"] == "down"
    assert body["nats"]["status"] == "down"
    assert body["app"]["uptime_seconds"] >= 0
