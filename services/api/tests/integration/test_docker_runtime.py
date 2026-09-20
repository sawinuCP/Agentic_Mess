"""Docker runtime backend against the real daemon (Wave 12 §7/§15).

Skipped without a daemon. Uses the cached ``python:3.11-slim`` image —
no pulls, no network in the container. Commands use the container's
``python3`` (host interpreter paths do not exist inside the image).
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest

from app.runtime.runtimes import RuntimeSpec, docker_argv, execute

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("docker") is None, reason="docker not installed"),
]


def test_docker_argv_isolation() -> None:
    argv = docker_argv(
        RuntimeSpec(backend="docker", image="python:3.11-slim"), ["echo", "hi"], Path(".")
    )
    for flag in ("--cap-drop", "ALL", "--read-only", "no-new-privileges", "--pids-limit"):
        assert flag in argv


def test_docker_executes_python_and_returns_output(tmp_path: Path) -> None:
    async def _run():
        return await execute(
            RuntimeSpec(backend="docker", image="python:3.11-slim"),
            ["python3", "-c", "print(6*7)"],
            tmp_path,
            timeout_seconds=180,
        )

    try:
        result = asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001 — daemon states vary; report, don't hang
        pytest.skip(f"docker daemon unavailable: {exc}")
    assert result.exit_code == 0, result.stderr[-2000:]
    assert result.stdout.strip() == "42"


def test_docker_container_has_no_network(tmp_path: Path) -> None:
    """SEC-005 live: the container cannot reach the outside world."""

    async def _run():
        return await execute(
            RuntimeSpec(backend="docker", image="python:3.11-slim", network="none"),
            ["python3", "-c", "import socket;socket.create_connection(('8.8.8.8',53),timeout=5)"],
            tmp_path,
            timeout_seconds=180,
        )

    try:
        result = asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001 — daemon states vary
        pytest.skip(f"docker daemon unavailable: {exc}")
    assert result.exit_code != 0  # connection must fail inside --network none
