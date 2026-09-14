"""Model registry and role routing (spec §32): roles → provider/model/budgets.

Configuration-driven — no model names in code. Routes come from a JSON file
(``HARNESS_MODELS_CONFIG``) merged over builtin defaults, keyed by role.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from app.agents_runtime.providers import (
    ModelProviderError,
    ModelRequest,
    ModelResponse,
    ModelRoute,
    get_provider,
)

logger = logging.getLogger("harness.models")

DEFAULT_ROUTES: dict[str, dict[str, Any]] = {
    role: {"provider": "rehearsal", "model": f"rehearsal-{role}", "max_output_tokens": 2048}
    for role in ("worker", "planner", "reviewer", "adjudicator", "supervisor", "security")
}


class ModelRegistry:
    """Loads role routes from JSON (or builtin defaults) and dispatches completions."""

    def __init__(self, routes: dict[str, dict[str, Any]]) -> None:
        self._routes = {role: self._route(role, spec) for role, spec in routes.items()}

    @staticmethod
    def _route(role: str, spec: dict[str, Any]) -> ModelRoute:
        from app.agents_runtime.providers import ModelRoute  # noqa: PLC0415

        return ModelRoute(
            role=role,
            provider=str(spec.get("provider", "rehearsal")),
            model=str(spec.get("model", f"rehearsal-{role}")),
            max_output_tokens=int(spec.get("max_output_tokens", 2048)),
            temperature=float(spec.get("temperature", 0.2)),
        )

    @classmethod
    def load(cls, config_path: Path | None) -> ModelRegistry:
        if config_path and Path(config_path).is_file():
            data = json.loads(Path(config_path).read_text(encoding="utf-8"))
            routes = {**DEFAULT_ROUTES, **data.get("routes", {})}
            logger.info("model registry loaded from %s", config_path)
            return cls(routes)
        return cls(dict(DEFAULT_ROUTES))

    def route_for(self, role: str) -> ModelRoute:
        route = self._routes.get(role) or self._routes.get("worker")
        if route is None:
            raise ModelProviderError(f"No model route for role {role!r}")
        return route

    async def complete(self, request: ModelRequest) -> ModelResponse:
        route = self.route_for(request.role)
        return await get_provider(route.provider).complete(request, route)


def extract_commands(model_text: str) -> list[str]:
    """Pull shell commands out of a model decision (rehearsal JSON or RUN markers)."""
    try:
        data = json.loads(model_text)
        if isinstance(data, dict) and isinstance(data.get("commands"), list):
            return [str(c) for c in data["commands"]]
    except (json.JSONDecodeError, ValueError):
        pass
    return [m.strip() for m in re.findall(r"^- RUN:\s*(.+)$", model_text, flags=re.MULTILINE)]
