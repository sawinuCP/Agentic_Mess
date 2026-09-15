"""Runtime settings for the control-plane API."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All values are overridable via ``HARNESS_``-prefixed env vars or a local ``.env`` file."""

    model_config = SettingsConfigDict(env_prefix="HARNESS_", env_file=".env", extra="ignore")

    app_name: str = "AI Harness API"
    environment: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"

    # Infrastructure endpoints (docker-compose defaults).
    # Host ports are offset from the standard ones (see docker-compose.yml): Windows dev
    # machines frequently run local PostgreSQL/Redis on 5432/6379, and loopback binds win.
    database_url: str = "postgresql+psycopg://harness:harness@localhost:15432/harness"
    redis_url: str = "redis://localhost:16379/0"
    nats_url: str = "nats://localhost:14222"

    # Readiness probes: PostgreSQL is the durable source of truth and always required;
    # Redis/NATS are optional until their phases, unless policy requires them.
    readiness_timeout_seconds: float = 2.0
    require_redis: bool = False
    require_nats: bool = False

    # Observability (OpenTelemetry) is opt-in until the collector is running.
    otel_enabled: bool = False
    otel_exporter_endpoint: str = "http://localhost:4318/v1/traces"
    otel_service_name: str = "ai-harness-api"

    # Durable execution (Temporal, Phase 2). Opt-in; the compose profile
    # `--profile temporal` provides the server.
    temporal_enabled: bool = False
    temporal_address: str = "localhost:7233"
    temporal_task_queue: str = "ai-harness-tasks"

    # Content-addressed artifact storage root (raw outputs, evidence, files).
    artifacts_dir: str = "./data/artifacts"

    # Agent runtime (Phase 3). The rehearsal model provider is the offline default;
    # point HARNESS_MODELS_CONFIG at a JSON file to route roles at real providers.
    agents_enabled: bool = True
    models_config_path: str = ""
    context_budget_tokens: int = 8000

    # HITL gates fail closed: if no decision arrives within the timeout the action
    # is treated as rejected (spec §25).
    hitl_timeout_seconds: float = 300.0
    hitl_poll_seconds: float = 1.0

    # Session supervision: heartbeats older than this mark a session "lost".
    session_stale_seconds: int = 300

    # Scheduler (Phase 4, FR-011/PERF-003): global cap on concurrently running tasks
    # plus optional per-role caps (JSON string, e.g. '{"implementer": 2, "tester": 1}').
    scheduler_enabled: bool = True
    scheduler_max_concurrency: int = 4
    scheduler_role_limits: str = ""

    # Dynamic spawn policy (FR-007): bounded recursion depth for spawned agents/tasks.
    spawn_max_depth: int = 2

    # Message delivery fan-out (FR-010): NATS JetStream transport is opt-in; the
    # durable `messages` table remains the source of truth either way (spec §14).
    nats_delivery_enabled: bool = False
    nats_delivery_stream: str = "harness-messages"
    nats_delivery_subject_prefix: str = "harness.msg"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton (tests construct Settings directly instead)."""
    return Settings()
