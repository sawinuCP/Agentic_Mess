"""Settings parsing behaviour."""

from __future__ import annotations

import os

import pytest

from app.core.config import Settings


@pytest.fixture()
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove any HARNESS_ variables so defaults are deterministic."""
    for key in list(os.environ):
        if key.startswith("HARNESS_"):
            monkeypatch.delenv(key, raising=False)


def test_defaults(clean_env: None) -> None:
    settings = Settings(_env_file=None)
    assert settings.environment == "dev"
    assert settings.database_url.startswith("postgresql+psycopg://")
    assert ":15432/" in settings.database_url  # conflict-free Windows default
    assert settings.redis_url == "redis://localhost:16379/0"
    assert settings.nats_url == "nats://localhost:14222"
    assert settings.otel_enabled is False
    # Wave 4 §16: worker concurrency is explicit, never SDK-default.
    assert settings.temporal_max_concurrent_workflows == 10
    assert settings.temporal_max_concurrent_activities == 4
    assert settings.temporal_max_activities_per_second == 0.0


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARNESS_DATABASE_URL", "postgresql+psycopg://u:p@db.example:5432/x")
    settings = Settings(_env_file=None)
    assert settings.database_url == "postgresql+psycopg://u:p@db.example:5432/x"


def test_foreign_vars_do_not_leak_into_namespaced_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://should:be@ignored/x")
    settings = Settings(_env_file=None)
    assert settings.database_url != "postgresql+psycopg://should:be@ignored/x"
