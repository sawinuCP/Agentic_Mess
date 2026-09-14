# AI Harness Code Editor — Architecture

**Spec version:** `AI_Harness_Code_Editor_Complete_Implementation_Specification.md` v1.0 (14 Sep 2026)
**Status:** Phase 0 (architecture foundation implemented; AI subsystems NOT_IMPLEMENTED)
**Companion documents:** [`IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md), [`DEVELOPMENT.md`](DEVELOPMENT.md), [`docs/REQUIREMENTS_MATRIX.md`](docs/REQUIREMENTS_MATRIX.md)

---

## 1. Product identity

```text
Requirement
    ↓
Task
    ↓
Agent
    ↓
Context
    ↓
Tool
    ↓
Artifact
    ↓
Validation
    ↓
Evidence
    ↓
Task Completion
```

The product is a durable AI software-engineering operating environment embedded in a professional
code editor. The editor must remain useful without AI (FR-028). Agents, models, tools and runtimes
are replaceable; requirements, tasks, code, artifacts, evidence and history are durable.

## 2. System topology (Phase 0 → target)

```text
┌────────────────────────────────────────────────────────────────────┐
│ Desktop shell (Tauri 2, Phase 1/10) hosting apps/web-ui            │
│   React + TypeScript + Monaco (Phase 1)                            │
│   Office / Execution Graph / Requirements / Diff (Phase 9)         │
└───────────────▲────────────────────────────────────────────────────┘
                │ HTTP + WebSocket/SSE (/api prefix, vite proxy in dev)
┌───────────────┴────────────────────────────────────────────────────┐
│ Control plane — FastAPI "modular monolith" (services/api)          │
│   app/api/          HTTP surface, middleware, deps                  │
│   app/core/         config, errors, structured logging, OTel        │
│   app/db/           SQLAlchemy models + engine/session management   │
│   app/files/        project filesystem (path-safety, tree, search)  │
│   app/gitops/       git CLI client (status/diff/log/stage/commit)   │
│   app/toolchains/   language registry, detection, tool execution    │
│   app/runtime/      process runner (timeout/kill/caps) — Phase 6    │
│                     grows this into sandboxed runtimes              │
│   app/terminal/     PTY sessions over WebSocket (pywinpty/POSIX)    │
│   app/artifacts/    content-addressed artifact store (sha256)       │
│   app/tasks/        task-graph integrity (cycle detection)          │
│   app/durable/      Temporal client/workflow/activities/worker      │
│   app/events/       durable event recording (events table)          │
│   app/orchestration Phase 4: scheduler, supervisor, recovery        │
│   app/agents/       Phase 3: agent runtime, lifecycle, model calls  │
│   app/context/      Phase 3/5: context broker, observation compress │
│   app/tools/        Phase 3/7: tool gateway, MCP, web research      │
│   app/integration/  Phase 4/6: worktrees, merge queue               │
│   app/requirements/ Phase 8: requirement overseer, traceability     │
└───────┬──────────────┬───────────────┬──────────────┬──────────────┘
        ▼              ▼               ▼              ▼
  PostgreSQL      Redis            NATS          Temporal (profile,
  (source of   (leases/cache,   JetStream       Phase 3+; compose
   truth)       Phase 4+)       (transport)      `--profile temporal`)
        ▼
  Object storage for raw artifacts (Phase 2+), pgvector for semantic retrieval (Phase 5+)

Execution plane (Phase 6/7): Docker/dev-container runtimes, Playwright browser workers,
language toolchains (compiler/formatter/linter/test runner/LSP), MCP servers.
```

**Rule:** PostgreSQL is the only source of truth for durable state. NATS is a transport — it never
owns state; consumers deduplicate by event/message ID. Redis holds only expiring coordination data
(leases, rate limits); losing Redis never loses work.

## 3. State ownership & durability rules

| Store          | Owns                                                       | Never owns                     |
| -------------- | ---------------------------------------------------------- | ------------------------------ |
| PostgreSQL     | projects, workspaces, requirements, plans, tasks, attempts, agents, sessions, messages, context items, memories, artifacts metadata, tool defs/calls, worktrees, resource leases (durable view), decisions, reviews, validations, HITL, events, runtimes, toolchains | Raw large blobs |
| Object storage | Raw stdout/stderr, screenshots, large artifacts            | Authoritative metadata         |
| Temporal       | Durable workflow progress, timers, retries (Phase 3+)      | Product semantics/completion   |
| NATS           | Nothing (transport + durable streams for delivery)         | Task/agent state               |
| Redis          | Leases/TTL, heartbeats, hot caches                         | Any state that must survive    |
| Agent process  | Nothing durable; rebuilds context from durable state       | Task ownership                 |

Critical engineering rules (spec §48) are enforced at these boundaries: an LLM is never the
authority on execution state; a running agent process is never the only holder of task state;
recovery is resumable because checkpoints are durable.

## 4. Task identity vs agent identity

```text
TASK-182
  Attempt 1 → Agent-12 → FAILED
  Attempt 2 → Agent-19 → FAILED
  Attempt 3 → Agent-24 → SUCCESS
```

- `tasks` rows are durable; `agents` rows are disposable.
- `task_attempts` record every (task × attempt × agent) with failure classification and evidence.
- A replacement agent resumes from durable state + artifacts, never from another agent's memory.
- All state transitions happen in the runtime (never mutated directly from UI or model code) and
  emit a durable `events` row.

## 5. Agent lifecycle (Phase 3 implementation; contract fixed now)

```text
CREATED → PLANNING → RUNNING ⇄ WAITING/BLOCKED → VERIFYING → COMPLETED
                        |                            |
                 PAUSE_REQUESTED                  FAILED
                        ↓                            ↓
                     PAUSED ← RECOVERING ←───────────┘
                        ↓
                    RESUMING → RUNNING            (CANCELLED from any state)
```

Heartbeat + lease renewal are mandatory while RUNNING. Pause reaches a safe checkpoint before
suspending new work. Emergency stop is distinct from pause. Every transition emits an event.

## 6. Contracts (v0 — formalized in `packages/schemas` during Phase 2/3)

**Event envelope** (spec §28): `event_id, occurred_at, event_type, source, project_id,
execution_id, agent_id, task_id, correlation_id, trace_id, payload` — persisted in `events`
(migration `0001` creates the table + indexes for project/occurred-at, execution, correlation,
trace lookups).

**Inter-agent message** (spec §14): `message_id, conversation_id, sender_agent_id,
recipient_agent_id, task_id, type, payload_ref, priority, created_at, correlation_id, reply_to,
expires_at` — large payloads are stored as artifacts and referenced, never inlined.

**Task spec** (spec §13): `task_id, parent_task_id, request, expected_output, constraints,
acceptance_criteria, dependencies, priority, context_refs, resource_requirements, allowed_tools,
deadline, retry_policy`.

**Observation compression** (spec §15/23, FR-023): raw tool output → artifact + compact JSON
observation (`tool, status, exit_code, summary, relevant_errors, artifact_ref`) before any model
sees it.

## 7. Context engineering

Hybrid context: global durable project state + agent-private context + selected shared evidence.
Before every model call: `request → plan → retrieve → rank → compress → build prompt → model`.
Tiering (spec §15): T0 safety/policy → T1 task+criteria → T2 project/plan state → T3 relevant
code/tests/deps → T4 recent history/messages → T5 research evidence → T6 raw details only when
explicitly required. Token budgets are enforced per call; repository dumps are prohibited.

## 8. Code intelligence (Phase 5)

Layered, not embedding-only: Tree-sitter (symbols) → LSP (defs/refs/diagnostics) → SCIP
(language-neutral index) → lexical/BM25 → embeddings (pgvector) → dependency/call graphs →
CFG/DFG/PDG/CPG only when a task justifies deeper analysis. Answers required: where defined, where
used, what depends on it, which tests cover it, what files are affected, what is relevant.

## 9. Execution & isolation (Phase 4/6)

- Code-writing agents work in Git worktrees (`agent/task-<id>` branches); integration happens only
  through the integration queue; conflicts become explicit tasks.
- All execution passes: `agent → tool gateway → policy check → runtime manager → sandbox → command
  → result → normalizer → artifact → agent context`.
- CPU/memory/process/disk/time quotas, network policy, filesystem restrictions, secret isolation,
  process cleanup (spec §19).
- Central port allocator: allocation, reservation, TTL, release, conflict detection, preview gateway.

## 10. Security model (Phase 0 posture; enforcement lands Phase 3+)

Security is a runtime responsibility, not a prompt instruction (SEC-001..010):

- Tool/execution policies enforced in the gateway/runtime manager, outside the model.
- Least-privilege file/network/secret/tool access per agent policy.
- Secrets never enter prompts or logs; redaction + scanning (SEC-003/010).
- Repository files, web pages, tool output and MCP output are untrusted input (SEC-006/007);
  prompt injection must never override system policy.
- Security-sensitive actions support HITL approval (SEC-004) and emit audit events (SEC-008).

## 11. Model routing (config-driven from day one)

No model names are hard-coded in code. A model registry/policy (Phase 3) maps roles → provider +
model + fallbacks + budgets (spec §32): routine worker → fast/cheap (GLM-5.3-Flash is the
practical default for inexpensive worker tasks in this environment), planner/reviewer/security →
stronger models, adjudicator → highest-confidence within budget. Independent verification should
prefer a different model family.

## 12. Observability

- Structured JSON logs (stdlib formatter, request-ID propagation) — implemented in Phase 0.
- Durable events in `events` (implemented as of migration 0001); live streaming to UI via
  WebSocket/SSE in later phases.
- OpenTelemetry tracing wired behind `HARNESS_OTEL_ENABLED` with OTLP/HTTP export; collector in
  `infrastructure/observability/` (compose profile `observability`).
- Timeline filtering by agent/task/tool/file and cost/token accounting arrive with Phases 3/9.

## 13. Architecture decisions (ADR summary)

| ADR | Decision | Rationale |
| --- | -------- | --------- |
| 0001 | Control plane is a **modular monolith** (`services/api`), not many microservices | Local desktop product; spec §35 forbids unnecessary microservices. Module boundaries + NATS-mediated interfaces allow extraction later. |
| 0002 | Heavy infra (Temporal, OTel collector) behind **compose profiles** | Keeps default dev loop fast on Windows; Temporal only required from Phase 3. |
| 0003 | Sync SQLAlchemy 2 + Alembic now; async drivers when worker/event paths demand it (Phase 3+) | Correctness and simplicity first; engine/session boundaries already isolate the choice. |
| 0004 | Structured logging via stdlib JSON formatter; OTel opt-in | Zero-dependency observability floor; upgrades cleanly to full OTel. |
| 0005 | UI talks to API under `/api` prefix (vite dev proxy) | Enables later Tauri bundling and reverse-proxying without UI changes. |
| 0006 | Tests live with each service; cross-service tests under root `tests/` later | Keeps imports simple and CI per package; e2e suite gets a home in Phase 8+. |
| 0007 | Spec requirement IDs (FR/LANG/TASK/REC/SEC/PERF/AC) are permanent traceability keys | Enables the requirements matrix and overseer traceability (FR-013). |
| 0008 | Web UI ships standalone now; Tauri shell added in Phase 1/10 | Tauri requires a Rust toolchain; blocking the editor on packaging is unnecessary. |

## 14. Directory layout (adapted from spec §36)

```text
repo root
├── apps/
│   └── web-ui/            # React+TS+Vite UI (editor: explorer/Monaco/Git/terminals/toolchains)
├── services/
│   └── api/               # FastAPI control plane (modular monolith)
│       ├── app/
│       │   ├── api/       # thin HTTP routes + deps + middleware
│       │   ├── schemas/   # Pydantic request/response contracts
│       │   ├── services/  # business logic + persistence (framework-free)
│       │   ├── core/      # config, errors, logging, observability
│       │   ├── db/        # SQLAlchemy models + engine/session management
│       │   ├── files/     # project filesystem (path-safety, tree, search)
│       │   ├── gitops/    # git CLI client
│       │   ├── toolchains/# language registry, detection, tool execution
│       │   ├── runtime/   # process runner (timeout/kill/caps)
│       │   ├── terminal/  # PTY sessions over WebSocket
│       │   ├── artifacts/ # content-addressed artifact store
│       │   ├── tasks/     # task-graph integrity (cycle detection)
│       │   ├── durable/   # Temporal client/workflow/activities/worker
│       │   └── main.py    # app factory
│       ├── alembic/       # migrations
│       └── tests/         # unit + integration tests
├── packages/              # shared contracts (schemas/protocols) — Phase 5+
├── infrastructure/
│   └── observability/     # OTel collector config
├── docs/
├── scripts/               # check.ps1, smoke_editor.py, smoke_durable.py
└── docker-compose.yml     # local infra with profiles
```

Layering rule (ADR-0001, see CONTRIBUTING.md): routes → schemas → services → db/adapters.
Routes are thin; business logic lives in `services/` (framework-free, sync, invoked via
`asyncio.to_thread`); adapters wrap external tools; `core` stays dependency-free.

Deliberate deviations from spec §36: no separate `services/orchestrator`, `services/context-engine`
… directories yet — those exist as modules inside `services/api/app/` and are extracted only when
the monolith boundary is no longer sufficient (ADR-0001). `migrations/` lives inside `services/api`
because Alembic requires the models importable; documented, not accidental.

## 15. Risks, contradictions and mitigations

| # | Risk / contradiction | Mitigation |
| - | -------------------- | ---------- |
| 1 | Temporal is heavy for local Windows dev (own DB, services) | Compose profile; durable-state rules don't depend on Temporal until Phase 3; interfaces keep it replaceable |
| 2 | Spec §36 diagram suggests many services; §35 forbids fragmentation | ADR-0001 modular monolith with explicit extraction path |
| 3 | Prompt mentions GLM-5.3-Flash; spec forbids hard-coding models | Model registry/policy from Phase 3; no model names in code |
| 4 | Events stored in both PostgreSQL and NATS → duplication risk | PG is truth; NATS is transport; consumers dedupe by event ID |
| 5 | pgvector at repository scale may underperform | Layered retrieval (lexical/AST/LSP first); vector search is one ranker among several |
| 6 | Tauri adds a Rust toolchain prerequisite | UI developed standalone; shell deferred (ADR-0008) |
| 7 | Windows-first quirks: path lengths, file locks, Docker path mounting | Worktree/port managers handle paths explicitly; runtime manager owns mounts; issues tracked per phase |
| 8 | Monaco editor scope creep vs shipping value | Phase 1 defines a minimal editor slice before AI features |
| 9 | `.docx` vs `.md` spec authority | Provided `.md` matches the `.docx`; `.md` is the working copy; `.docx` archived in repo |

## 16. Phase map

| Phase | Deliverable | Exit criteria (spec §37) | Status |
| ----- | ----------- | ------------------------ | ------ |
| 0 | Architecture foundation | Repo, CI, schemas, local services, observability skeleton | **COMPLETE** |
| 1 | Conventional editor | Project open/edit/search/terminal/Git/toolchain basics | **COMPLETE** (web UI; Tauri shell in Phase 10) |
| 2 | Durable core | PG schemas, projects/tasks/agents/events, artifacts | **COMPLETE** (Temporal opt-in via `HARNESS_TEMPORAL_ENABLED`) |
| 3 | Agent runtime + durable orchestration | Lifecycle, tools, context broker, Temporal, pause/resume | NOT_STARTED |
| 4 | Multi-agent team | Dynamic spawn, scheduler, messaging, worktrees, leases | NOT_STARTED |
| 5 | Code intelligence | Tree-sitter + LSP/SCIP + retrieval/ranking | NOT_STARTED |
| 6 | Execution plane | Containers, quotas, ports, supervision | NOT_STARTED |
| 7 | Browser/MCP/web | Playwright, MCP gateway, research evidence | NOT_STARTED |
| 8 | Quality/oversight | Requirement graph, reviewers, adjudication, security | NOT_STARTED |
| 9 | Office UI | Live team view, graph, timeline, evidence | NOT_STARTED |
| 10 | Hardening | Security/recovery/performance, packaging, docs | NOT_STARTED |


