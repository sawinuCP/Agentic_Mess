"""Runtime manager (Phase 6, spec §19, FR-018/SEC-005): controlled execution backends.

Every agent execution occurs inside a controlled runtime. Two backends:
``local`` (the Phase-1/3 subprocess runner — trusted editor-equivalent work) and
``docker`` (untrusted code: filesystem isolated to the mounted workspace, no
network by default, memory/CPU caps, no-new-privileges). The backend is chosen
from settings and can be overridden per task via the payload ``runtime`` block —
policy decisions stay outside the model (spec §48).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.errors import DomainError
from app.runtime.runner import ExecResult, run_process

BACKENDS = ("local", "docker")
_DOCKER_TIMEOUT_OVERHEAD_SECONDS = 30.0


@dataclass(frozen=True, slots=True)
class RuntimeSpec:
    backend: str  # local | docker
    image: str = "python:3.11-slim"
    network: str = "none"
    memory: str = "512m"
    cpus: str = "1.0"
    container_workdir: str = "/workspace"


def resolve_spec(settings: Any, payload: dict[str, Any] | None) -> RuntimeSpec:
    """Build the runtime spec from settings, overridable per task payload.

    Payload override shape: ``{"runtime": {"backend": "docker", "image": "..."}}``.
    Unknown backends fail closed (DomainError 422) — never silently local.
    """
    payload_runtime = (payload or {}).get("runtime") or {}
    if not isinstance(payload_runtime, dict):
        raise DomainError("payload.runtime must be an object", 422)

    backend = str(payload_runtime.get("backend") or getattr(settings, "runtime_backend", "local"))
    if backend not in BACKENDS:
        raise DomainError(f"unknown runtime backend: {backend!r} (expected one of {BACKENDS})", 422)
    return RuntimeSpec(
        backend=backend,
        image=str(payload_runtime.get("image") or getattr(settings, "docker_image", "")),
        network=str(payload_runtime.get("network") or getattr(settings, "docker_network", "none")),
        memory=str(payload_runtime.get("memory") or getattr(settings, "docker_memory", "512m")),
        cpus=str(payload_runtime.get("cpus") or getattr(settings, "docker_cpus", "1.0")),
    )


def docker_argv(spec: RuntimeSpec, argv: list[str], cwd: str | Path) -> list[str]:
    """Build the ``docker run`` argv for executing ``argv`` inside the container.

    Isolation posture (SEC-005): the workspace is bind-mounted at
    ``/workspace`` (the only host path the container sees), the network is
    disabled unless explicitly configured, memory/CPU are capped, and
    privilege escalation is blocked.
    """
    return [
        "docker",
        "run",
        "--rm",
        "--network",
        spec.network,
        "--memory",
        spec.memory,
        "--cpus",
        spec.cpus,
        "--security-opt",
        "no-new-privileges",
        "-v",
        f"{Path(cwd)}:{spec.container_workdir}",
        "-w",
        spec.container_workdir,
        spec.image,
        *argv,
    ]


async def execute(
    spec: RuntimeSpec,
    argv: list[str],
    cwd: str | Path,
    *,
    timeout_seconds: float,
    output_limit: int = 200_000,
) -> ExecResult:
    """Run ``argv`` in the configured backend; returns the shared ExecResult shape.

    Docker runs are wrapped by the host CLI, so the wall-clock budget adds a
    small overhead for container startup while the inner command keeps its own
    budget. Docker daemon failures surface as ``RuntimeUnavailable`` (503).
    """
    if spec.backend == "local":
        return await run_process(
            argv, cwd, timeout_seconds=timeout_seconds, output_limit=output_limit
        )
    if spec.backend == "docker":
        from app.core.errors import DomainError  # noqa: PLC0415

        try:
            return await run_process(
                docker_argv(spec, argv, cwd),
                Path(cwd),
                timeout_seconds=timeout_seconds + _DOCKER_TIMEOUT_OVERHEAD_SECONDS,
                output_limit=output_limit,
            )
        except FileNotFoundError:
            raise DomainError(
                "docker executable was not found on PATH (install Docker Desktop or use "
                "the local runtime backend)",
                503,
            ) from None
        except OSError as exc:
            raise DomainError(f"docker runtime unavailable: {exc}", 503) from None
    raise DomainError(f"unknown runtime backend: {spec.backend!r}", 422)
