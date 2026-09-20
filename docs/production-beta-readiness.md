# Production Beta Readiness (Wave 12)

Beta means: real projects, single operator, local-first. Not multi-tenant,
not unattended fleet use (see gaps).

## Beta scorecard (no single score)

| Dimension | Status | Evidence | Remaining Risk |
|---|---|---|---|
| Security | PASS | Wave 1 suite green; live docker network isolation proven; faults post-policy | Hour-scale adversarial soak not run |
| Reliability | PASS | Kill-9/NATS/DB-restart chaos; pause/resume proven; barrier-tested races | None above P3 |
| Agent orchestration | PASS WITH RISK | Scheduler, quotas, 8-agent stress (2+6), replacement chains | Autonomous planner quality unmeasured |
| Recovery | PASS | Ladders, fallback, budgets, debugger, rollback all executed in tests | None |
| Context | PASS | Bounded bundles; truncation markers; retrieval fixed + measured | None |
| Code intelligence | PASS | 2000-file exact retrieval; incremental 68 ms–0.1 s scale | 100k-symbol review outstanding |
| Runtime isolation | PASS | Live `--network none`, cap-drop, read-only proofs | Disk quota absent |
| Performance | PASS | Matrix in WAVE4_PERFORMANCE.md; history 83 events | 100k-volume review outstanding |
| Scalability | PASS WITH RISK | Quotas enforced; 8-way proven; 25–50 agent tiers not demonstrated | See envelope below |
| Cost control | PASS | Per-task/agent/invocation budgets; ladder always terminates | No live spend observed (rehearsal) |
| Requirement verification | PASS | Journey requirement → VERIFIED; ambiguity stays UNKNOWN | None |
| Observability | PASS | Metrics/logs/traces wired; diagnose-any-failure table | Alerts operator-owned |
| Realtime | PASS | Scenarios A–H; live-NATS e2e; multi-client convergence | Test-consumer hygiene manual |
| UI/UX | PASS | 3 smokes live; Problems/Settings/Runtime views; no placeholders | Per-agent controls absent by design |
| Accessibility | PASS | Focus/ARIA/reduced-motion verified | No full screen-reader audit |
| Evaluation | PASS | 10/10 baseline; triage; repeats; budgets | No evaluator model (deliberate) |
| Deployment | PASS WITH RISK | Checklist + config docs; `alembic current`; clean build | CI runs on push (not executed here); backups procedural |

## Beta decision

**GO for local-first single-operator beta** with `production-configuration.md`
applied (token set, CORS exact, retention chosen, backups rehearsed).
**Not yet**: multi-user, unattended, or high-scale fleet use.
