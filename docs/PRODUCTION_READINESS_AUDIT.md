# Production Readiness Audit — AI Harness Code Editor

**Date:** 2026-09-16 · **Baseline:** `53dadf7` (all 10 spec phases delivered, CI green)
**Method:** evidence-based inspection of the implementation (which this audit's author also built — see
§4 self-review caveat) plus targeted runtime probes (grep-level verification of auth/CORS/env handling,
Linux-container test reproduction with a fresh database, live smoke battery).

Per-requirement status lives in `docs/REQUIREMENTS_MATRIX.md`. This audit covers subsystems and
production characteristics; the remediation plan is `docs/PRODUCTION_REMEDIATION_PLAN.md`.

## 1. Repository map (verified)

```
services/api        FastAPI modular monolith (app/main.py factory, lifespan wiring)
  app/api/routes/   thin routers by area: core, workspace, planning, orchestration,
                    intelligence, execution, browser, mcp, research, quality
  app/services/     domain services (framework-free, asyncio.to_thread convention)
  app/db/models/    SQLAlchemy entities (flat registry in __init__)
  app/durable/      Temporal client/workflow/activities/worker
  app/agents_runtime/ lifecycle, providers, models_registry, gateway, observations,
                      context_broker, spawn_policy
  app/messaging/    NATS JetStream adapter (opt-in) + durable messages
  app/browser|mcp|research/   integration adapters (Phase 7)
  app/codeintel/    tree-sitter parser, incremental indexer, hybrid retrieval, SCIP
  app/services/quality/       overseer, review pipeline, gates, secrets, security
  app/services/orchestration/ scheduler, leases, worktrees, agents, hitl, recovery
  app/runtime/      process runner + runtimes.py (local/docker backends)
  app/artifacts/    content-addressed blob store
apps/web-ui         React 18 + Vite + TS + zustand + Monaco; views: explorer, search,
                    git, run, office (team/timeline/oversight), diagnostics dialog
docs/               ARCHITECTURE, REQUIREMENTS_MATRIX, DEVELOPMENT, this audit set
scripts/            live smokes (editor/durable/scheduler/runtime/integrations/
                    oversight/office) + runners; CI: .github/workflows/ci.yml
infra               docker-compose.yml (postgres+pgvector, redis, nats, temporal profile)
```

## 2. Subsystem audit

Legend: **COMPLETE** / **PARTIAL** / **MISSING** / **NEEDS_VALIDATION**, plus risk.

### 2.1 Backend / API surface — PARTIAL (risk: HIGH networked, LOW local)
- FastAPI factory + lifespan; thin routers; framework-free services; DomainError → HTTP
  mapping; request-ID middleware; structured JSON logs; fail-closed readiness.
- **Gaps:** no authentication/authorization on any endpoint (grep-verified: no auth
  middleware, no token checks); no CORS policy configured; no rate limiting; OpenAPI
  fully exposed. The API binds per-process (uvicorn default `127.0.0.1`), which makes the
  local desktop posture acceptable, but nothing *enforces* localhost binding.

### 2.2 Durable core (PostgreSQL + SQLAlchemy + Alembic) — COMPLETE (risk: LOW)
- Spec §29 entities with FKs/indexes/JSONB defaults; migrations 0001–0009; content-
  addressed artifacts on disk; transactions owned by services; idempotent project open.
- **Gaps:** no retention policy for events/artifacts (unbounded growth); no index audit
  under large histories.

### 2.3 Durable execution (Temporal) — COMPLETE (risk: MEDIUM)
- Workflow per task with bounded attempts, evidence artifacts, pause/resume signals,
  checkpoints; worker fail-closed when Temporal disabled; supervision marks stale
  sessions. Verified live (smoke_durable).
- **Gaps:** recovery *decisions* (FR-016) are surfaced on attempts but the workflow does
  not yet *consume* them (e.g., retry-alternate-model); workflow tests run activities
  directly rather than through a real Temporal server in CI.

### 2.4 Messaging (NATS JetStream) — PARTIAL (risk: MEDIUM)
- Durable `messages` table is source of truth; JetStream fan-out with `Nats-Msg-Id`
  dedup; opt-in delivery; fail-loud NullBroker.
- **Gaps:** no DLQ/park for poison messages; no consumer-lag metrics; ordering is
  per-subject only; the UI does not consume the stream (polls REST).

### 2.5 Redis (leases/cache) — COMPLETE (risk: LOW)
- TTL leases with computed expiry, renewal, holder checks, stale-expiry endpoint; Redis
  optional (require_redis flag) with fail-closed readiness.

### 2.6 Agent runtime + tool gateway — PARTIAL (risk: HIGH)
- 14-state lifecycle, sessions with heartbeats, supervision, replacement; gateway with
  per-task allowlists, deny + approval patterns → HITL, timeouts, evidence artifacts,
  normalized observations (never raw logs), per-task token-budget gate.
- **Gaps:** tool permissions are command-pattern based, not capability-based (spec §11
  wants explicit READ_FILE/WRITE_FILE/RUN_* capabilities); env inheritance leaks API
  secrets into agent subprocesses (verified: `runner.run_process` merges `{**os.environ,
  **env_extra}` — the model API key is visible to generated code); no per-agent budget
  or tool-call caps.

### 2.7 Model gateway — PARTIAL (risk: MEDIUM)
- `models_registry` centralizes role → provider/model routing (JSON config, no model
  names in code), bounded fallback escalation; rehearsal provider offline; cost ledger
  per task/agent/model with per-task budget gate.
- **Gaps:** no backoff on transient provider errors (single fallback hop); no per-agent
  or per-execution budgets; provider timeout hard-coded (httpx 120 s), not per-route.

### 2.8 Context engine — COMPLETE (risk: MEDIUM)
- T0–T5 tiered assembly with token budgets (T0 never dropped), hybrid lexical+pgvector
  retrieval (T3), RTK-style observation compression, research evidence as T5.
- **Gaps:** no compaction of very long histories; no relevance measurement; injection
  flags attached but not yet used to down-rank content.

### 2.9 Code intelligence — PARTIAL (risk: MEDIUM)
- tree-sitter + stdlib-ast parsing, hash-driven incremental index, hybrid retrieval,
  SCIP-JSON export; multi-language grammars.
- **Gaps (honest):** LSP daemon, call/dependency graphs, repository map — deferred; no
  semantic or security analysis.

### 2.10 Runtimes / sandbox — PARTIAL (risk: HIGH for untrusted code)
- `local` (trusted) and `docker` backends: workspace-only bind-mount, network-none,
  memory/CPU caps, no-new-privileges; lease-based execution quotas; port allocator with
  bind probe + TTL; verified live.
- **Gaps:** no disk-size or pids limits; containers run as root (no `--user`); docker
  daemon required (fail-closed OK); `local` is the default backend and is trusted.

### 2.11 Git / worktrees — COMPLETE (risk: LOW)
- Worktree create/list/branch-hygiene, active-branch exclusivity, FIFO integration with
  no-ff merges, conflicts → explicit tasks, canonical workspace never dirty, `.harness/`
  in local exclude. Verified in Linux-container reproduction.

### 2.12 Quality / oversight — COMPLETE (risk: LOW)
- Traceability chain, evidence-only verification, fail-closed completion gate with
  blockers/warnings + durable report artifact; 5-role review pipeline persisted;
  credential scanner; security gate. Verified live (smoke_oversight) + Playwright office
  smoke.

### 2.13 Browser / MCP / research — PARTIAL (risk: MEDIUM)
- Playwright sessions with console/network capture + screenshot artifacts; MCP stdio
  client with allowlists/schema validation/audit; research with provenance packets.
- **Gaps:** browser sessions in-process (lost on restart; single-worker assumption);
  research private-host guard **defaults to allowed** (SSRF posture); MCP HTTP
  transports deferred; no per-session network policy for the browser.

### 2.14 Recovery / portability / diagnostics — PARTIAL (risk: LOW-MEDIUM)
- Failure classifier (11 spec §26 classes) + bounded plans wired into attempts;
  restart-recovery proof; diagnostics endpoint + UI dialog (fail-soft); export/import
  bundles with artifact inlining.
- **Gaps:** recovery plan not yet acted on by the workflow; diagnostics sync probes run
  on the event loop briefly.

### 2.15 Observability — PARTIAL (risk: MEDIUM)
- Durable events with request/task/agent correlation; structured logs; OTel opt-in
  skeleton; event API for the UI.
- **Gaps:** no metrics endpoint (Prometheus); no trace propagation into Temporal
  activities; no SSE/WebSocket event streaming (UI polls at 2.5 s); retention absent.

### 2.16 Web UI — PARTIAL (risk: MEDIUM)
- VS Code-style shell: Monaco with tabs/dirty/quick-open, search, git panel,
  run/toolchains, real PTY terminals, office (team/timeline/oversight), HITL approval
  cards, diagnostics dialog, Torph/Typehug interactive typography.
- **Gaps:** polling (no live push); no command palette for *actions* (QuickOpen is
  files-only); production states (offline/reconnecting/partial) incomplete; no list
  virtualization for large feeds; accessibility partial (keyboard for core flows only,
  no reduced-motion support); ad-hoc error toasts.

### 2.17 Packaging / desktop / release — MISSING (documented deferral)
- No Tauri shell (no Rust toolchain; ADR-0008). No SBOM, pip-audit/npm-audit gate, or
  signed artifacts. Install story = clone + compose + uvicorn + vite.

### 2.18 Testing / chaos — PARTIAL (risk: MEDIUM)
- 214 tests: unit + integration across all domains; Linux-container reproduction of the
  CI job; 7 live smokes; Playwright UI smoke.
- **Gaps:** no `tests/chaos/` (kill-worker, infra restarts, stale-lease takeover,
  model-timeout injection, NATS interruption); no E2E benchmark projects; no agent
  evaluation harness; browser test skips honestly when chromium is missing.

## 3. Production checklist (spec §52) — summary

| Area | Status |
|------|--------|
| Architecture: durable state, idempotency, transactions, boundaries | ✅ |
| Reliability: retry/timeout/cancel/recovery/checkpoint/pause-resume | ✅ core / ⚠ recovery plans not consumed |
| Security: sandbox ✅ · secret isolation ⚠ env leak · SSRF ⚠ default-open · auth ❌ | ⚠ |
| Agent system: spawning/replacement/communication/bounded/oversight | ✅ |
| AI: gateway/fallback/budgets/compression/cost | ✅ core / ⚠ backoff, per-agent budgets |
| UI/UX: design system, office, gate | ⚠ action palette + production states missing |
| Performance: virtualization, backpressure, retention | ⚠ |
| Testing: chaos ❌ · E2E benchmarks ❌ · evaluation ❌ | ⚠ |
| Release: packaging/SBOM/signing ❌ | ❌ (deferred, documented) |

## 4. Self-review caveat

This audit was produced by the same engineering process that implemented the system — a
known bias. Mitigations: every claim was re-verified against current code (grep/runtime
probes) or a passing test; the risk registers prefer *demonstrable* gaps (with file
references) over speculation; the Linux-container reproduction of CI exists to catch
what local (Windows) testing cannot.
