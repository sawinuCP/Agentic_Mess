# Refactoring Plan (Phase E — for review; NOT started)

Batches are small, ordered, independently committable. Every batch ends with:
unit + integration + evals + frontend tests, ruff/format/mypy, build, alembic
`current`, and the affected smokes. Rollback = `git revert` per batch commit.

## R-00 Delete ignored debug logs (P3)
Current: root `tmp-w3-*.log` (3 files, git-ignored clutter).
Target: deleted. Files: those 3 only. Risk: none (ignored, regenerated never).
Tests: none needed. Rollback: n/a.

## R-01 Documentation hierarchy (P3)
Current: 38 flat docs + spec pair (.md + .docx).
Target: `docs/architecture/` entry point (done in Phase D) + `README` links;
mark wave/audit docs historical-by-date (headers, no moves — moves break
external links). Files: docs only. Risk: negligible. Tests: docs link check.

## R-02 Boundary regression tests (P1)
Current: domain purity (`agents_runtime/` has no sqlalchemy/db imports;
`workflows.py` imports only `timedelta` + pure policy) holds by convention.
Target: two unit tests asserting it (AST import scan): no `app.db`/sqlalchemy
in `agents_runtime/*`; no `datetime.now`/`random`/`uuid4` in `workflows.py`.
Files: +2 test files. Risk: none (additive). Tests: themselves.

## R-03 Services↔models coupling discipline (P2, ongoing)
Current: services import ORM models directly (56 inbound on the barrel).
Target: NO big-bang repository layer. Rule: new cross-context writes go
through owner-context functions; add read/write repository helpers per
context only where churn justifies it. Files: as-touched. Risk: low (additive).

## R-04 Frontend direct-fetch audit (P2)
Current: views must use `api/client`; thin legacy exceptions may exist.
Target: grep-audit + route stragglers through the client; add client fns
(ports/leases pattern) rather than inline fetch. Files: as-found. Risk: low.
Tests: existing smokes cover the touched views.

## R-05 Dependency audit (P3)
Current: single `pyproject.toml` + `package.json`/lockfile; no sprawl found.
Target: install-graph proof of use for flagged deps; remove only with a
passing full build+test after. Files: manifests only. Risk: low. Tests: full
gates.

## R-06 Event-type naming (P3 — likely DECLINE)
Current: `TOOL_RUN_COMPLETED` (toolchain runs) vs `TOOL_*` (agent commands)
overlap in name only; semantics differ.
Target: most likely DOCUMENT-only (renaming emitted types breaks historical
queries). Decision required in review: rename with backfill, or keep.

## Explicitly declined
* Microservices split; Clean-Architecture layer rewrite; repository-pattern
  port; frontend router/rewrites; migration history rewrite; `TOOL_*` rename
  without backfill decision. Reasons in target-architecture.md.

## Order
R-00 → R-02 (both trivial, either order) → R-01 → R-04 → R-05 → R-03
(ongoing) → R-06 decision. No batch touches more than one architectural
boundary (Rule 11).
