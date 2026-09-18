"""Offline evaluation subprocess recorder. No raw logs or exception text in reports."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

_records: list[dict[str, Any]] = []
_collection_errors = 0
_metrics: dict[str, Any] = {
    "model_call_count": 0,
    "input_tokens": 0,
    "output_tokens": 0,
    "estimated_cost_usd": 0.0,
    "tool_call_count": 0,
    "tool_failure_count": None,
    "context_retrieval_count": None,
    "context_tokens": None,
    "provider_failure_count": 0,
}
_provider_routes: set[tuple[str, str]] = set()
_call_limit = int(os.environ.get("HARNESS_EVAL_MODEL_LIMIT", "100"))


@pytest.fixture(autouse=True)
def offline_only(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.agents_runtime import gateway
    from app.agents_runtime.models_registry import ModelRegistry
    from app.agents_runtime.providers import OpenAICompatibleProvider

    async def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("External provider calls forbidden in offline evaluation")

    monkeypatch.setattr(OpenAICompatibleProvider, "complete", forbidden)
    original_provider = ModelRegistry._provider_for

    class MeasuredProvider:
        def __init__(self, provider: Any) -> None:
            self.provider = provider

        async def complete(self, request: Any, route: Any) -> Any:
            # Wrap the provider boundary, not registry.complete: fallback counts too.
            if _metrics["model_call_count"] >= _call_limit:
                _metrics["budget_exhausted"] = True
                pytest.fail("Evaluation model-call budget exhausted")
            _metrics["model_call_count"] += 1
            _provider_routes.add((route.provider, route.model))
            try:
                response = await self.provider.complete(request, route)
            except Exception:
                _metrics["provider_failure_count"] += 1
                raise
            _metrics["input_tokens"] += response.prompt_tokens_est
            _metrics["output_tokens"] += response.output_tokens_est
            return response

    def measured_provider(self: Any, route: Any) -> MeasuredProvider:
        return MeasuredProvider(original_provider(self, route))

    monkeypatch.setattr(ModelRegistry, "_provider_for", measured_provider)
    # Patch the policy boundary, including already-imported invoke aliases.
    original_policy = gateway.check_policy

    def measured_policy(*args: Any, **kwargs: Any) -> Any:
        _metrics["tool_call_count"] += 1
        return original_policy(*args, **kwargs)

    monkeypatch.setattr(gateway, "check_policy", measured_policy)


def pytest_runtest_logreport(report: Any) -> None:
    if len(_records) >= 2000:
        raise RuntimeError("Evaluation record limit reached")
    _records.append(
        {
            "node": report.nodeid,
            "phase": report.when,
            "outcome": report.outcome,
            "duration_seconds": report.duration,
        }
    )


def pytest_collectreport(report: Any) -> None:
    global _collection_errors
    if report.failed:
        _collection_errors += 1


def pytest_sessionfinish(session: Any, exitstatus: int) -> None:
    target = os.environ.get("HARNESS_EVAL_RESULT")
    if target:
        Path(target).write_text(
            json.dumps(
                {
                    "exit_code": int(exitstatus),
                    "collection_errors": _collection_errors,
                    "records": _records,
                    "metrics": _metrics,
                    "model_routes": sorted(_provider_routes),
                }
            ),
            encoding="utf-8",
        )
