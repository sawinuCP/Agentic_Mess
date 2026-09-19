# Wave 5 — Agent Evaluation & QA (factual report)

Status: **offline infrastructure evaluation implemented and green**. This wave did NOT
measure autonomous AI planning/implementation quality; see Limitations.

## What exists

Two evaluation modes, kept deliberately separate:

1. **Supplied-evidence audit** (`app/evaluation/runner.py`, `scorecard.py`): fail-closed
   scoring of evidence a caller supplies through the authenticated artifact API.
   Deterministic gates only — a model's positive assessment is not an input and can never
   override a failed test, missing artifact, security violation, or unverified mandatory
   requirement. Reports are persisted as project artifacts.
2. **Offline infrastructure suite** (`app/evaluation/suite.py`, `dataset.py`): executes a
   fixed, versioned 10-case catalog as real pytest processes against a **disposable
   Postgres database** (`isolation.py` — created and force-dropped per run, never the live
   project DB). Each case runs the repository's own trusted tests via the tool gateway's
   process runner (Wave 4 memory-bounded), with sanitized environments, per-case and
   per-run timeouts, and a provider-attempt model-call budget.

## Event → case mapping (EVAL-001..010)

| Case | Verifies (repository-owned evidence) |
|------|--------------------------------------|
| EVAL-001 Simple implementation | Seeded Python defect fails an independent oracle; scripted repair via tool gateway passes it (verify-before/after asserted) |
| EVAL-002 Multi-file | TS (tsc + node oracle, protected input untouched) and Go (`go test`) |
| EVAL-003 Parallel tasks | Scheduler tests + measured child-interval overlap with isolated outputs |
| EVAL-004 Dependency chain | DAG cycle/readiness tests + persisted dependent lookup |
| EVAL-005 Intentional test failure | Recovery classification, idempotent debugger/replan activities, bounded ladder |
| EVAL-006 Provider failure | Injected provider outage → bounded fallback; exhausted budget blocks execution |
| EVAL-007 Context challenge | Hybrid retrieval ranking + context tier/token budget tests |
| EVAL-008 Large repository | 200-file index, exact symbol search, single-file incremental reindex |
| EVAL-009 Security | Auth, stream scoping, secret sanitization, private-destination guards (no exploit execution) |
| EVAL-010 Requirement coverage | 4/5 verified criteria still block completion; hard gates intact |

## CLI

```
python -m app.evaluation list
python -m app.evaluation run --fast --output report.json          # EVAL-001
python -m app.evaluation run --full --output report.json          # all 10 cases
python -m app.evaluation run --case EVAL-005 --repeats 3 --output r.json
python -m app.evaluation report report.json
python -m app.evaluation compare before.json after.json
python -m app.evaluation persist report.json --project <uuid> [--api ...]
python -m app.evaluation audit evidence.json [--api ...]
```

Exit codes: 0 PASS, 1 FAIL, 2 ERROR (error type only — never inputs or credentials).
Reports are ≤1 MiB, written atomically, validated (`reports.validate`) against saved
per-test outcomes before summary/compare/persist; a verdict that contradicts its recorded
test outcomes is rejected.

## Measured results (local Windows machine, disposable DB, dirty worktree recorded)

- Baseline full run: **PASS, 10/10 cases, 96.47 s** (run `5eca4ea5-…`)
- Post-fix full run: **PASS, 10/10 cases, 76.28 s** (run `19350547-…`)
- Verification full run (2026-09-18): **PASS, 10/10 cases, 67.46 s** — rows now
  carry deterministic failure triage (`§39`: COST/INFRA/PERFORMANCE hard signals
  first, then failed-node evidence mapping; PASS rows carry none), surfaced in
  `report` tallies.
- `compare` between the two: **PASS, no regressions**; all cases faster (e.g. EVAL-002
  −797.5 ms, EVAL-005 −2067.5 ms median) — consistent with warm Go/TS tool caches.
- Repeatability (`--fast --repeats 2`): EVAL-001 **PASS, PASS** (not FLAKY);
  6814.7 ms / 6266.2 ms; metrics: model calls 0, tool calls 3 per repeat, cost $0.
- Budget enforcement: `test_provider_attempt_budget_stops_fallback` proves a 1-call
  budget fails the case (`BUDGET_EXCEEDED`) at the provider boundary — fallback
  attempts are counted, and `pytest.fail` propagates as FAIL, not ERROR.
- Full backend suite: **398 passed** (includes 7 golden fixtures + 53 evaluation tests).

## CI

- `python` job runs `python -m app.evaluation run --fast` on every push/PR.
- `evaluation-full` (manual `workflow_dispatch`) runs the full dataset with Go/Node setup
  and uploads the JSON report; it never calls paid models.

## Limitations (explicit)

- Cases execute **scripted repairs and repository tests**; they do not exercise the
  autonomous planner/spawning loop end-to-end. Orchestration dimensions (planning
  quality, context sufficiency, tool selection under autonomy) are **not yet measured**.
- Model-assisted evaluation is intentionally absent; no evaluator model can override
  deterministic failures. Adding one is future work.
- Latency metrics include pytest startup; they are regression baselines, not SLAs.

## Evaluation metrics library (2026-09-18)

`app/evaluation/metrics.py` — pure read-only extractors over durable rows for
reports (§12/§16/§42): `execution_metrics(task_id)` (attempts, retries + rate,
recoveries + success, replans, replacements, debugger spawns, tool calls +
success rate, model calls, tokens, cost, HITL count, terminal state; unavailable
splits stay `None`, never fabricated) and `communication_health(conversation_id)`
(orphan replies, duplicates, unanswered questions, undelivered). Covered by
`tests/integration/test_evaluation_metrics.py`.
