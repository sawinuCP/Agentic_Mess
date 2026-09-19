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
    # Worker concurrency (Wave 4 §16): explicit bounds, not SDK defaults.
    # Activities run agent executions — keep this small and deliberate.
    temporal_max_concurrent_workflows: int = 10
    temporal_max_concurrent_activities: int = 4
    temporal_max_activities_per_second: float = 0.0  # 0 = no rate cap

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

    # --- Realtime event streaming (Wave 3) ------------------------------------
    # PostgreSQL remains the authoritative event store; NATS JetStream is the
    # low-latency delivery hop and the SSE gateway is the fan-out. Live delivery
    # is at-most-once: a missed event is recovered by replay/resync from the
    # durable API, never from the bus.
    nats_events_enabled: bool = True
    nats_events_stream: str = "harness-events"
    nats_events_subject_prefix: str = "harness.events"
    # Bounded JetStream retention (the durable history lives in PostgreSQL).
    nats_events_max_age_seconds: int = 86_400
    nats_events_max_msgs: int = 100_000
    nats_events_max_bytes: int = 268_435_456  # 256 MiB
    # Publisher-side bounded queue. Overflow DROPS the live copy (never blocks
    # execution) and is counted in metrics; clients resync from PostgreSQL.
    realtime_publish_queue_size: int = 4096
    realtime_max_payload_bytes: int = 32_768
    # SSE gateway: connection limits, per-client bounded queues, slow-client policy.
    realtime_enabled: bool = True
    realtime_max_connections: int = 50
    realtime_connection_queue_size: int = 256
    realtime_heartbeat_seconds: float = 15.0
    realtime_consumer_name: str = "realtime-gateway"
    realtime_fetch_batch: int = 64
    realtime_fetch_timeout_seconds: float = 1.0
    realtime_max_ack_pending: int = 512
    realtime_max_deliver: int = 3
    realtime_slow_client_max_drops: int = 50
    realtime_replay_page_cap: int = 500

    # --- Retention (Wave 3): bounded, explicit, boring. 0 disables. ----------
    retention_events_days: int = 0  # authoritative audit history: deletion requires explicit opt-in
    retention_artifacts_days: int = 0
    retention_interval_seconds: int = 3600
    retention_batch_size: int = 1000

    # Code intelligence (Phase 5): index caps + context retrieval (T3 tier).
    index_max_files: int = 5000
    index_max_file_bytes: int = 512_000
    context_retrieval_enabled: bool = True
    retrieval_k: int = 6

    # Model budget gates (spec §32 bounded cost): cumulative tokens per task
    # (original gate), plus per-agent tokens and per-task/per-agent invocation
    # counts. A per-task gate also bounds each execution run, because ledger
    # rows are task-scoped across runs. 0 = unlimited for every gate.
    model_budget_tokens_per_task: int = 0
    model_budget_tokens_per_agent: int = 0
    model_budget_invocations_per_task: int = 0
    model_budget_invocations_per_agent: int = 0
    # Model provider resilience (spec §32): attempts per role before the route
    # fallback runs. Transient errors (timeouts, 429/5xx) back off using the
    # recovery_backoff_* policy above; permanent errors fail fast to fallback.
    model_provider_max_attempts: int = 3

    # Execution plane (Phase 6, spec §19): runtime backend + isolation defaults.
    runtime_backend: str = "local"  # local | docker
    docker_image: str = "python:3.11-slim"
    docker_network: str = "none"  # untrusted code gets no network by default (SEC-005)
    docker_memory: str = "512m"
    docker_cpus: str = "1.0"
    # Docker hardening (SEC-005, settings-only — task payloads cannot relax it):
    # PID cap (fork-bomb containment), read-only root fs with a /tmp tmpfs, and
    # an optional explicit "--user uid:gid" (empty = daemon default; set
    # HARNESS_DOCKER_USER to pin a non-root user, verifying workspace writes).
    docker_pids_limit: int = 256
    docker_readonly: bool = True
    docker_user: str = ""
    exec_timeout_cap_seconds: float = 900.0
    exec_max_concurrent_per_project: int = 2

    # Port allocator (spec §19.1): agents request ports; allocations carry a TTL.
    port_range_low: int = 21000
    port_range_high: int = 21999
    port_ttl_seconds: int = 3600

    # Browser debugging (Phase 7, FR-020): Playwright chromium, headless.
    browser_enabled: bool = True
    browser_max_sessions: int = 5

    # MCP gateway (Phase 7, FR-021): opt-in — servers execute arbitrary commands.
    mcp_enabled: bool = False
    mcp_config_path: str = ""
    mcp_timeout_seconds: float = 60.0

    # --- Security (Wave 1) ---------------------------------------------------
    # Per-IP fixed-window rate limit (W1-RATE-1): fail-closed against brute-force
    # and accidental client hot-loops. Public paths (health/docs) and CORS
    # preflight are exempt so probes and browsers never trip the limiter.
    # 0 requests = limiter disabled (in addition to the enabled flag).
    rate_limit_enabled: bool = True
    rate_limit_requests_per_window: int = 600
    rate_limit_window_seconds: float = 60.0
    # API bearer token (HARNESS_API_TOKEN). Empty = auth disabled, which is only
    # acceptable for the local desktop posture (host defaults to loopback and
    # startup refuses non-loopback binding without a token). Never commit a
    # real token; never log or return it.
    api_token: str = ""
    # Server bind host for launchers (uvicorn --host). Non-loopback binding
    # without an API token fails at startup (fail-closed misconfiguration).
    host: str = "127.0.0.1"
    # CORS allow-list (comma-separated origins). No wildcard: browsers talk to
    # the API through the vite dev proxy or these explicit origins.
    cors_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,tauri://localhost,https://tauri.localhost"
    )
    # Extra environment variable names agents may inherit (comma-separated),
    # on top of the built-in safe baseline. Sensitive-named variables are never
    # inherited; scoped secrets go through explicit per-call overrides instead.
    agent_env_allow: str = ""

    # Recovery policy (Wave 2): bounded exponential backoff for transient
    # failures. delay = min(base * factor**(attempt-1), max) with ± jitter.
    recovery_backoff_base_seconds: float = 2.0
    recovery_backoff_factor: float = 2.0
    recovery_backoff_max_seconds: float = 60.0
    recovery_jitter_ratio: float = 0.25
    recovery_dependency_wait_seconds: float = 900.0

    # Web research (Phase 7, FR-022): bounded fetches. Private/internal network
    # destinations are DENIED by default (SSRF posture, spec §31); local research
    # against the dev API opts back in explicitly (tests, smokes).
    research_enabled: bool = True
    research_private_hosts_allowed: bool = False
    research_max_bytes: int = 2_000_000
    research_timeout_seconds: float = 30.0


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton (tests construct Settings directly instead)."""
    return Settings()
