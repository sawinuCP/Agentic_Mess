# AI Harness Code Editor

A durable, locally runnable **AI-native code editor and agentic software-engineering platform**.
Users describe a software requirement; the harness plans work, dynamically creates agents,
executes them in isolated workspaces with controlled tools, verifies results with evidence,
and keeps humans in control — all inside a professional code editor.

> **Status:** Phase 5 complete — agent runtime + multi-agent orchestration + code intelligence (see [`IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md)).
> The specification is authoritative: `AI_Harness_Code_Editor_Complete_Implementation_Specification.md`.

## What works today (Phases 1–4)

- Open local projects (registered in PostgreSQL), browse with the file explorer
- Edit with Monaco (tabs, dirty tracking, Ctrl+S, quick-open Ctrl+P) — fully usable without AI
- Search across the project (regex/case options, click-to-line)
- Git basics: status, stage/unstage, commit, log, branches, checkout, init, HEAD↔worktree diff
- Language toolchains: auto-detection (Python, JS/TS, Go, Rust, C#), per-project overrides
  (`.ai-harness/toolchains.json`), format/run/test/build with missing-tool diagnostics
- Integrated terminals: real PTY (PowerShell on Windows) over WebSocket with xterm.js
- Agent runtime: 14-state lifecycle, rehearsal/offline + OpenAI-compatible model providers with
  fallback escalation, tool gateway (allowlists, deny + approval-required patterns → HITL),
  RTK-style observation compression, tiered context broker with token budgets
- Durable orchestration: Temporal task execution with bounded attempts + evidence artifacts,
  pause/resume signals, bounded scheduler (global/role concurrency, lease-aware), dynamic spawn policy
- Multi-agent plumbing: TTL resource leases with renewal, NATS JetStream message fan-out
  (opt-in), git worktree isolation with a controlled integration queue (conflicts → explicit tasks)
- Code intelligence: tree-sitter/ast symbol index with incremental updates, hybrid
  lexical+semantic retrieval feeding agent context, SCIP-JSON export, model cost ledger
- Health/readiness endpoints, durable event stream, structured JSON logs, opt-in OpenTelemetry

## Quickstart (local development)

Prerequisites: Python 3.11+, Node 22+, Docker Desktop, Git.

```powershell
# 1. Start local infrastructure (PostgreSQL + Redis + NATS)
docker compose up -d postgres redis nats

# 2. Python control plane
python -m venv .venv
.venv\Scripts\pip install -e "services/api[dev]"

# 3. Apply migrations (services/api is the working directory for alembic)
Push-Location services/api
..\..\.venv\Scripts\alembic upgrade head
Pop-Location

# 4. Run the API
.venv\Scripts\uvicorn app.main:app --reload --port 8000 --app-dir services/api

# 5. Run the web UI
cd apps\web-ui
npm install
npm run dev                                                        # http://localhost:5173
```

Quality gates (same as CI): `powershell -File scripts\check.ps1`

## Repository layout

```text
apps/web-ui/          React + TypeScript UI (Monaco editor arrives in Phase 1)
services/api/         FastAPI control plane (modular monolith; module map in ARCHITECTURE.md)
infrastructure/       Local infra config (OTel collector, later: docker/temporal/nats assets)
docs/                 Requirements matrix and engineering docs
scripts/              Developer helper scripts
```

## Documentation

| Document                                             | Purpose                                        |
| ---------------------------------------------------- | ---------------------------------------------- |
| [`ARCHITECTURE.md`](ARCHITECTURE.md)                 | Target architecture, decisions, risks          |
| [`IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md)| Phase tracking and honest NOT_IMPLEMENTED list |
| [`DEVELOPMENT.md`](DEVELOPMENT.md)                   | Setup, commands, migrations, extension guides  |
| [`docs/REQUIREMENTS_MATRIX.md`](docs/REQUIREMENTS_MATRIX.md) | Requirement → subsystem → status matrix |
