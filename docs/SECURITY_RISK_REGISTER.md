# Security Risk Register

Threat model: a local-first desktop application whose backend executes **arbitrary
agent-generated code** and drives tools (shell, browser, MCP, network). Posture assumes
the API is reachable from the local machine; anything beyond that raises severity.

| ID | Risk | Severity | Evidence | Mitigation | Status |
|----|------|----------|----------|------------|--------|
| SR-01 | **No authentication/authorization** on any API endpoint or WebSocket — any local process (or LAN peer if bound wider) can read/write projects, run commands, decide HITL | CRITICAL (networked) / MEDIUM (localhost-only) | Grep-verified: only RequestIDMiddleware; no token checks anywhere | W1-AUTH-1 optional bearer token + default 127.0.0.1 binding + explicit override warning; WS handshake check | OPEN |
| SR-02 | **Environment inheritance leaks secrets to agent subprocesses** — `runner.run_process` merges `os.environ`; `HARNESS_OPENAI_API_KEY` (and any host secret) is readable by generated code via `env` | CRITICAL | Verified `runner.py` `{**os.environ, **env_extra}` | W1-SECRET-1 deny-by-default env sanitizer with allow-list | OPEN |
| SR-03 | **SSRF via research/browser/MCP** — fetch guard checks hostnames but defaults to allowing private hosts; no DNS-resolution check (rebinding bypass), no metadata-IP block | HIGH | `research/service.py` `_guard_url` (string checks only; `research_private_hosts_allowed=true` default) | W1-SSRF-1 resolve+block private/link-local/metadata ranges on final targets | OPEN |
| SR-04 | **Terminal WebSocket + browser/MCP endpoints unauthenticated** — full host PTY reachable from any allowed origin | HIGH (networked) | `routes/workspace/terminal.py` (no auth) | Same token gate as SR-01 incl. WS handshake | OPEN |
| SR-05 | **Prompt injection** — tool outputs are compressed but injection attempts are only flagged, not down-ranked or blocked | MEDIUM | `observations.py` security_flags; `quality/security.py` | Flag-aware context ranking; system-prompt hardening; test corpus | PARTIAL |
| SR-06 | **Sandbox gaps** — docker containers run as root; no pids/disk limits; local backend is trusted-by-design but is default | HIGH (untrusted code) | `runtime/runtimes.py` | `--user`, `--pids-limit`, `--storage-opt`; document local-backend trust boundary | OPEN |
| SR-07 | **No rate limiting / request size caps** on mutating endpoints | MEDIUM | No middleware present | W1-RATE-1 token bucket | OPEN |
| SR-08 | **CORS unset** — currently same-origin via proxy; a networked deployment would default to permissive browser behavior | MEDIUM | No CORSMiddleware configured | W1-CORS-1 explicit allow-list | OPEN |
| SR-09 | **Log/artifact leakage** — redaction filter covers log messages; exception tracebacks and artifact *content* are not scanned | MEDIUM | `core/logging.py` redacts msg/args only | Extend formatter to exc text; artifact scan on store | PARTIAL |
| SR-10 | **Supply chain** — no pip-audit/npm-audit/SBOM gate in CI; deps pinned loosely (`^`) | MEDIUM | CI workflow lacks audit steps | Audit jobs + lockfile policy (Wave 8) | OPEN |
| SR-11 | **Path traversal** — files service enforces root-relative resolution (verified by tests); worktree/ports validated | LOW (residual) | `files/service.py` path safety + tests | Keep regression tests | MITIGATED |
| SR-12 | **Command injection** — argv-list subprocess only, never a shell; git ops argv-based | LOW (residual) | `runtime/runner.py`, `gitops/client.py` | Keep argv-only invariant (lint note) | MITIGATED |
| SR-13 | **MCP servers execute arbitrary commands** — gated behind opt-in flag + per-server allowlists + policy patterns | MEDIUM (residual) | `mcp/registry.py` (allowlist) + route 503 default | Keep fail-closed default; add per-tool scopes | MITIGATED (partial) |

Resolved during earlier phases and kept as regression tests: command-injection posture
(argv-list), path traversal (files service), prompt-injection *detection* (Phase 10),
credential scanning, secret-free observations (FR-023).
