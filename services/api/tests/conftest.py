"""Shared fixtures for the API test suite."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

# Settings that guarantee infrastructure is unreachable by construction (port 9 = discard),
# so unit tests are deterministic and fail fast. Explicit kwargs beat environment variables.
UNREACHABLE_SETTINGS = Settings(
    environment="test",
    database_url="postgresql+psycopg://harness:harness@localhost:9/harness",
    redis_url="redis://localhost:9/0",
    nats_url="nats://localhost:9",
    readiness_timeout_seconds=0.5,
    require_redis=False,
    require_nats=False,
    log_level="INFO",
    otel_enabled=False,
)


@pytest.fixture()
def client() -> Iterator[TestClient]:
    app = create_app(UNREACHABLE_SETTINGS)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def app() -> FastAPI:
    """App wired for integration tests; uses HARNESS_DATABASE_URL or the compose default.

    Temporal is pinned off so the fail-closed execute test is deterministic.
    """
    settings = Settings(
        environment="test",
        readiness_timeout_seconds=2.0,
        require_redis=False,
        require_nats=False,
        log_level="INFO",
        otel_enabled=False,
        temporal_enabled=False,
    )
    return create_app(settings)


@pytest.fixture()
def project(app: FastAPI, tmp_path: Path) -> Iterator[tuple[FastAPI, TestClient, str, Path]]:
    """A registered project rooted at a throwaway directory, plus a live test client."""
    with TestClient(app) as client:
        response = client.post("/api/projects/open", json={"root_path": str(tmp_path)})
        yield app, client, response.json()["id"], tmp_path
