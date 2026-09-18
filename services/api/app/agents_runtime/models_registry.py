"""Model registry and role routing (spec §32): roles → provider/model/budgets.

Configuration-driven — no model names in code. Routes come from a JSON file
(``HARNESS_MODELS_CONFIG``) merged over builtin defaults, keyed by role.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from app.agents_runtime.providers import (
    ModelProvider,
    ModelProviderError,
    ModelRequest,
    ModelResponse,
    ModelRoute,
    get_provider,
)

logger = logging.getLogger("harness.models")

DEFAULT_ROUTES: dict[str, dict[str, Any]] = {
    role: {"provider": "rehearsal", "model": f"rehearsal-{role}", "max_output_tokens": 2048}
    for role in (
        "worker",
        "planner",
        "reviewer",
        "critic",
        "evidence_verifier",
        "adjudicator",
        "supervisor",
        "security",
    )
}


class ModelRegistry:
    """Loads role routes from JSON (or builtin defaults) and dispatches completions.

    ``provider_override`` replaces the provider for every route while keeping the
    configured models/temperatures — used by deterministic tests and smokes of
    model-driven pipelines (e.g. the Phase-8 review flow).
    """

    def __init__(
        self,
        routes: dict[str, dict[str, Any]],
        *,
        provider_override: ModelProvider | None = None,
        max_attempts: int = 3,
        backoff_base_seconds: float = 2.0,
        backoff_factor: float = 2.0,
        backoff_max_seconds: float = 60.0,
        backoff_jitter_ratio: float = 0.25,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._routes = {role: self._route(role, spec) for role, spec in routes.items()}
        self._provider_override = provider_override
        self._max_attempts = max(1, max_attempts)
        self._backoff_base = backoff_base_seconds
        self._backoff_factor = backoff_factor
        self._backoff_max = backoff_max_seconds
        self._backoff_jitter = backoff_jitter_ratio
        self._sleep = sleep

    @staticmethod
    def _route(role: str, spec: dict[str, Any]) -> ModelRoute:
        return ModelRoute(
            role=role,
            provider=str(spec.get("provider", "rehearsal")),
            model=str(spec.get("model", f"rehearsal-{role}")),
            max_output_tokens=int(spec.get("max_output_tokens", 2048)),
            temperature=float(spec.get("temperature", 0.2)),
            fallback_role=str(spec.get("fallback_role", "")),
            timeout_seconds=float(spec.get("timeout_seconds", 120.0)),
        )

    @classmethod
    def load(cls, config_path: Path | None, **retry_kwargs: Any) -> ModelRegistry:
        """Load routes from JSON (or builtin defaults); ``retry_kwargs`` forward to
        the constructor (max_attempts/backoff_*), letting callers inject settings."""
        if config_path and Path(config_path).is_file():
            data = json.loads(Path(config_path).read_text(encoding="utf-8"))
            routes = {**DEFAULT_ROUTES, **data.get("routes", {})}
            logger.info("model registry loaded from %s", config_path)
            return cls(routes, **retry_kwargs)
        return cls(dict(DEFAULT_ROUTES), **retry_kwargs)

    def route_for(self, role: str) -> ModelRoute:
        route = self._routes.get(role) or self._routes.get("worker")
        if route is None:
            raise ModelProviderError(f"No model route for role {role!r}")
        return route

    def _provider_for(self, route: ModelRoute) -> ModelProvider:
        return self._provider_override or get_provider(route.provider)

    async def complete(self, request: ModelRequest) -> ModelResponse:
        """Complete with bounded retries then escalation (spec §32).

        Transient provider failures (timeouts, 429/5xx) retry up to
        ``max_attempts`` with exponential backoff
        ``delay = min(base * factor**(attempt-1), max)`` plus ± jitter. A
        permanent failure — or exhausted retries — escalates once via the
        route's ``fallback_role``, recording that the fallback ran. The
        fallback itself is single-shot (bounded total cost).
        """
        route = self.route_for(request.role)
        last_error: ModelProviderError | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                return await self._provider_for(route).complete(request, route)
            except ModelProviderError as exc:
                last_error = exc
                if not exc.transient or attempt >= self._max_attempts:
                    break
                delay = min(
                    self._backoff_base * (self._backoff_factor ** (attempt - 1)),
                    self._backoff_max,
                )
                delay *= 1.0 + random.uniform(-self._backoff_jitter, self._backoff_jitter)
                logger.warning(
                    "model provider %r transient failure (attempt %d/%d); retrying in %.1fs: %s",
                    route.provider,
                    attempt,
                    self._max_attempts,
                    max(0.0, delay),
                    exc,
                )
                await self._sleep(max(0.0, delay))
        assert last_error is not None  # loop runs at least once; return/raise otherwise
        fallback_role = str(getattr(route, "fallback_role", "") or "")
        if not fallback_role or fallback_role == request.role:
            raise last_error
        fallback = self.route_for(fallback_role)
        response = await self._provider_for(fallback).complete(request, fallback)
        response.fell_back_to = fallback.role
        return response


def extract_commands(model_text: str) -> list[str]:
    """Pull shell commands out of a model decision (rehearsal JSON or RUN markers)."""
    try:
        data = json.loads(model_text)
        if isinstance(data, dict) and isinstance(data.get("commands"), list):
            return [str(c) for c in data["commands"]]
    except (json.JSONDecodeError, ValueError):
        pass
    return [m.strip() for m in re.findall(r"^- RUN:\s*(.+)$", model_text, flags=re.MULTILINE)]
