# Requirements Matrix

Traceability from specification requirements to subsystems, implementation status, files, tests,
dependencies and risk. Requirement IDs are permanent keys (ADR-0007) — they are reused later by
the Requirement Overseer (Phase 8) for machine-checked coverage.

**Status values:** `NOT_STARTED` · `IN_PROGRESS` · `IMPLEMENTED` (code exists, tests pass) ·
`VERIFIED` (evidence-backed per spec §23) · `BLOCKED` (with reason).

**Risk:** L = low, M = medium, H = high.

## Functional requirements (spec §6)

| ID | Requirement | Subsystem | Phase | Status | Files | Tests | Depends | Risk |
|----|-------------|-----------|-------|--------|-------|-------|---------|------|
| FR-001 | Open/create/clone/manage local projects | workspace-manager (API) | 1 | IN_PROGRESS | services/api/app/api/routes/projects.py, app/files/ | tests/unit/test_files_service.py, tests/integration/test_projects_api.py | FR-029 | M |
| FR-002 | Arbitrary languages via configurable toolchains | language-adapters, registry | 1 | IN_PROGRESS | services/api/app/toolchains/registry.py | tests/unit/test_toolchains.py | FR-004 | H |
| FR-003 | Detect project languages/build systems | language-adapters | 1 | IMPLEMENTED | services/api/app/toolchains/detection.py | tests/unit/test_toolchains.py | FR-002 | M |
| FR-004 | Configure compilers/interpreters/formatters/linters/test runners/debuggers/package managers/LSP | toolchain registry | 1 | IN_PROGRESS | app/toolchains/registry.py, app/toolchains/overrides.py | tests/unit/test_toolchains.py | — | M |
| FR-005 | Accept NL requirements + desired outcomes | requirement-engine | 2 | IN_PROGRESS | services/api/app/api/routes/requirements.py | tests/integration/test_durable_core_api.py | FR-006 | M |
| FR-006 | Decompose requirements into durable tasks | planner/orchestrator | 2 | IMPLEMENTED | app/api/routes/plans.py, app/tasks/graph.py, app/durable/ | tests/integration/test_durable_core_api.py | FR-005 | H |
| FR-007 | Dynamically spawn agents per task needs | orchestrator | 4 | IMPLEMENTED | app/agents_runtime/spawn_policy.py, app/services/scheduler.py, app/durable/activities.py | tests/unit/test_spawn_policy.py, tests/integration/test_phase4_orchestration.py, scripts/smoke_scheduler.py | FR-006 | H |
| FR-008 | Agents disposable/replaceable, task identity preserved | agent-runtime, db | 3 | IMPLEMENTED | app/db/models/agents.py, app/agents_runtime/lifecycle.py, app/durable/ | tests/unit/test_agent_lifecycle.py, tests/integration/test_durable_activities.py | FR-006 | H |
| FR-009 | Multiple concurrent instances of same role | scheduler | 4 | IMPLEMENTED | app/services/scheduler.py (role caps + shared global pool) | tests/integration/test_phase4_orchestration.py | FR-008 | M |
| FR-010 | Async durable structured inter-agent messaging | messaging (NATS+PG) | 4 | IMPLEMENTED | app/db/models/messages.py, app/messaging/broker.py, app/services/messages.py, app/api/routes/messages.py | tests/unit/test_messaging_broker.py, tests/integration/test_phase4_orchestration.py | FR-006 | M |
| FR-011 | Configurable concurrency/resource limits | scheduler | 4 | IMPLEMENTED | app/services/scheduler.py (global + per-role caps), app/services/leases.py | tests/integration/test_phase4_orchestration.py | FR-011-b | M |
| FR-012 | Isolated workspaces/worktrees for conflicting work | integration-manager | 4 | IMPLEMENTED | app/services/worktrees.py, app/api/routes/worktrees.py, app/gitops/client.py | tests/integration/test_worktrees.py | FR-001 | M |
| FR-013 | Requirement→task→code→test traceability | requirement-engine, db | 2/8 | NOT_STARTED | — | — | FR-006 | H |
| FR-014 | HITL approvals/interventions at any phase | hitl + UI | 3/9 | IMPLEMENTED (API+gates; UI in Phase 9) | app/services/hitl.py, app/api/routes/hitl.py, app/durable/activities.py (gate) | tests/integration/test_phase3_runtime.py | — | M |
| FR-015 | Pause/resume without destroying durable state | agent-runtime, temporal | 3 | IMPLEMENTED | app/durable/workflows.py (signals+checkpoints) | scripts/smoke_durable.py (live) | FR-008 | H |
| FR-016 | Classify failures, bounded recovery | recovery-manager | 3 | NOT_STARTED | — | — | FR-008 | H |
| FR-017 | Independent validation of high-risk decisions | review/debate | 8 | NOT_STARTED | — | — | FR-013 | M |
| FR-018 | Execute code in isolated runtimes | runtime-manager | 6 | IMPLEMENTED | app/runtime/runtimes.py (local + docker backends), app/agents_runtime/gateway.py | tests/unit/test_runtime_manager.py, scripts/smoke_runtime.py | — | H |
| FR-019 | Compiler/interpreter + formatter as first-class tools | toolchain adapters | 1/6 | IMPLEMENTED | app/toolchains/service.py, app/runtime/runner.py | tests/unit/test_toolchains.py, tests/unit/test_runner.py | FR-004 | M |
| FR-020 | Browser-based debugging for web apps | playwright worker | 7 | IMPLEMENTED | app/browser/session.py, app/browser/manager.py, routes/browser | tests/integration/test_browser.py, scripts/smoke_integrations.py | FR-018 | M |
| FR-021 | MCP discovery/invocation/permissions | mcp gateway | 7 | IMPLEMENTED | app/mcp/protocol.py, app/mcp/registry.py, routes/mcp | tests/integration/test_mcp_gateway.py, tests/unit/test_mcp_registry.py | SEC-001 | M |
| FR-022 | Web research with evidence/provenance | researcher + evidence | 7 | IMPLEMENTED | app/research/service.py, routes/research | tests/integration/test_research.py, scripts/smoke_integrations.py | — | L |
| FR-023 | Normalize/compress tool observations pre-context | context-engine | 3 | IMPLEMENTED | app/agents_runtime/observations.py, app/agents_runtime/gateway.py | tests/unit/test_agent_gateway.py | — | H |
| FR-024 | Persist events/artifacts/audit info | events, artifacts, db | 0/2 | IMPLEMENTED | app/db/models/events.py, app/services/events.py, app/artifacts/store.py | tests/integration/test_db_smoke.py, tests/integration/test_durable_core_api.py | — | L |
| FR-025 | Engineering-office UI for live agent activity | web-ui | 9 | NOT_STARTED | — | — | FR-024 | M |
| FR-026 | No completion from agent self-report alone | requirement-overseer | 8 | NOT_STARTED | — | — | FR-013 | H |
| FR-027 | Final evidence-backed completion report | overseer + UI | 8/9 | NOT_STARTED | — | — | FR-026 | M |
| FR-028 | Editor usable for conventional workflows without AI | editor | 1 | IMPLEMENTED | apps/web-ui/src/ | scripts/smoke_editor.py (live) | — | M |
| FR-029 | Project-level config, no hard-coded framework | config, toolchain registry | 1 | IMPLEMENTED | app/toolchains/overrides.py | tests/unit/test_toolchains.py | — | L |
| FR-030 | Security boundaries independent of model instructions | policy engine, gateway | 3+ | IN_PROGRESS | app/agents_runtime/gateway.py (deny/allow/approval outside model) | tests/unit/test_agent_gateway.py | — | H |

## Language/toolchain rules (spec §8)

| ID | Requirement | Subsystem | Phase | Status | Files | Tests | Depends | Risk |
|----|-------------|-----------|-------|--------|-------|-------|---------|------|
| LANG-001 | Registry stores paths/args/env/workdir/capabilities | toolchain registry | 1 | IMPLEMENTED | app/toolchains/registry.py, app/toolchains/service.py | tests/unit/test_toolchains.py | FR-004 | M |
| LANG-002 | Projects may contain multiple languages/toolchains | registry | 1 | IMPLEMENTED | app/toolchains/detection.py | tests/unit/test_toolchains.py | LANG-001 | M |
| LANG-003 | Missing tool → actionable diagnostic | toolchain registry | 1 | IMPLEMENTED | app/toolchains/service.py | tests/unit/test_toolchains.py | LANG-001 | L |
| LANG-004 | Formatting available manually + as agent action | adapters, tools | 1/3 | IN_PROGRESS | app/toolchains/service.py, RunView UI | tests/unit/test_toolchains.py | LANG-001 | L |
| LANG-005 | Compiler/test output passes observation normalizer | context-engine | 3 | IMPLEMENTED | app/agents_runtime/observations.py, app/toolchains/service.py | tests/unit/test_agent_gateway.py | FR-023 | M |

## Task / recovery rules (spec §13, §26)

| ID | Requirement | Subsystem | Phase | Status | Files | Tests | Depends | Risk |
|----|-------------|-----------|-------|--------|-------|-------|---------|------|
| TASK-001 | No vague tasks when acceptance criteria can be explicit | planner | 2 | IMPLEMENTED | app/api/routes/requirements.py | tests/integration/test_durable_core_api.py | FR-006 | M |
| TASK-002 | Task state persisted independently of worker process | db, orchestrator | 2 | IMPLEMENTED | app/db/models/tasks.py, app/durable/ | tests/integration/test_durable_activities.py | FR-006 | H |
| TASK-003 | Task attempts preserve failure reasons + evidence | db, recovery | 2/3 | IMPLEMENTED | app/db/models/tasks.py, app/durable/activities/ | tests/integration/test_durable_activities.py | TASK-002 | M |
| REC-001 | Recovery preserves task identity + attempt evidence | recovery-manager | 3 | IN_PROGRESS | app/durable/workflows.py, app/durable/activities.py | tests/integration/test_durable_activities.py | TASK-003 | H |
| REC-002 | Retries are bounded | recovery-manager, temporal | 3 | IMPLEMENTED | app/durable/workflows.py (max_attempts + durable timers) | tests/integration/test_durable_activities.py | REC-001 | M |
| REC-003 | Repeated failure → escalation/replan, never infinite loop | recovery-manager | 3 | NOT_STARTED | — | — | REC-002 | M |

## Security rules (spec §31)

| ID | Requirement | Subsystem | Phase | Status | Files | Tests | Depends | Risk |
|----|-------------|-----------|-------|--------|-------|-------|---------|------|
| SEC-001 | All tool execution passes policy enforcement | tool-gateway | 3 | IMPLEMENTED | app/agents_runtime/gateway.py | tests/unit/test_agent_gateway.py | — | H |
| SEC-002 | Least-privilege files/network/secrets/tools per agent | policy engine | 3 | IN_PROGRESS | app/agents_runtime/gateway.py (allowlists) | tests/unit/test_agent_gateway.py | SEC-001 | H |
| SEC-003 | Secrets never in prompts or normal logs | secret store, logging | 3 | NOT_STARTED | — | — | SEC-001 | H |
| SEC-004 | Sensitive actions support HITL approval | hitl, gateway | 3 | IN_PROGRESS | app/agents_runtime/gateway.py (APPROVAL_PATTERNS) | tests/unit/test_agent_gateway.py | SEC-001 | M |
| SEC-005 | Untrusted code runs in stronger isolation when configured | runtime-manager | 6 | IN_PROGRESS (docker backend live: workspace-only mount, network-none, memory/CPU caps, no-new-privileges; gVisor/Firecracker deferred) | app/runtime/runtimes.py | tests/unit/test_runtime_manager.py | FR-018 | H |
| SEC-006 | Tool outputs treated as untrusted input | context-engine | 3 | IN_PROGRESS | app/agents_runtime/observations.py | tests/unit/test_agent_gateway.py | SEC-001 | M |
| SEC-007 | Prompt injection cannot override system policy | policy engine, context | 3+ | NOT_STARTED | — | — | SEC-006 | H |
| SEC-008 | Audit events for security-sensitive actions | events | 3 | NOT_STARTED | — | — | FR-024 | L |
| SEC-009 | User/project data local by default | packaging, config | 10 | NOT_STARTED | — | — | — | L |
| SEC-010 | Credential redaction + secret scanning | logging, gateway | 3 | NOT_STARTED | — | — | SEC-003 | M |

## Performance/reliability rules (spec §41)

| ID | Requirement | Subsystem | Phase | Status | Files | Tests | Depends | Risk |
|----|-------------|-----------|-------|--------|-------|-------|---------|------|
| PERF-001 | UI responsive while agents/runtimes execute | web-ui, api | 9 | NOT_STARTED | — | — | FR-025 | M |
| PERF-002 | Live event streaming incremental + backpressure-aware | api, nats | 9 | NOT_STARTED | — | — | FR-024 | M |
| PERF-003 | Scheduler concurrency bounded by config | scheduler | 4 | IMPLEMENTED | app/services/scheduler.py (HARNESS_SCHEDULER_* limits) | tests/integration/test_phase4_orchestration.py | FR-011 | L |
| PERF-004 | Large logs never injected wholesale into context | context-engine | 3 | IMPLEMENTED | app/agents_runtime/observations.py | tests/unit/test_agent_gateway.py | FR-023 | H |
| PERF-005 | Recovery operations idempotent where possible | recovery-manager | 3 | NOT_STARTED | — | — | REC-001 | M |
| PERF-006 | Durable state survives application restart | db, temporal | 2/3 | IN_PROGRESS | app/durable/workflows.py (durable timers/state) | scripts/smoke_durable.py | FR-024 | H |
| PERF-007 | Agent process loss must not destroy task state | orchestrator, db | 3 | IMPLEMENTED | app/services/agents.py (supervise_sessions), app/durable/workflows.py | tests/integration/test_phase3_runtime.py | TASK-002 | H |
| PERF-008 | Index updates incremental after file changes | code-intelligence | 5 | IMPLEMENTED | app/codeintel/indexer.py (hash-driven reindex), app/db/models/codeintel.py | tests/integration/test_codeintel_index.py | FR-013 | M |

## Product acceptance criteria (spec §44)

| ID | Acceptance criterion | Verified via | Phase | Status |
|----|----------------------|--------------|-------|--------|
| AC-001 | Open real repo, edit/format/build/test without AI | E2E suite + manual | 1 | IN_PROGRESS (works today; scripts/smoke_editor.py covers the API path) |
| AC-002 | Submit requirement → structured execution plan | E2E | 2 | IN_PROGRESS (API flow live; planner UI lands later) |
| AC-003 | Dynamic multi-agent concurrent execution | Agent-protocol + concurrency tests | 4 | IN_PROGRESS (scheduler + concurrency live; full protocol in later phases) |
| AC-004 | Async communication + durable shared artifacts | Contract tests | 4 | IN_PROGRESS (durable messages + JetStream fan-out live; artifact-payload refs live) |
| AC-005 | Parallel changes isolated + safely integrated | Worktree/integration tests | 4 | IN_PROGRESS (worktrees + integration queue live; review gates land Phase 8) |
| AC-006 | Agents use compilers/formatters/linters/test runners | Toolchain adapter tests | 1/6 | NOT_STARTED |
| AC-007 | Pause/resume + worker-failure recovery | Recovery tests | 3 | IN_PROGRESS (pause/resume live; supervision live) |
| AC-008 | Semantic/structural repo inspection | Code-intelligence tests | 5 | IN_PROGRESS (symbol index + hybrid retrieval + SCIP-JSON export live; LSP daemon + call/dependency graphs deferred) |
| AC-009 | Tool output compressed before context injection | Context tests | 3 | IMPLEMENTED (FR-023 observation compression) |
| AC-010 | Web/MCP/browser permission-controlled + observable | Security tests | 7 | NOT_STARTED |
| AC-011 | Requirement coverage continuously tracked | Overseer tests | 8 | NOT_STARTED |
| AC-012 | High-risk decisions independently reviewed/adjudicated | Review tests | 8 | NOT_STARTED |
| AC-013 | HITL intervenes without destroying state | HITL tests | 3/9 | IN_PROGRESS (fail-closed gates live; UI Phase 9) |
| AC-014 | Office UI reflects live execution state | UI tests | 9 | NOT_STARTED |
| AC-015 | Completion evidence-backed, blocked by unmet criteria | Overseer tests | 8 | NOT_STARTED |
| AC-016 | Restart preserves durable execution state | Restart-recovery tests | 2/3 | NOT_STARTED |
| AC-017 | Multi-language via configurable toolchains | Multi-language suite | 1/6 | NOT_STARTED |

## Phase 0 evidence

What exists and is validated today (see `IMPLEMENTATION_STATUS.md` validation log):

- Runnable control plane: `services/api` — liveness/readiness probes, structured logging,
  request-ID correlation, opt-in OTel tracing.
- Durable event sink scaffold: `events` table (FR-024 partial, `IN_PROGRESS`) with migration
  `0001_initial_core` and integration test `services/api/tests/integration/test_db_smoke.py`.
- Local infrastructure: `docker-compose.yml` (PostgreSQL+pgvector, Redis, NATS; profiles for
  Temporal + OTel collector).
- Quality gates + CI (`.github/workflows/ci.yml`), requirements traceability (this file).



