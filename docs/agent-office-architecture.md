# Agent Office architecture — Wave 7

Status: contract inspection completed before implementation. Every claim below
was read from backend/frontend source (paths cited). No new backend concepts
are introduced; the Office is a projection over existing durable state plus
three existing-but-unwired read endpoints (messages, worktrees, costs).

## 1. Existing data sources (all real, no simulation)

| Source | Route / store | Fields used |
|---|---|---|
| Agents | `GET /api/projects/{id}/agents` → `officeStore.agents` | `id, name, role, model, capabilities[], state` (`schemas/orchestration/agents.py`) |
| Agent lifecycle | `agents_runtime/lifecycle.py:10-40` (14 states, transition map) | `created, planning, running, waiting, blocked, pause_requested, draining, paused, resuming, verifying, completed, failed, recovering, cancelled` |
| Tasks | `GET /api/projects/{id}/tasks` → `officeStore.tasks` | `id, title, request, status, priority, requirement_id, parent_task_id, depends_on[], attempts[{attempt_number, agent_id, outcome, failure_class, failure_detail, evidence_artifact_ids[]}]` |
| Task control | `POST /api/tasks/{id}/execute\|pause\|resume\|cancel` (existing client fns) | execute → `{started, workflow_id}`; pause/resume → 204 signal (ack ≠ applied); cancel → `TaskOut` FR-014 |
| Messages | `GET /api/agents/{id}/messages?limit` (NEW frontend client fn, existing backend) | `id, conversation_id, sender/recipient_agent_id, task_id, type (request\|response\|progress\|artifact\|question\|broadcast), payload, payload_ref, priority, correlation_id, reply_to, created_at, delivered_at` |
| Worktrees | `GET /api/projects/{id}/worktrees?status&limit` (NEW client fn) | `id, task_id, branch, path, status (active\|merged\|abandoned), integration_status (none\|queued\|integrating\|merged\|conflict)` |
| Costs | `GET /api/projects/{id}/intelligence/costs?task_id` (NEW client fn) | `{invocations, total_tokens, by_model, by_role, budget_tokens_per_task}` — project- or task-scoped only |
| HITL | `GET /api/hitl?project_id&status` → `officeStore.hitl`; `POST …/hitl/{id}/decide` | `id, task_id, kind, question, choices[], risk, status (pending\|approved\|rejected\|modified\|timeout), created_at` |
| Oversight | `GET …/oversight/traceability` → `officeStore.traceability` | requirements/criteria/coverage/blockers/warnings (existing OversightTab, unchanged) |
| Reviews | `POST /api/tasks/{id}/reviews` → `lastReview` | existing TeamTab flow, unchanged |
| Realtime | `GET /api/events/stream` (SSE) → `officeStore.events` (cap 120) | `EventEntry{id, occurred_at, event_type, project/task/agent/execution_id, payload, project_seq}` |
| Toolchains | existing `useStore.toolchains` + `output` | detected tools, last run result (existing StatusBar/RunView, unchanged) |

## 2. Event types consumed (48 literals emitted by the backend)

Agent: `AGENT_CREATED, AGENT_STATUS_CHANGED` (projected to agent rows;
`AGENT_STARTED` also honored). Task: `TASK_SCHEDULED, TASK_EXECUTION_STARTED,
TASK_REPLANNED, TASK_COMPLETED, TASK_FAILED, TASK_TERMINALLY_FAILED,
TASK_CANCELLED, TASK_REPLAN_STARTED, TASK_REPLANNED, DEPENDENCY_WAIT_STARTED,
DEPENDENCY_RESUMED`. Recovery (timeline + recovery derivation):
`RECOVERY_SELECTED, RETRY_STARTED, AGENT_REPLACED, MODEL_SWITCHED,
CONTEXT_COMPACTED, DEBUGGER_SPAWNED, DEPENDENCY_WAIT_STARTED,
DEPENDENCY_RESUMED, TASK_TERMINALLY_FAILED`. HITL: `HITL_REQUESTED,
HITL_RESPONDED, HITL_RECOVERY_REQUESTED, HITL_RECOVERY_RESPONDED` (dirty flag →
authoritative `listHitl` refresh). Tools/validation: `TOOL_RUN_COMPLETED
{language, tool, exit_code, duration_ms, path, artifact_ids}`,
`MCP_TOOL_CALLED, BROWSER_SCREENSHOT, REVIEW_FAILED_CLOSED,
DECISION_ADJUDICATED, SECURITY_SCAN_COMPLETED, SCOPE_DRIFT_ALERT`. Infra
(kept out of the Office activity view, still in raw timeline):
`LEASE_*, PORT_*, WORKTREE_*, INTEGRATION_*, GIT_COMMIT, PROJECT_OPENED,
MODEL_BUDGET_EXCEEDED, PLAN_CREATED, REQUIREMENT_CREATED`.

There are NO `MESSAGE_*`, `TASK_PROGRESS`, or per-tool-start events: message
and tool-start granularity below `TOOL_RUN_COMPLETED` is a genuine backend
gap (see §8). The Office never invents them.

## 3. State derivation rules (pure, unit-tested in `office/selectors.ts`)

- **Agent → tasks**: a task belongs to an agent when any
  `attempt.agent_id === agent.id`; the *current* task is the one whose latest
  attempt references the agent and whose status is non-terminal, else the most
  recently attempted task. No backend link field exists — this join IS the
  contract and is tested.
- **Waiting reason**: for agents in `waiting|blocked` (or tasks
  `blocked`): unresolved `depends_on` ids resolved against task statuses →
  "Waiting for {title} ({status})"; `DEPENDENCY_WAIT_STARTED` payload as
  fallback; otherwise "Waiting — no dependency detail recorded". Waiting is
  rendered as a distinct warning state, never as idleness.
- **Recovery**: per task, from `attempts` (ordered by `attempt_number`:
  `failure_class, failure_detail, outcome`) plus correlated events
  (`RECOVERY_SELECTED{action,…}, RETRY_STARTED, AGENT_REPLACED{…},
  MODEL_SWITCHED, CONTEXT_COMPACTED, DEBUGGER_SPAWNED, TASK_TERMINALLY_FAILED`).
  Displayed as a real lifecycle chain (failed → classified → decision →
  action → verification → recovered/still failing). Only the 13 Wave 2 actions
  plus `escalate_model/escalate_or_replan` are ever named; anything else
  renders as its raw recorded string.
- **Agent activity**: last event with matching `agent_id` (any prefix) →
  human sentence; first-seen event time → "active since" (elapsed is
  event-derived, labeled as such — DTOs carry no timestamps).
- **Overall execution state**: `failed/recovering` tasks or failed agents →
  "needs attention"; any `running` → "running"; any `paused|waiting|blocked` →
  "waiting"; pending only → "ready"; all terminal-ok → "completed"; empty →
  "no tasks". Counts shown alongside — never a bare dot.
- **Timeline grouping**: consecutive same-`event_type` rows within 90 s merge
  into "N × TYPE" with first/last timestamps and up to 3 distinct details.
  Infra `LEASE_*/PORT_*` excluded from the Activity view by default (kept in
  raw "all" filter).
- **Costs**: project summary (`total_tokens`, `invocations`, top model/role,
  `budget_tokens_per_task`) + optional task scope in detail. No per-agent
  breakdown exists — the UI says so instead of dividing numbers.

## 4. Components

- `OfficeView` — header (project, overall state, agent/task/approval counts,
  connection, cost summary, resync) + tabs (Team, Activity, Comms, Oversight)
  + prominent `ApprovalCard` + footer. Selecting an agent swaps the body to
  `AgentDetail` (context preserved, back button — no route change).
- `TeamTab` — enriched agent cards (status + current task + waiting reason +
  last activity + recovery badge, all buttons) + task rows (status,
  dependencies, evidence, recovery chain link, owner jump, existing controls).
- `ActivityTab` (extends `TimelineTab`) — grouped timeline, category filters
  (agents, tasks, recovery, tools, tests, comms-adjacent, HITL, security),
  agent-scoped filter, click-through to agent/task selection.
- `CommsTab` (new) — messages merged across agents sorted by `created_at`
  (bounded), sender → recipient rendering, type/priority/correlation labels,
  selection reveals timestamp, task, correlation/reply-to, payload keys and
  evidence ref. Read-only: `POST /api/messages` exists but agent-authored
  messaging from the UI would fake provenance — explicitly out of scope.
- `AgentDetail` (new) — lazy sections: Overview, Activity, Tasks, Tools,
  Files, Dependencies, Communication, Recovery, Evidence, Cost. Messages,
  worktrees, and costs fetch on first open only. Message detail shows payload
  *keys*, never values: payloads may carry secrets and there is no backend
  field marking them safe (§22). Requirement jumps land on the existing
  Oversight tab (no duplicate pages).
- Reused Wave 6: `StatusLabel` tones, `UiState`, `useDialogFocus`,
  `ViewBoundary`, resizable/persisted panels, command palette (plus an "Open
  communication" navigation command).

## 5. Interaction model

Selection (`selectedAgentId/selectedTaskId` in `officeStore`) is the single
navigation mechanism: cards, task rows, timeline rows, messages, HITL cards,
and approval links all select rather than navigate away. Contextual actions
are exactly the existing endpoints (execute/pause/resume/cancel/retry task,
bulk fan-out, decide HITL, request review, open file/symbol, open panel);
unavailable actions render disabled with the recorded reason. Destructive
actions (cancel/stop) confirm. Symbol search is palette/command-only
(browsers reserve Ctrl+T).
Nothing polls: team/activity state flows from SSE + authoritative resync;
messages/worktrees/costs load on view open with an explicit refresh action
(no message events exist to subscribe to).

## 6. Performance strategy

Bounded everything: timeline 120, messages 100/agent-merged-200 cap,
worktrees 100, dedup window 512 (all pre-existing or mirrored). Derived state
is memoized (`useMemo`) over store slices with stable selectors; detail
sections mount lazily. No virtualization: measured derivation over synthetic
50 agents / 500 tasks / 5000 events must stay under frame budget — recorded in
`docs/agent-office-performance.md`; virtualize only if measurement says so.

## 7. Accessibility strategy

Agent cards and rows are native buttons with `aria-label`s ("Agent {name},
{state}, {activity}"); status never color-alone (icon glyph + text +
`StatusLabel`); timeline groups use list semantics with textual counts;
comms/dependency visuals always paired with textual sender→recipient and
"waiting for X" sentences; `aria-live="polite"` for connection + HITL count;
dialogs reuse `useDialogFocus` with focus restoration; `prefers-reduced-motion`
inherited from the Wave 6 global rule. Dense views get `title` tooltips, not
ARIA soup.

## 8. Backend gaps (explicit, not fabricated in UI)

Revisited 2026-09-18 — each former skip was re-verified against source:

BUILT since first writing: bulk pause/resume/stop (fan-out, §6 above);
failed-task retry (execute endpoint, new Temporal run, attempts preserved;
cancelled excluded); workspace symbol search (palette + dialog over
`GET …/symbols`, editor jump); sole-vs-shared cost attribution labels
(`costAttribution`: a task scope belongs to one agent only when no other
agent attempted it).

STILL REFUSED, with evidence:
1. Agent spawn UI — `create_agent` (`services/orchestration/agents.py:46`)
   is a bare registry insert; the only activation path, `start_session`,
   on a taskless agent heartbeats nothing until supervision marks it
   `lost`/`failed`. Exposing spawn would manufacture failing agents.
2. Per-agent pause/resume/stop — no endpoints exist; sessions cannot even be
   listed (no GET sessions route), so there is nothing truthful to act on.
3. Task creation UI — no POST tasks route exists (only list/get/
   cancel/pause/resume/execute in `api/routes/planning/tasks.py`).
4. Message composing — `POST /api/messages` exists but requires choosing a
   `sender_agent_id`: the UI would impersonate agents. Read-only stands.
5. Execution Graph / replay / traceability explorer / 3-column shell —
   separate waves / stopping-condition items, not Wave 7 scope.

1. No `MESSAGE_*` realtime events — comms refresh is manual/on-open.
2. No per-agent cost aggregation (`ModelInvocation.agent_id` stored, never
   exposed) — UI shows project/by-role/task scopes with a labeled note.
3. No timestamps on `AgentOut/TaskOut/AttemptOut` — elapsed/first-seen is
   event-derived and labeled "since first recorded event".
4. No `current_tool/current_file/waiting_reason` on agents — UI derives last
   `TOOL_RUN_COMPLETED.path` and dependency join, labeled as last-recorded.
5. `replace_agent/spawn_debugger/request_hitl` unreachable via the pure Wave 2
   policy core (workflow handles them; policy never emits them) — the UI names
   only actions actually recorded in `RECOVERY_SELECTED`.
6. No global pause/resume/stop-execution endpoint — CLOSED on the frontend
   by fan-out: the Office header offers Pause N / Resume N / Stop N over the
   existing per-task endpoints with one confirmation, per-task result
   reporting, and a single resync (`bulkEligible` reuses the per-task
   availability builder). No bulk semantics were invented server-side.
7. `TaskOut` omits `constraints/acceptance_criteria/allowed_tools/deadline`
   — detail shows `request/expected_output/priority/retry_policy` only.
8. Events carry no `requirement_id`, so the Activity view filters by agent
   and task but not by requirement; requirement navigation jumps to the
   Oversight tab instead.
9. The Office is sidebar-hosted: the single-column layout with
   selection-preserving detail *is* the narrow transformation. A large-screen
   three-column (Agents | Activity | Detail) arrangement needs a shell
   rework and is deferred — not a Wave 7 regression, an explicit constraint.
