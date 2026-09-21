# Backend Trust & Runtime Hardening — Record

Pre-UI-5 gate. Governing principle: the UI must never claim stronger
execution/verification/completion state than the backend can prove.

## Objective A — snapshot registration: FIXED + VERIFIED

Live symptom: `snapshot_attempt_activity` unregistered on the Temporal worker →
workflow tasks for snapshot stuck, task orphaned `running`.
Fix: registered in `services/api/app/durable/worker.py`.
Guard: `services/api/tests/unit/test_worker_registration.py` (AST check that every
`execute_activity` name in `workflows.py` is registered). Commits `8823481`.

## Objective B — failure reconciliation: FIXED + VERIFIED

`TaskExecutionWorkflow._execute` split out with `_reconcile_terminal_failure`:
terminal workflow error finishes the attempt (`finish_attempt_activity`),
writes `terminal_failure_activity`, takes the lawful `ready→running→failed` /
`pending→cancelled` path, emits `TASK_FAILED`, re-raises. Attempt tracking via
`_current_attempt_id`; `load_task_activity` returns attempts. Commits `f2fe4ce`.
Proof: `services/api/tests/integration/test_workflow_reconciliation.py`
(3 tests, real Temporal) + live scheduler smoke (both tasks `completed`,
leases honored).

### Live-found race (same objective): set-status idempotency

Live scheduler run failed healthy tasks:
`DomainError: Invalid task transition: running -> running` in
`set_task_status_activity` (attempt 3). Cause: `commit_scheduled`
(`services/api/app/services/orchestration/scheduler.py:242`) pre-claims tasks
as `running` before the workflow starts; the workflow's own set-to-`running`
then 422s, retries exhaust, reconciliation fails a healthy task.
Fix (`services/api/app/durable/activities/tasks.py:200`): same-state set is a
no-op success (already applied, not a transition — required under at-least-once
delivery). `TASK_TRANSITIONS` unchanged; genuine transitions still 422;
REST paths untouched.
Regression: `services/api/tests/unit/test_set_task_status_idempotent.py`
(no-op / lawful applies / unlawful still rejected).

## Objective C — verification provenance/events: FIXED + VERIFIED

Design: `docs/architecture/verification-provenance.md`.
`overseer.py:_source_provenance` captures `{source_head_sha, source_branch,
source_dirty}` at verify time into `validations.detail`; `verify_criterion`
emits `CRITERION_VERIFIED`; traceability criterion entries carry the
`verification` block; `RequirementOut.created_at` exposed (schemas + service).
No invalidation substrate exists by design — verification stays HISTORICAL;
status math unchanged (still VERIFIED); consumers compare
`source_head_sha` vs current HEAD. Commits `171b194`.
Proof: `test_quality_overseer.py` (provenance + event + DTO).

## Objective D — HITL / artifact investigations: OBSERVED, no code change

- HITL approve path proven live: `smoke_office.py` seeds a pending
  `hitl_requests` row, approves via the approval card, asserts the durable row
  flips to `approved`.
- Attempt evidence: live recovery runs record `evidence_artifact_ids` per
  attempt/finish; failures carry `failure_class`/`failure_detail`.
- By design, unchanged: artifacts have no FKs; `validations.created_at`
  history beyond latest is unexposed; no criterion→file dependency map
  (relevance cannot be determined safely — §10 conservative semantic kept).

## Live ladder clarification (recovery smoke, NOT a product change)

Scenario B asserted 2 parent attempts for a `TASK_FAILURE` doom command with
`max_attempts=2`. Implemented + unit-blessed policy
(`recovery.py:75-85`, `test_task_failure_spawns_debugger_on_final_retry`):
`attempts_left == 1` for TASK_FAILURE → `spawn_debugger` → Debug child +
parent terminal (1 parent attempt). The run demonstrated exactly this
(1 attempt + `Debug: Doomed command` child + terminal) — the smoke expectation
was stale, not the ladder.
Fix: scenario B now uses a TIMEOUT doom (hang + `timeout_seconds`), the class
with no last-attempt specialization, which runs the full budget and ends at
`escalate_or_replan`: 2 attempts + replan child + `TASK_REPLANNED` +
`TASK_TERMINALLY_FAILED` (REC-002/REC-003 as designed).

## Test-harness flexibility (backward-compatible defaults)

- `smoke_scheduler.py` / `smoke_recovery.py` / `smoke_office.py`:
  `SMOKE_BASE_URL` (was hardcoded `:8000`); scheduler tick now
  `raise_for_status` before indexing (was `KeyError: 'scheduled'` on 503s).
- `smoke_office.py`: `SMOKE_UI_URL`; vite `--port` derived from it.
- `apps/web-ui/vite.config.ts`: proxy target overridable via
  `VITE_API_TARGET` (default `:8000`; typed via `globalThis`, no new dep).

## Deferred / not supported

- No verification invalidation; no `validations.created_at` history endpoint;
  artifact FKs absent by design (see Objective D).
- `test_docker_runtime.py` excluded (needs docker daemon profile, as before).
- Dev-server note (pre-existing, untouched): two uvicorn processes on `:8000`
  (PIDs 56968 + 75976, both started 11:02:55); the listener accepts TCP but
  never responds (even `/healthz`). All gate validation above ran against
  isolated API instances; the owner should restart the dev server.
