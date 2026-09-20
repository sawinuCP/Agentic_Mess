# Phase G Baseline (G0 — 2026-09-19)

## Freeze state

* HEAD: `63ab41e refactor(docs): Phase F results and validation record`
* Working tree: 18 uncommitted Wave-12 paths (implementation + docs) —
  **boundary: do not modify** unless a demonstrated dependency/correctness
  issue forces it. All Phase G work must leave these paths byte-identical
  (verified at the end via `git status` + targeted diff).
* Branch: `master` (no new branch: Phase G commits go on top; Wave-12 work
  stays uncommitted and separate).

## Baseline measurements (Phase F validation, same tree)

| Suite | Result |
|---|---|
| Backend unit | 315 passed (incl. 4 boundary tests) |
| Backend integration (live PG/NATS/Temporal/Docker) | 217 passed |
| Backend evals | 7 passed |
| Frontend vitest | 144 passed |
| `ruff check` + `ruff format --check` | clean (319 files) |
| `mypy app` | clean (214 files) |
| ESLint / `tsc` / vite build | 0 errors / clean / green |
| Alembic | 0011 head |

## Critical smokes (last green: Wave 6/11 rounds)

Palette, office, task-controls Playwright smokes green against live stack.
Full 19-smoke battery wired but not re-run here (time-boxed; run on demand).

## Known failures at baseline

None. Zero `PRE_EXISTING_FAILURE` entries.
