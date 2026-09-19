# Refactoring Baseline (Phase 0 — 2026-09-19)

Recorded before any structural analysis. No implementation changes made.

## Git state

* Branch: `master` (no dedicated refactoring branch created — 18 uncommitted
  Wave-12 paths exist in the tree; switching branches would disturb them.
  All Phase A–E work is documentation-only, so no branch is required yet.
  A branch MUST be created before any Phase F+ structural change.)
* HEAD: `e64e254 feat(acceptance): Wave 11 end-to-end production acceptance`
* Working tree: 18 modified/untracked paths (Wave 12 validation work) —
  intentionally untouched by this analysis.

## Test baseline (all green, zero failures)

| Suite | Result | Duration |
|---|---|---|
| Backend unit (`tests/unit`) | 311 passed | ~32 s |
| Backend integration (`tests/integration`, live PG/NATS/Temporal) | 217 passed | ~204 s |
| Backend evals (`tests/evals`) | 7 passed | ~18 s |
| Frontend (`vitest run`) | 144 passed | ~10 s |
| `ruff check` + `ruff format --check` | clean | — |
| `mypy app` | clean, 214 files | — |

No `PRE_EXISTING_FAILURE` entries: nothing fails at baseline.

## Migrations / startup

* `alembic current`: `0011 (head)` on the live harness DB.
* Backend startup, frontend build, and the eval baseline (10/10) were last
  verified green in Waves 11–12; not re-run for this docs-only phase beyond
  imports (no code changes to validate).

## Critical flows (last verified Wave 11/12)

Requirement → task → Temporal workflow → evidence → VERIFIED (journey test);
pause/resume; kill-9/NATS-loss/DB-restart chaos; HITL approve/timeout/cancel;
idempotent creates; realtime replay/resync; artifact ranges; rollback.
