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

- Single shared bearer token; no per-user identity/RBAC yet (SR-13 in the security register).
- No rate limiting / request size caps yet (SR-07).
- SSRF validation is at request time; TOCTOU DNS-rebinding connection pinning is deferred.
- Docker sandbox hardening (`--user`, pids/disk limits) is SR-06, planned next wave.
- Web UI token entry is via `localStorage` (`harness.api_token`); a settings UX is Wave 6+.
