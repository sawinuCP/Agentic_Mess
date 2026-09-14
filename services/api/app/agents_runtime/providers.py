"""Model provider protocol and adapters (spec §32): rehearsal + OpenAI-compatible.

The rehearsal provider is a deterministic offline provider used for development
and tests — it never claims external capability. The OpenAI-compatible adapter
talks to any compliant endpoint (auth/base via HARNESS_OPENAI_* env vars).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Protocol


def estimate_tokens(text: str) -> int:
    """~4 chars per token; good enough for budget accounting (not billing)."""
    return max(1, len(text) // 4)


@dataclass(slots=True)
class ModelRoute:
    role: str
    provider: str
    model: str
    max_output_tokens: int = 2048
    temperature: float = 0.2
    fallback_role: str = ""  # role to escalate to when this provider fails (spec §32)


@dataclass(slots=True)
class ModelRequest:
    role: str
    system: str
    prompt: str
    max_output_tokens: int = 2048


@dataclass(slots=True)
class ModelResponse:
    text: str
    provider: str
    model: str
    prompt_tokens_est: int
    output_tokens_est: int
    fell_back_to: str = ""


class ModelProviderError(Exception):
    pass


class ModelProvider(Protocol):
    async def complete(self, request: ModelRequest, route: ModelRoute) -> ModelResponse: ...


class RehearsalProvider:
    """Deterministic offline provider: reflects RUN-markers from the prompt into a
    scripted JSON decision so the runtime is exercisable without external services."""

    async def complete(self, request: ModelRequest, route: ModelRoute) -> ModelResponse:
        commands = [
            line.strip().removeprefix("- RUN:").strip()
            for line in request.prompt.splitlines()
            if line.strip().startswith("- RUN:")
        ]
        text_out = json.dumps(
            {
                "decision": "run_commands",
                "commands": commands,
                "notes": "rehearsal provider: scripted deterministic decision",
            }
        )
        return ModelResponse(
            text=text_out,
            provider=route.provider,
            model=route.model,
            prompt_tokens_est=estimate_tokens(request.prompt),
            output_tokens_est=estimate_tokens(text_out),
        )


class OpenAICompatibleProvider:
    """Adapter for OpenAI-compatible chat endpoints (GLM/OpenAI/vLLM/...)."""

    def __init__(self, base_url: str | None, api_key: str | None) -> None:
        self._base_url = (base_url or "").rstrip("/")
        self._api_key = api_key or ""

    async def complete(self, request: ModelRequest, route: ModelRoute) -> ModelResponse:
        if not self._base_url or not self._api_key:
            raise ModelProviderError(
                "openai_compatible provider needs HARNESS_OPENAI_BASE_URL and "
                "HARNESS_OPENAI_API_KEY"
            )
        import httpx  # noqa: PLC0415 — imported on use

        payload = {
            "model": route.model,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.prompt},
            ],
            "max_tokens": min(request.max_output_tokens, route.max_output_tokens),
            "temperature": route.temperature,
        }
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                f"{self._base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        text_out = data["choices"][0]["message"]["content"]
        return ModelResponse(
            text=text_out,
            provider=route.provider,
            model=route.model,
            prompt_tokens_est=estimate_tokens(request.prompt),
            output_tokens_est=estimate_tokens(text_out),
        )


_PROVIDERS: dict[str, ModelProvider] = {}


def get_provider(name: str) -> ModelProvider:
    if name not in _PROVIDERS:
        if name == "rehearsal":
            _PROVIDERS[name] = RehearsalProvider()
        elif name == "openai_compatible":
            _PROVIDERS[name] = OpenAICompatibleProvider(
                base_url=os.environ.get("HARNESS_OPENAI_BASE_URL"),
                api_key=os.environ.get("HARNESS_OPENAI_API_KEY"),
            )
        else:
            raise ModelProviderError(f"Unknown model provider: {name!r}")
    return _PROVIDERS[name]
