# Production Release Checklist (Wave 11 §26)

Check each box with evidence (test name, measurement, or procedure run).
Unchecked boxes block release.

## Code

* [ ] Typecheck: `mypy app` clean (211 source files)
* [ ] Lint: `ruff check` + `ruff format --check` clean
* [ ] Build: `vite build` green (web-ui), backend imports clean
* [ ] Unit tests green (`tests/unit`)
* [ ] Integration tests green (`tests/integration`, live Postgres + NATS)
* [ ] E2E journey green (`test_e2e_journey.py`: requirement → VERIFIED)
* [ ] Temporal workflow tests green (`test_recovery_workflow.py`)
* [ ] Security tests green (`test_wave1_security.py`, `test_wave1_auth.py`, SSRF matrix)
* [ ] Evaluation suite: `python -m app.evaluation run --full` PASS + `compare` clean
* [ ] Performance budgets green (query-count tests, soak test, benchmark script)
* [ ] Frontend tests + Playwright smokes green (palette, office, task-controls)

## Infrastructure

* [ ] PostgreSQL reachable, migrations at head (`alembic current`)
* [ ] Redis reachable iff `HARNESS_REQUIRE_REDIS=true`
* [ ] NATS reachable iff delivery/events enabled
* [ ] Temporal reachable iff `HARNESS_TEMPORAL_ENABLED=true`
* [ ] Artifact storage writable (`/readyz` artifacts check ok)
* [ ] Observability: `/metrics` serves the realtime + HTTP series

## Security

* [ ] `HARNESS_API_TOKEN` set for any non-loopback bind (startup enforces)
* [ ] CORS allow-list exact, no wildcard
* [ ] Research private hosts denied (unless intranet deployment)
* [ ] MCP disabled or allow-listed; failure injection disabled
* [ ] Docker hardening intact (`--cap-drop ALL`, read-only, PID cap)

## Reliability

* [ ] Retry ladders terminate (exhaustion tests)
* [ ] Recovery executes end-to-end (workflow tests)
* [ ] Pause/resume/cancel paths tested
* [ ] Agent replacement drains + chains (replaces_agent_id)
* [ ] Reconnect + replay + DLQ verified
* [ ] Idempotency keys on creates; event dedup on redelivery
* [ ] Chaos battery green (kill-9, NATS loss, DB restart, backend kill)

## Product

* [ ] Command Center, Agent Office, Execution Graph, Timeline render recorded state
* [ ] Requirements + traceability agree with durable state (journey test)
* [ ] Editor, terminal, diff, evidence, HITL flows smoke-tested

## Operations

* [ ] Logs structured with correlation IDs; no secrets
* [ ] Metrics present (§22 list in `REALTIME_EVENTS.md`)
* [ ] Traces enabled if collector configured (opt-in)
* [ ] Backup procedure rehearsed (`disaster-recovery.md`)
* [ ] Retention windows explicitly chosen (defaults keep everything)
