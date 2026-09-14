"""Context broker budgeting (spec §15) and model registry routing (spec §32)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.agents_runtime.context_broker import assemble
from app.agents_runtime.models_registry import ModelRegistry, extract_commands
from app.agents_runtime.providers import ModelProviderError, ModelRequest


def test_context_assembles_in_tier_order() -> None:
    bundle = assemble(
        safety_text="policy",
        task_text="task details",
        state_text="project state",
        code_text="code excerpt",
        history_text="history",
        evidence_text="evidence",
    )
    assert [s.tier for s in bundle.sections] == [0, 1, 2, 3, 4, 5]
    assert bundle.dropped_tiers == []
    assert "policy" in bundle.render()


def test_context_budget_drops_lowest_priority_first() -> None:
    bundle = assemble(
        safety_text="policy",
        task_text="task details",
        state_text="state",
        code_text="code",
        history_text="history",
        evidence_text="evidence",
        budget_tokens=2,  # only T0 (1 token) fits; everything else is dropped
    )
    assert [s.tier for s in bundle.sections] == [0, 2]  # safety survives; smaller T2 still fits
    assert set(bundle.dropped_tiers) == {1, 3, 4, 5}


def test_registry_default_routes_are_rehearsal() -> None:
    registry = ModelRegistry.load(None)
    route = registry.route_for("worker")
    assert route.provider == "rehearsal"
    fallback = registry.route_for("unknown-role")
    assert fallback.role == "worker"


def test_registry_loads_overrides(tmp_path: Path) -> None:
    config = tmp_path / "models.json"
    config.write_text(
        '{"routes": {"worker": {"provider": "openai_compatible", "model": "glm-5.3-flash"}}}',
        encoding="utf-8",
    )
    registry = ModelRegistry.load(config)
    assert registry.route_for("worker").model == "glm-5.3-flash"


def test_extract_commands_from_rehearsal_json() -> None:
    import json

    text = json.dumps({"decision": "run_commands", "commands": ["pytest -q", "ruff check ."]})
    assert extract_commands(text) == ["pytest -q", "ruff check ."]


def test_extract_commands_from_run_markers() -> None:
    assert extract_commands("- RUN: black .\nother\n- RUN: go test ./...") == [
        "black .",
        "go test ./...",
    ]


def test_unknown_provider_is_rejected(tmp_path: Path) -> None:
    config = tmp_path / "models.json"
    config.write_text(
        '{"routes": {"worker": {"provider": "holodeck", "model": "x"}}}', encoding="utf-8"
    )
    registry = ModelRegistry.load(config)
    with pytest.raises(ModelProviderError):
        asyncio.run(registry.complete(ModelRequest(role="worker", system="s", prompt="p")))
