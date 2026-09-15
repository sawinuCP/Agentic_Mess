# Contributing

Scope: this is a single-maintainer local product, but the repo follows professional engineering
conventions so that it can scale to a team without a rewrite. The rules below are enforced by CI.

## Ground rules

1. **Never break the gates.** Before every commit: `powershell -File scripts\check.ps1` (ruff,
   mypy, pytest) and, for UI changes, `npm run lint && npm run build` in `apps/web-ui`.
2. **Layering is fixed** (dependencies point downward only):

   ```text
   routes (app/api/routes/<area>/)  thin: parse → call service → return. No business logic, no SQL.
                                    Grouped by area: core/ (health, events, artifacts),
                                    workspace/ (projects, files, git, terminal, toolchains),
                                    planning/ (requirements, plans, tasks),
                                    orchestration/ (agents, messages, knowledge, hitl, leases,
                                    scheduler, worktrees). Each subpackage exposes `routers`.
   schemas (app/schemas)            Pydantic request/response contracts, shared by routes+services.
   services (app/services)          one module per domain; business logic + persistence. No FastAPI
                                    imports; sync functions called via asyncio.to_thread.
   adapters/domains                 well-bounded packages wrapping external tools:
                                    app/files, app/gitops, app/toolchains, app/terminal,
                                    app/runtime, app/durable, app/artifacts, app/messaging,
                                    app/agents_runtime
   durable activities               app/durable/activities/ is a package split by concern
                                    (_context, tasks, agents, execution, hitl); the public
                                    activity names are re-exported from the package __init__.
   core (app/core)                  config, errors, logging, observability. No domain imports.
   db (app/db)                      SQLAlchemy models + engine. No domain logic.
   ```

   If you need a new dependency direction, stop and update ARCHITECTURE.md first.
3. **Errors**: raise `DomainError` (or a subclass) with an HTTP status — never return raw dicts,
   never swallow exceptions.
4. **Durable state lives in PostgreSQL**; never keep authoritative task/agent state only in
   memory. Events for consequential actions go through `app/services/events.record_event`.
5. **Security**: every client-supplied path passes through `ProjectFiles.resolve`; commands run
   through `app/runtime.runner`; secrets never enter logs or prompts.
6. **Types everywhere**: full annotations (mypy passes with `disallow_untyped_defs`).
7. **No hard-coded models, languages, or tool paths** — registry/config driven.

## Naming

- Test files are named for their **domain** (`test_leases.py`, `test_scheduler.py`,
  `test_agent_runtime.py`), never for the phase that introduced them.
- Frontend components live in `src/components/<area>/` (`editor/`, `panels/`, `shell/`).

## Adding an endpoint (checklist)

1. DTOs in `app/schemas/<domain>.py`
2. Logic in `app/services/<domain>.py` (sync, returns schema objects)
3. Thin route in the matching `app/api/routes/<area>/` module (`asyncio.to_thread` around service
   calls); register it in that subpackage's `routers` list
4. Record a durable event if the action is consequential
5. Tests: unit for service logic, integration for the endpoint (see `tests/`)

## Commit style

Imperative subject (`Phase N: deliverable` or `area: change`), body explaining what and why.
