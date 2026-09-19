# Product Capability Map (Phase B)

Every implemented capability with its implementation home. Status: IMPLEMENTED
unless noted; gaps noted honestly (PARTIAL / ABSENT).

## Project Management — IMPLEMENTED

Project open/list (workspace/projects), root-relative file service, git
integration (status/diff/commit/worktrees), artifact store (content-addressed).
UI: Explorer, editor (Monaco), Settings, Problems views.

## Code Editor / File System — IMPLEMENTED

Monaco (dark+light themes), tabs, diff, dirty guards, search (capped),
symbols, file tree. Backend: `files/service.py`, `files/search.py`.

## Code Intelligence — IMPLEMENTED

Tree-sitter-ish parser, incremental sha-based indexer, hybrid lexical/semantic
retrieval, embeddings (offline hash), SCIP subset. UI: symbol search, related
retrieval in Command Center.

## Requirements / Planning — IMPLEMENTED

Requirements + acceptance criteria, plans with tasks/dependencies (DAG cycle
checks), task CRUD + validated executable payloads. UI: Office oversight,
traceability report, graph.

## Dynamic Agents / Lifecycle — IMPLEMENTED

Per-attempt disposable agents, role-derived capability scopes
(read/write/admin), sessions with heartbeats + supervision, replacement chains
(`replaces_agent_id`), session release endpoint. UI: Team tab, AgentDetail.

## Agent Communication — IMPLEMENTED

Durable messages (request/response/question/broadcast), operator compose with
explicit null-sender attribution, conversation replay, NATS fan-out. UI: Comms
tab. Per-agent realtime delivery to agents: ABSENT by design (agents read via
activities, not subscriptions).

## Task Dependencies — IMPLEMENTED

DAG validation, dependency wait (signal + pre-check + deadline), dependents
signaling, DepMap visualization.

## Context Management — IMPLEMENTED

Tiered broker with budgets, truncate-before-drop compaction (head; tail for
history), per-task/per-agent/per-invocation model budgets. UI: context
inspection in Command Center.

## Tool Gateway — IMPLEMENTED

Allowlist + global deny + HITL approval patterns, capability floors
(`shell`→write, unknown→admin), timeouts, normalized observations, evidence
artifacts, TOOL_STARTED/COMPLETED/FAILED lifecycle events.

## Shell / Runtimes — IMPLEMENTED

Local runner (sanitized env) + Docker backend (no-net, cap-drop, read-only,
PID cap, optional user). Ports allocator (TTL, idempotent), leases with
takeover. UI: terminal (xterm + WS), Runtime view.

## Language Toolchains — IMPLEMENTED

Detection, registry, per-language run/test/format/lint/build, overrides.
UI: Run view, shell status, palette commands.

## Worktrees / Git — IMPLEMENTED

Isolated worktrees, integration queue (merge/conflict→explicit tasks),
snapshots + evidence-preserving rollback, dirty-release guards.

## Browser / MCP / Research — IMPLEMENTED (all opt-in)

Playwright sessions, MCP gateway (allow-listed), web research with DNS-aware
SSRF guard + per-hop redirect validation.

## Recovery — IMPLEMENTED

Deterministic policy core (11 classes + ladders + last-attempt specializations),
Temporal coordinator, 19 activities, budgets/HITL gates, DLQ, idempotency,
chaos-proven (kill-9, NATS/DB loss, races fixed).

## HITL — IMPLEMENTED

Durable requests (pending/approved/rejected/modified/timeout/cancelled),
fail-closed waits, approval cards, notes, lockout. States: approved flows
continue; everything else terminates.

## Verification / Evidence — IMPLEMENTED

Overseer (criterion VERIFIED only with evidence; UNKNOWN default), completion
gate (409 without evidence), artifacts with refs + ranges, traceability map.

## Evaluation — IMPLEMENTED

EVAL-001..010 offline suite (disposable DB, budgets, repeats/FLAKY), failure
triage, orchestration/message metrics, scorecard gates, compare, CLI, CI fast
+ manual full. No evaluator model (deliberate).

## Realtime — IMPLEMENTED

v1 envelope, per-project sequences, NATS bounded stream, gateway fan-out,
SSE with replay/resync, Zustand reducer (dedupe/ordering/incremental),
connection states, metrics, retention (opt-in), DLQ.

## Agent Office / Graph / Timeline / Command Center — IMPLEMENTED

Office (team/timeline/comms/oversight), execution graph (REQ→TASK→deps),
history with replay, AI command center with intent routing. Later-wave scope
 respected: no full-history time travel claims beyond the bounded feed.

## Observability / Cost / Security — IMPLEMENTED

OTel (opt-in), Prometheus metrics, structured correlation logs, per-task/agent
budgets + ledger + cost surfaces, Wave 1 controls (token, SSRF, sandbox,
capabilities, rate limit).

## Persistence / Deployment — IMPLEMENTED

Postgres (sole truth, alembic 0011), Redis (health-only), NATS (transport),
Temporal (opt-in), compose stack, health/readiness depth, runbook + DR docs.

## PARTIAL / ABSENT (documented, not hidden)

* Autonomous planner loop, evaluator model, per-agent pause/resume/stop,
  virtualization, multi-range serving, disk quota, 100k-scale proofs,
  automated backups, alerting stack — see `known-limitations.md`.
