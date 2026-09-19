# Architecture Overview (authoritative entry point)

AI Harness is a local-first AI software-engineering platform: a FastAPI
modular monolith (`services/api/app/`), a React 18 + Vite + Zustand desktop
UI (`apps/web-ui/src/`), PostgreSQL as the sole source of truth, NATS for
live event transport, Temporal (opt-in) for durable execution, Redis for
health-checks only.

Start here, then follow the links. Historical wave docs remain valid for
their subject; this hierarchy resolves conflicts (newer + this tree win).

* Original full architecture (Sep 16, pre-waves-7–12): root `ARCHITECTURE.md`
  — historical reference; validated claims live in the wave docs below.
* Product: `AI_HARNESS_PRODUCT_SPEC.md`, `REQUIREMENTS_MATRIX.md`
* This refactoring: `docs/refactoring/` (BASELINE → inventory → capabilities →
  matrix → use-cases → data-flow → target → plan → risks)
* Operations: `OPERATIONS.md`, `operational-runbook.md`, `disaster-recovery.md`
* Security: `SECURITY_RISK_REGISTER.md`, Wave 1 validation
* Realtime: `REALTIME_EVENTS.md` · Recovery: `RECOVERY.md`
* Decisions: `docs/architecture/decisions/`
