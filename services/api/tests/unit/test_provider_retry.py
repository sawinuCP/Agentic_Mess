"""Model provider retry/backoff behaviour (spec §32 resilience)."""

from __future__ import annotations

import asyncio

import pytest

from app.agents_runtime import providers as providers_module
from app.agents_runtime.models_registry import ModelRegistry
from app.agents_runtime.providers import (
    ModelProviderError,
    ModelRequest,
    ModelResponse,
    ModelRoute,
)

_REQUEST = ModelRequest(role="worker", system="s", prompt="p")


class FlakyProvider:
    """Fails transiently ``failures`` times, then succeeds."""

    def __init__(self, failures: int, *, transient: bool = True) -> None:
        self.failures = failures
        self.transient = transient
        self.calls = 0

    async def complete(self, request: ModelRequest, route: ModelRoute) -> ModelResponse:
        self.calls += 1
        if self.calls <= self.failures:
            raise ModelProviderError("boom", transient=self.transient)
        return ModelResponse(
            text='{"decision": "ok"}',
            provider=route.provider,
            model=route.model,
            prompt_tokens_est=1,
            output_tokens_est=1,
        )


def _routes() -> dict[str, dict[str, object]]:
    return {
        "worker": {"provider": "flaky-test", "model": "x", "fallback_role": "reviewer"},
        "reviewer": {"provider": "rehearsal", "model": "rehearsal-reviewer"},
    }


def _registry(
    flaky: FlakyProvider,
    monkeypatch: pytest.MonkeyPatch,
    **kwargs: object,
) -> tuple[ModelRegistry, list[float]]:
    monkeypatch.setitem(providers_module._PROVIDERS, "flaky-test", flaky)
    sleeps: list[float] = []

    async def record(delay: float) -> None:
        sleeps.append(delay)

    return (
        ModelRegistry(
            _routes(),
            sleep=record,
            backoff_base_seconds=2.0,
            backoff_factor=2.0,
            backoff_max_seconds=60.0,
            backoff_jitter_ratio=0.25,
            **kwargs,  # type: ignore[arg-type]
        ),
        sleeps,
    )


def test_transient_failure_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    flaky = FlakyProvider(failures=2)
    registry, sleeps = _registry(flaky, monkeypatch)
    response = asyncio.run(registry.complete(_REQUEST))
    assert response.text == '{"decision": "ok"}'
    assert flaky.calls == 3
    assert len(sleeps) == 2
    # Exponential backoff with ±25% jitter: 2.0s then 4.0s nominal.
    assert 1.5 <= sleeps[0] <= 2.5
    assert 3.0 <= sleeps[1] <= 5.0


def test_permanent_failure_skips_retry_goes_to_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flaky = FlakyProvider(failures=99, transient=False)
    registry, sleeps = _registry(flaky, monkeypatch)
    response = asyncio.run(registry.complete(_REQUEST))
    assert response.fell_back_to == "reviewer"
    assert flaky.calls == 1
    assert sleeps == []


def test_exhausted_retries_escalate_to_fallback_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flaky = FlakyProvider(failures=99)
    registry, sleeps = _registry(flaky, monkeypatch, max_attempts=3)
    response = asyncio.run(registry.complete(_REQUEST))
    assert response.fell_back_to == "reviewer"
    assert flaky.calls == 3
    assert len(sleeps) == 2


def test_exhausted_retries_without_fallback_raises_last_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flaky = FlakyProvider(failures=99)
    monkeypatch.setitem(providers_module._PROVIDERS, "flaky-test", flaky)
    sleeps: list[float] = []

    async def record(delay: float) -> None:
        sleeps.append(delay)

    registry = ModelRegistry(
        {"worker": {"provider": "flaky-test", "model": "x"}},
        sleep=record,
        backoff_base_seconds=0.01,
        backoff_jitter_ratio=0.0,
    )
    with pytest.raises(ModelProviderError, match="boom"):
        asyncio.run(registry.complete(_REQUEST))
    assert flaky.calls == 3  # default max_attempts
    assert len(sleeps) == 2


def test_unknown_provider_fails_fast_without_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []

    async def record(delay: float) -> None:
        sleeps.append(delay)

    registry = ModelRegistry(
        {"worker": {"provider": "holodeck", "model": "x"}},
        sleep=record,
    )
    with pytest.raises(ModelProviderError):
        asyncio.run(registry.complete(_REQUEST))
    assert sleeps == []


def test_per_route_timeout_seconds_from_config() -> None:
    registry = ModelRegistry(
        {"worker": {"provider": "rehearsal", "model": "x", "timeout_seconds": 7.5}}
    )
    assert registry.route_for("worker").timeout_seconds == 7.5
    assert ModelRegistry.load(None).route_for("worker").timeout_seconds == 120.0


def test_openai_adapter_uses_route_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    from app.agents_runtime.providers import ModelRoute, OpenAICompatibleProvider

    seen: dict[str, object] = {}

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"choices": [{"message": {"content": "hi"}}]}

    class _FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            seen.update(kwargs)

        async def __aenter__(self) -> _FakeClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(self, *args: object, **kwargs: object) -> _FakeResponse:
            return _FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
    provider = OpenAICompatibleProvider(base_url="http://x", api_key="k")
    route = ModelRoute(role="worker", provider="openai_compatible", model="m", timeout_seconds=9.0)
    response = asyncio.run(
        provider.complete(ModelRequest(role="worker", system="s", prompt="p"), route)
    )
    assert response.text == "hi"
    assert seen.get("timeout") == 9.0
