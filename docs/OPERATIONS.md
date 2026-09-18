# Operations Runbook

Operator-facing guide for running and configuring the AI Harness control plane safely.
Developer setup lives in the root `DEVELOPMENT.md`; this page focuses on deployment
posture, security configuration, and day-2 operations.

## 1. Running the stack

```bash
# Infrastructure (postgres+pgvector, redis, nats; temporal under the `temporal` profile)
docker compose up -d

# API (from repo root venv)
.venv\Scripts\uvicorn app.main:app --host 127.0.0.1 --port 8000   # services/api is the app dir

# Web UI
cd apps/web-ui && npm run dev
```

Health: `GET /healthz` (liveness, always open) · `GET /readyz` (readiness, fail-closed 503 with
component detail) · `GET /api/diagnostics` (support bundle, fail-soft per component).

## 2. Security configuration (Wave 1)

### 2.1 Authentication — `HARNESS_API_TOKEN`

| Mode | Configuration | Behavior |
|------|---------------|----------|
| Local desktop (default) | `HARNESS_API_TOKEN` empty **and** `HARNESS_HOST=127.0.0.1` | Auth disabled; every request from the local machine is trusted. This is the intended posture for the desktop app. |
| Networked / token mode | `HARNESS_API_TOKEN=<secret>` | Every `/api/*` HTTP request requires `Authorization: Bearer <token>`; every WebSocket handshake requires the token via the `Authorization` header or a `bearer.<token>` WebSocket subprotocol (browsers cannot set WS headers). Rejections: HTTP 401 (`WWW-Authenticate: Bearer`), WS close code `4401`. |

Rules enforced by the application:

- **Fail-closed startup**: a non-loopback `HARNESS_HOST` with an empty token raises
  `RuntimeError` at startup — a networked bind without authentication is a
  misconfiguration, not a warning.
- **Public paths** (no token required): `/healthz`, `/readyz`, `/docs`, `/redoc`,
  `/openapi.json`; CORS `OPTIONS` preflights are answered unauthenticated.
- **Secret hygiene**: the token is compared in constant time, never logged, never echoed
  back in a response, never returned by `/api/diagnostics`, and never exposed to agent
  subprocesses (see 2.4). Provide it via environment/secret store — never commit it.

### 2.2 Host binding — `HARNESS_HOST`

`uvicorn --host $(HARNESS_HOST)`; default `127.0.0.1`. Local-only mode stays local-only
unless an operator explicitly binds wider AND sets a token. Document the implication for
your deployment: binding `0.0.0.0` exposes project files, terminals, and code execution
to the network (mitigated only by the bearer token — put the API behind a VPN/reverse
proxy with TLS for real networked use).

### 2.3 CORS — `HARNESS_CORS_ORIGINS`

Comma-separated explicit origin allow-list. Defaults cover the vite dev server
(`http://localhost:5173`, `http://127.0.0.1:5173`) and Tauri origins
(`tauri://localhost`, `https://tauri.localhost`). No wildcard; `allow_credentials=false`
(the API uses bearer tokens, not cookies); `Authorization`/`Content-Type`/`X-Request-ID`
are the permitted request headers. Unknown origins get no `Access-Control-Allow-Origin`.

### 2.4 Agent environment policy — `HARNESS_AGENT_ENV_ALLOW`

Agent/tool subprocesses are started with a **sanitized environment** (default deny):

- Built-in baseline only: `PATH`, `HOME`/`USERPROFILE`/`HOMEDRIVE`/`HOMEPATH`, `TEMP`/`TMP`,
  Windows system vars (`SystemRoot`, `ComSpec`, `PATHEXT`, …), locale/TZ/TERM.
- `HARNESS_AGENT_ENV_ALLOW` adds extra variable names (comma-separated), e.g. toolchain
  configuration like `PIP_INDEX_URL`, `CARGO_HOME`.
- **Credential-shaped names are never inherited**, even if allow-listed (deny wins):
  names containing `TOKEN`/`SECRET`/`PASSWORD`/`CREDENTIAL`/`KEY`, or prefixed
  `AWS_`/`OPENAI_`/`ANTHROPIC_`/`GOOGLE_`/`AZURE_`/`GCP_`/`HCLOUD_`.
- A tool that genuinely needs a secret receives it via an explicit per-call
  `env_extra` override in tool/run code — the only sanctioned path, auditable at the
  call site. Never place secrets in the allow-list.

### 2.5 SSRF policy — `HARNESS_RESEARCH_PRIVATE_HOSTS_ALLOWED`

Web fetches (research evidence packets) validate scheme, hostname, and **all DNS-resolved
addresses** (IPv4/IPv6, v4-mapped, loopback, private, link-local, multicast, unspecified,
reserved; unresolvable hosts are denied), and re-validate **every redirect hop** — a
public URL that redirects into loopback/metadata is blocked before the hop.

- Default `false`: private/loopback destinations are denied (`403`, `SSRF_BLOCKED` warning
  logged with the host only).
- Set `true` only for local development against localhost test servers; it disables the
  resolved-IP layer for that deployment, not for agents' other tools.

### 2.6 Security observability

Structured log events (JSON, request-ID correlated): `AUTHENTICATION_FAILED`,
`SSRF_BLOCKED` (`ip_literal` / `hostname` / `resolved_private` / `unresolvable`).
None of them ever contain token or secret values.

### 2.7 Rate limiting — `HARNESS_RATE_LIMIT_*`

Per-IP fixed-window buckets (`RateLimitMiddleware`): `HARNESS_RATE_LIMIT_ENABLED`
(default true), `HARNESS_RATE_LIMIT_REQUESTS_PER_WINDOW` (default 600),
`HARNESS_RATE_LIMIT_WINDOW_SECONDS` (default 60). Over-limit responses are 429
JSON with a `Retry-After` header and still carry `X-Request-ID`. Public paths
(`/healthz`, `/readyz`, docs) and CORS preflight are exempt so probes and
browsers never trip the limiter. Buckets are in-memory per process — correct for
the single-process deployment below, not for multi-replica.

### 2.8 Agent capability scopes

Tool execution additionally requires a capability scope (`read < write < admin`).
`shell` requires `write`; unknown tools require `admin` (deny-by-default).
Agents are granted scopes at creation from their role: `reviewer`, `critic`,
`security`, `evidence_verifier` get `read` (observe-only — a reviewer task that
reaches execution fails closed); all other roles get `read`+`write`. `admin` is
never granted by default. Unknown scope strings are rejected fail-closed.

## 3. Verification

```bash
# Backend gates (services/api)
python -m ruff format . && python -m ruff check . && python -m mypy app && python -m pytest -q

# Security regression coverage
python -m pytest -q tests/unit/test_wave1_security.py tests/integration/test_wave1_auth.py

# Live smokes (repo root): editor, durable, scheduler, runtime, integrations, oversight, office
powershell -ExecutionPolicy Bypass -File scripts/run-all-smokes.ps1
```

## 4. Known limitations (post-Wave 1)

- Single shared bearer token; no per-user identity/RBAC yet (SR-13/SR-14 in the security register).
- Rate limiting is per-process memory (SR-07 residual); no request-size caps.
- SSRF validation is at request time; TOCTOU DNS-rebinding connection pinning is deferred.
- Docker `--user` defaults to unset (SR-06 residual); pin `HARNESS_DOCKER_USER` where workspace writes allow. No disk quota.
- Web UI token entry is via `localStorage` (`harness.api_token`); a settings UX is Wave 6+.

## 5. Single-process deployment (production posture)

The control plane is one API process plus managed infrastructure — no replica
coordination exists, and the following depend on it:

- **PostgreSQL is the sole source of truth** (durable state, ledger, queues).
  Redis holds leases only; NATS is transport only (live fan-out), never authority;
  Temporal is opt-in (`HARNESS_TEMPORAL_ENABLED`).
- **In-memory state is per-process**: rate-limit buckets, SSE connection registry.
  Do not run two API processes against one database (double delivery, split buckets).
- **Migrations**: `alembic upgrade head` from `services/api` against
  `HARNESS_DATABASE_URL` (live schema head: `0011` — port/worktree idempotency keys).
- **Bounded cost**: `HARNESS_MODEL_BUDGET_TOKENS_PER_TASK`,
  `HARNESS_MODEL_BUDGET_TOKENS_PER_AGENT`,
  `HARNESS_MODEL_BUDGET_INVOCATIONS_PER_TASK`,
  `HARNESS_MODEL_BUDGET_INVOCATIONS_PER_AGENT` (0 = unlimited); exhausted budgets
  stop the attempt with `BUDGET_EXCEEDED` (non-retryable) and a
  `MODEL_BUDGET_EXCEEDED` event carrying the scope.
- **Provider resilience**: `HARNESS_MODEL_PROVIDER_MAX_ATTEMPTS` (default 3);
  transient errors (timeouts, 429/5xx) back off on the `HARNESS_RECOVERY_BACKOFF_*`
  policy, then escalate once via the route `fallback_role`. Per-route
  `timeout_seconds` lives in the models config.
- **Idempotent creates**: port allocate and worktree create accept
  `idempotency_key` (client-generated per logical operation); replays return the
  live row (worktree replay answers HTTP 200).
- **Task lists are paginated** (`limit` 1–500 default 100, `offset` default 0;
  stable order priority/created_at/id). EXPLAIN on the hot query shows an index
  scan on `ix_tasks_project_status` (~0.4 ms); related rows are scoped to the page.
- **Dead letters**: undecodable or exhaustively-crashing realtime messages are
  retained verbatim on `<prefix>.dlq` (same stream subjects) and counted as
  `dead_lettered`; nothing redelivers forever.
- **Recovery ladder**: `retry_policy.max_attempts` on the task (clamped 1–10);
  final-attempt specializations (`replace_agent`, `spawn_debugger`,
  `request_hitl`); backoff on `HARNESS_RECOVERY_BACKOFF_*`; budget-sensitive
  actions gate on the cost ledger then the durable HITL gate
  (`HARNESS_HITL_TIMEOUT_SECONDS`, fail-closed; requests cancellable via
  `POST .../hitl/{id}/cancel`); dependency waits park on a durable signal
  with a pre-check for already-finished deps. Rollback: per-attempt HEAD
  snapshots with evidence-preserving restore (`recovery/*` branches) on the
  merge-conflict path; untracked files are never deleted.
- **NATS endpoints**: prefer `127.0.0.1` over `localhost` in `HARNESS_NATS_URL` —
  on hosts where IPv6 `::1` blackholes instead of refusing, clients can hang
  past their own timeouts (observed with nats-py; the broker additionally caps
  connects with `asyncio.wait_for` on the readiness timeout).

## 6. Diagnostics

`GET /api/diagnostics` is fail-soft (never fails): per-component `ok`/`down`
plus detail, with sync probes run off the event loop under the readiness
timeout. It is safe to curl during incidents; `/readyz` remains the fail-closed
gate.
