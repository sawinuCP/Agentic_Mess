"""Runtime manager (FR-018/SEC-005): spec resolution, docker argv, local execution."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from app.core.errors import DomainError
from app.runtime.runtimes import RuntimeSpec, docker_argv, execute, resolve_spec


class _Settings:
    runtime_backend = "local"
    docker_image = "python:3.11-slim"
    docker_network = "none"
    docker_memory = "512m"
    docker_cpus = "1.0"


def test_resolve_spec_defaults_to_local() -> None:
    spec = resolve_spec(_Settings(), {})
    assert spec.backend == "local" and spec.image == "python:3.11-slim"


def test_resolve_spec_payload_overrides_settings() -> None:
    spec = resolve_spec(_Settings(), {"runtime": {"backend": "docker", "image": "node:22"}})
    assert spec.backend == "docker" and spec.image == "node:22"
    assert spec.network == "none"  # SEC-005 default: untrusted code gets no network


def test_resolve_spec_rejects_unknown_backend() -> None:
    with pytest.raises(DomainError) as excinfo:
        resolve_spec(_Settings(), {"runtime": {"backend": "teleport"}})
    assert excinfo.value.status_code == 422


def test_docker_argv_contains_the_isolation_flags() -> None:
    spec = RuntimeSpec(backend="docker", image="python:3.11-slim")
    argv = docker_argv(spec, ["python", "work.py"], Path("C:/tmp/proj"))
    joined = " ".join(argv)
    assert argv[:2] == ["docker", "run"]
    assert "--rm" in argv
    assert "--network none" in joined
    assert "--memory 512m" in joined
    assert "--cpus 1.0" in joined
    assert "no-new-privileges" in joined
    assert "-v C:/tmp/proj:/workspace" in joined or "-v C:\\tmp\\proj:/workspace" in joined
    assert argv[-3:] == ["python:3.11-slim", "python", "work.py"]


def test_local_backend_executes_end_to_end() -> None:
    spec = RuntimeSpec(backend="local")
    result = asyncio.run(
        execute(
            spec,
            [sys.executable, "-c", "print('runtime-ok')"],
            Path("."),
            timeout_seconds=60,
        )
    )
    assert result.exit_code == 0 and "runtime-ok" in result.stdout

    # Docker execution itself needs an image + daemon, verified live in
    # scripts/smoke_runtime.py; the argv contract is covered above.
