# Backend Trust Hardening — Final Report (Pre-UI-5 Gate)

Date: 2026-09-21. Full record: `docs/architecture/backend-trust-hardening.md`.

## Verdict: READY for UI-5 (with the data gaps already recorded in UI-4.5)

No objective reframes UI state beyond what the backend proves. Two live
findings surfaced during validation; both are fixed with regression tests
(see record). No public contract changed (REST/SSE/envelope schemas,
`TASK_TRANSITIONS`, agent lifecycle, recovery policy intact).

## Validation matrix (all green 2026-09-21)

| Check | Result |
|---|---|
| `ruff check` backend | clean |
| `mypy app` | clean |
| unit (`tests/unit`) | 328 passed (incl. 3 new idempotency tests) |
| integration (`tests/integration`, excl. `test_docker_runtime.py`) | 222 passed |
| evals (`tests/evals`) | 7 passed |
| frontend `tsc --noEmit` / `eslint src --quiet` | 0 errors |
| frontend `vitest` | 166 passed |
| `vite build` | success |
| `alembic` | head 0011 (no new migration needed) |
| UI smokes (mocked vite) | oversight, editor, task_controls, agent_office, command_center, graph, history, panel_retention, shell_status, command_palette — PASS |
| `smoke_office.py` (real UI + isolated API) | PASS (HITL approve → durable `approved`, gate fail-closed, timeline, palette views) |
| `smoke_scheduler.py` (live Temporal: worker + `HARNESS_TEMPORAL_ENABLED=true`) | PASS (tick #1 schedules free / skips leased; release → tick #2 completes blocked; 0 running, 2 completed) |
| `smoke_recovery.py` (live Temporal) | PASS (A: transient fails once → retried → completed, 2 attempts; B: TIMEOUT ×2 → replan child + terminal with evidence) |

Fail-closed postures confirmed live: scheduler tick and task execute return
503 without Temporal (never schedule what cannot be durably started);
policy denials flow to `SECURITY_BLOCK` → terminal, never a stuck `running`.

## Invariant coverage

1. Success path durable end-to-end — scheduler smoke, both tasks `completed`.
2. Retryable failure reconciled, attempts persisted — recovery A (2 attempts,
   `RETRY_STARTED`, `RECOVERY_SELECTED`).
3. Terminal failure reconciled, no orphaned `running` — recovery B +
   `test_workflow_reconciliation.py`.
4. Cancel/timeout lawful — TIMEOUT ladder live (B); cancel covered by
   reconciliation tests.
5. Verify success/failure provenance — `test_quality_overseer.py`.
6. No duplicate terminal events on retry — idempotency keys
   (`snapshot:`/`terminal:`/`replan:`/`child:`) + same-state set no-op.
7. Source-change-after-verify stays historical — provenance design
   (no invalidation substrate; UI renders HEAD comparison, never FAILED).

## Residual risks (accepted)

- Stray-worker lesson: duplicate pollers on `ai-harness-tasks` steal and fail
  tasks (an old-code orphan caused three false-red runs). Single-worker
  discipline for the task queue; the AST registration guard stays.
- `:8000` dev server wedged (pre-existing double-launch) — owner action.
- `test_docker_runtime.py` remains environment-gated, as before.

STOP — gate complete. UI-5 may start.
