# Recovery Architecture (Wave 2)

How the AI Harness turns failures into bounded, durable recovery. The Temporal
task workflow is the **authoritative coordinator**: a recovery decision always
results in a real bounded action or an explicit terminal/HITL state — never an
advisory field.

## Flow

```
Agent/Tool Failure (agent_execute_activity)
        |
        v
Failure Classification  recovery.py::classify_failure
        |                (deterministic: exit codes, timeouts, provider errors,
        |                 dependency state, policy violations)
        v
Recovery Decision  recovery_decision(...)   <- pure, workflow-deterministic
        |            failure_class + attempt_number + max_attempts
        |            -> action, parameters, backoff, budget sensitivity,
        |               recovery_id (deterministic => idempotency key)
        v
Temporal Workflow  TaskExecutionWorkflow  (RECOVERY_SELECTED, then dispatch)
        |
        v
+----------------------- Executor dispatch -----------------------------------+
| stop               -> terminal_failure_activity (evidence + recommended     |
|                       action) + TASK_TERMINALLY_FAILED                     |
| escalate_or_replan -> replan_task_activity (durable child task with the    |
|                       failure evidence) + terminal failure  [REC-003]      |
| retry_if_safe / retry_then_replan / recreate_runtime / throttle_then_retry |
|                    -> RETRY_STARTED + durable workflow.sleep(backoff)      |
| rebuild_context    -> CONTEXT_COMPACTED; next attempt re-assembles context |
|                       with a scaled budget (real compaction)               |
| retry_alternate_model / escalate_model                                     |
|                    -> MODEL_SWITCHED; next attempt routes via the registry |
|                       fallback_role (config-driven, never hard-coded)      |
| replace_agent      -> end_agent_session_activity (failed agent drained) +  |
|                       AGENT_REPLACED; next attempt carries replaces_agent_id|
| spawn_debugger / create_integration_task                                   |
|                    -> spawn_child_task_activity (durable child task with   |
|                       structured failure evidence); the parent then        |
|                       terminates WITH a reference to the child (no dead    |
|                       wait — nothing auto-executes the child, so waiting   |
|                       on a completion signal would only delay the same     |
|                       terminal state past the dependency timeout).         |
|                       Children are born `pending`, so the scheduler picks  |
|                       them up for durable execution (no dangling rows).    |
|                       Merge conflicts additionally roll back first (below).|
| wait_for_dependency-> pre-check (already-finished deps resume immediately) |
|                       then task "blocked" + durable signal wait, deadline  |
|                       converts to terminal failure (no busy loop)          |
| request_hitl       -> hitl_recovery_gate_activity (durable, fail-closed); |
|                       approved continues via RETRY_STARTED + backoff,      |
|                       rejected/timed-out/cancelled terminates              |
+------------------------------------------------------------------------------+
        |
        v
Validation / next attempt / terminal or HITL state
(completed tasks signal dependent workflows via dependency_completed)
```

## Failure classes (spec §26 — do not extend casually)

The eleven spec classes, plus two policy classes the executor emits itself:

| Class | Non-retryable | While attempts remain | Last attempt (1 left) | Ladder end |
|---|---|---|---|---|
| MODEL_FAILURE | | `retry_alternate_model` | `escalate_model` | `escalate_or_replan` |
| TOOL_FAILURE | | `retry_if_safe` | `replace_agent` (fresh agent, old drained) | `escalate_or_replan` |
| ENVIRONMENT_FAILURE | | `recreate_runtime` (fresh runtime per attempt) | `recreate_runtime` | `escalate_or_replan` |
| CONTEXT_FAILURE | | `rebuild_context` (budget scaled to 0.5) | `rebuild_context` | `escalate_or_replan` |
| TASK_FAILURE | | `retry_then_replan` | `spawn_debugger` (parent terminates with child ref) | `escalate_or_replan` |
| TIMEOUT | | `retry_then_replan` | `retry_then_replan` | `escalate_or_replan` |
| DEPENDENCY_FAILURE | | `wait_for_dependency` | `wait_for_dependency` | `escalate_or_replan` |
| MERGE_CONFLICT | | `create_integration_task` (worktree queue owns merges) | `create_integration_task` | `escalate_or_replan` |
| RESOURCE_LIMIT | | `throttle_then_retry` (doubled backoff) | `request_hitl` (operator guidance) | `escalate_or_replan` |
| SECURITY_BLOCK | yes | `stop` | `stop` | `stop` |
| HITL_TIMEOUT | yes | `stop` | `stop` | `stop` |
| BUDGET_EXCEEDED (policy) | yes | `stop` | `stop` | `stop` |
| QUOTA_EXCEEDED (policy) | | `throttle_then_retry` | `throttle_then_retry` | `escalate_or_replan` |

## ROLLBACK (evidence-preserving)

Every attempt snapshots the project repo HEAD (`snapshot_attempt_activity` →
`SNAPSHOT_CREATED`, idempotent per attempt; non-git projects skip gracefully).
On `create_integration_task`, `rollback_attempt_activity` restores the worktree
to the snapshot **after** preserving the pre-reset HEAD on a
`recovery/<task>-<attempt>` branch referenced from `ROLLBACK_COMPLETED`:
history and evidence are never deleted, only working state is restored
(tracked files; untracked files are left alone — deleting them would destroy
unrecoverable evidence). No snapshot means a graceful no-op. Crash-safe: a
retry reuses the evidence branch and converges on the same state.

Distinctions: RESOURCE_LIMIT = infrastructure exhaustion; BUDGET_EXCEEDED =
per-task token-budget policy (§32); QUOTA_EXCEEDED = per-project concurrency
slots (§19.1). Non-retryable classes fail terminally on first occurrence — hard
policy signals are never weakened by heuristics, and LLM output never overrides
them.

## Bounds and safety

- **Attempt limit**: `retry_policy.max_attempts` clamped to 1..10; the loop
  cannot exceed it (REC-002).
- **Ladder end**: every retryable class ends at `escalate_or_replan` — a durable
  replan child task plus a terminal failure with evidence (REC-003). No class
  loops.
- **Backoff**: `min(base * factor**(attempt-1), max)` with ±`jitter_ratio`
  deterministic jitter (uuid5 of the task/attempt seed — Temporal-replay safe,
  no RNG). Knobs: `HARNESS_RECOVERY_BACKOFF_BASE_SECONDS` (2), `..._FACTOR` (2),
  `..._MAX_SECONDS` (60), `..._JITTER_RATIO` (0.25),
  `..._DEPENDENCY_WAIT_SECONDS` (900).
- **Budget gates (§9/§32)**: expensive actions (`retry_alternate_model`,
  `escalate_model`, `replace_agent`, `spawn_debugger`,
  `escalate_or_replan`) check the remaining task budget first
  (`recovery_budget_activity`, cost ledger). Insufficient budget routes the
  decision through the durable HITL gate; a rejected/timed-out gate fails the
  task terminally. Recovery never bypasses cost control.
- **HITL (§13/§25)**: `hitl_recovery_gate_activity` creates a durable
  `hitl_requests` row (kind `recovery_decision`) showing what failed, what was
  detected, the proposed action and its evidence; waits fail-closed. Approval
  continues; rejection/timeout/cancellation terminates. Lifecycle
  `pending → approved | rejected | modified | timeout | cancelled`
  (`timeout` is the expired state; `cancelled` is operator withdrawal via
  `POST .../hitl/{id}/cancel`). Survives restarts (durable row +
  Temporal history).
- **Agent replacement (§11)**: the failed attempt's execution slot is released
  by the execution activity's `finally`; `end_agent_session_activity` closes the
  session row and marks the agent failed; the next attempt records
  `replaces_agent_id` (FR-008). Policy denials inside the execution activity are
  contained failure outcomes (`SECURITY_BLOCK`), never escaping exceptions —
  an escaping exception would fail the workflow run and strand the task as
  "running" with no terminal state. Agents are disposable per attempt, so
  duplicate concurrent execution of a task is impossible by construction.
- **Dependencies (§12)**: blocked tasks park on a durable `wait_condition`
  (zero worker usage); before parking, an unfinished-dependency pre-check
  resumes immediately when nothing is actually blocking (a dependency that
  finished before the waiter parked would never signal again); completing
  workflows signal `dependency_completed` on dependents (deterministic workflow
  ids `task-exec-{task_id}`); a wait deadline converts to terminal failure
  with evidence.
- **Failure evidence (§16)**: command failures record exit code plus the
  compressed stderr lines in `failure_detail` — stdout-only summaries miss the
  signal the classifier needs (`tool X missing`, `quota exceeded`). Capability
  denials (`requires 'write' capability`) classify as `SECURITY_BLOCK`.
- **Idempotency (§17)**: every durable recovery effect carries an
  `idempotency_key` (derived from the deterministic `recovery_id`) stored on its
  event payload and checked before creation — activity replays and worker
  crashes never duplicate child tasks, HITL requests, or events, and never
  rewrite attempt identity/evidence (REC-001).
- **History (§15)**: durable and queryable via the event stream
  (`GET /api/events?project_id=&event_type=RECOVERY_SELECTED|RETRY_STARTED|
  MODEL_SWITCHED|AGENT_REPLACED|DEBUGGER_SPAWNED|TASK_REPLANNED|
  DEPENDENCY_WAIT_STARTED|DEPENDENCY_RESUMED|HITL_RECOVERY_REQUESTED|
  HITL_RECOVERY_RESPONDED|TASK_TERMINALLY_FAILED`), attempt rows, and the
  terminal summary on the task payload. Only decision, concise rationale,
  evidence references and results are stored — never chain-of-thought, never
  secrets.

## Persistence

Postgres remains authoritative (attempts, events, HITL rows, terminal payload);
Temporal history owns workflow progression; Redis is not involved in recovery.
Worker or API restarts resume the ladder exactly where the history says.
