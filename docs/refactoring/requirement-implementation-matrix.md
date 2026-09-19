# Requirement → Implementation Matrix (Phase B)

Traceability: Requirement → Capability → API → Service → Domain → Database →
Events → Agent → Tool → Frontend → Tests → Evidence. Status: OK / PARTIAL /
GAP. Sources: `REQUIREMENTS_MATRIX.md`, `AI_HARNESS_PRODUCT_SPEC.md`,
`requirement-traceability.md`, verified against code.

| Requirement | Capability | API | Service/Domain | DB | Events | Frontend | Tests | Status |
|---|---|---|---|---|---|---|---|---|
| Projects/files/editing | Project mgmt, editor | `/api/projects`, `/tree`, `/file`, `/entries`, `/search` | `services/workspace`, `files/*` | `projects` | `PROJECT_OPENED`, `FILE_WRITTEN` | Explorer, Monaco, diff | files/git suites | OK |
| Requirements + criteria | Requirements | `/requirements`, `/criteria/*/verify` | `services/planning`, overseer | `requirements`, `acceptance_criteria`, `validations` | `REQUIREMENT_CREATED` | Oversight, traceability | overseer/gates suites | OK |
| Planning/tasks/DAG | Planning | `/plans`, `/tasks`, execute/pause/cancel | `services/planning`, `tasks/graph.py` | `tasks`, `task_dependencies`, `plans` | `TASK_*` | Team, DepMap, graph | graph/scheduler suites | OK |
| Agents/sessions | Agent runtime | `/agents`, `/sessions/*`, supervise | `agents_runtime/*`, `services/orchestration/agents` | `agents`, `agent_sessions` | `AGENT_*` | Team, AgentDetail | lifecycle/sessions suites | OK |
| Execution | Temporal workflows | `/tasks/{id}/execute`, signals | `durable/*` (workflow + 19 activities) | attempts, events | `TASK_EXECUTION_STARTED`, attempt rows | Office live | workflow suites (7) | OK |
| Tools/policy | Tool gateway | (via execution) | `agents_runtime/gateway.py` | invocations (ledger) | `TOOL_*` | Output panel, timeline | gateway suites | OK |
| Models/fallback | Registry | models-config file | `agents_runtime/models_registry`, `providers` | `model_invocations` | `MODEL_SWITCHED`, `MODEL_BUDGET_EXCEEDED` | Costs surfaces | retry/cost suites | OK |
| Recovery | Policy + executor | (workflow-internal) | `services/orchestration/recovery` | recovery trail in payloads | `RECOVERY_*`, `TASK_REPLANNED` | Timeline, Problems | recovery suites | OK |
| HITL | Gates | `/hitl`, `/decide`, `/cancel` | `services/orchestration/hitl` | `hitl_requests` | `HITL_*` | Approval cards | hitl suites + race test | OK |
| Context/budgets | Broker + ledger | `/intelligence/costs` | `agents_runtime/context_broker`, `services/intelligence/costs` | `model_invocations` | (ledger rows) | Command Center context | compaction/costs suites | OK |
| Codeintel | Index/search | `/symbols`, `/retrieve`, `/index` | `codeintel/*` | `symbol_files`, `symbols` | — | Symbol search | codeintel suites | OK |
| Runtimes/ports/leases | Execution plane | `/ports`, `/leases`, `/runtimes` | `runtime/*`, `services/execution`, leases | `port_allocations`, `resources` | `PORT_*`, `LEASE_*` | Runtime view, terminal | ports/leases/quotas suites | OK |
| Worktrees/git | Isolation | `/worktrees`, `/git/*` | `gitops/*`, worktree service | `worktrees` | `WORKTREE_*`, `GIT_COMMIT` | Git view | worktrees suites | OK |
| Browser/MCP/research | Integrations (opt-in) | `/browser/*`, `/mcp/*`, `/research` | `browser/*`, `mcp/*`, `research/*` | sessions, artifacts | `BROWSER_*`, `MCP_TOOL_CALLED` | Panels/dialogs | browser/mcp/research suites | OK |
| Realtime | SSE projection | `/events`, `/events/stream`, `/metrics` | `realtime/*` | `events`, `event_sequences` | all durable types | store/reducer/views | scenarios A–H + NATS e2e | OK |
| Evaluation | Offline suite | eval CLI + artifact persist | `evaluation/*` | (own reports, not DB) | — | (reports as artifacts) | eval suites | OK |
| Auth/security | Wave 1 | middleware (all `/api/*` + WS) | `api/security.py`, `env_sandbox`, `research/ssrf` | — | `AUTHENTICATION_FAILED`, `SSRF_BLOCKED` | token settings, 4401 handling | wave1 suites | OK |
| Autonomous planning | — | — | — | — | — | — | — | GAP (documented) |
| Multi-tenant identity | — | single shared token | — | — | — | — | — | GAP (documented) |
| Virtualized lists | — | bounded pages instead | — | — | — | caps (100/120/500) | perf tests | PARTIAL (by design) |

No requirement maps to two competing implementations (verified in inventory).
No test file lacks a corresponding behavior (suite green = exercised).
