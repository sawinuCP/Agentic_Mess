# Use Cases (Phase C)

Reconstructed from the implementation (routes, workflows, tests, UI). Each:
Actor / Trigger / Main flow / Failure flow / Evidence. Preconditions assume an
open project unless noted. All flows below are test-covered (see Tests).

## UC-01 Create/Open Project
Actor: operator. Trigger: Open-project dialog / API. Flow: root path →
`POST /api/projects/open` (idempotent by path) → indexing → Explorer loads.
Failure: invalid root → 422 with reason. Evidence: `PROJECT_OPENED` event.

## UC-02 Submit Engineering Requirement
Actor: operator. Trigger: requirement form / API. Flow: title + mandatory
criteria → `REQUIREMENT_CREATED`. Failure: vague text accepted (ambiguity is
allowed) but stays UNKNOWN without evidence — never auto-verified.

## UC-03 Plan Requirement
Actor: operator/planner. Trigger: plan endpoint with task list. Flow: DAG
validated (unknown/foreign deps and cycles rejected) → plan + tasks created.
Failure: bad links → 422, nothing persisted.

## UC-04 Dynamically Spawn Agents
Actor: workflow/operator. Trigger: attempt start / spawn dialog / API.
Flow: role → capability scopes granted → agent row + session + `AGENT_CREATED`.
Failure: unknown role falls back to worker route; invalid data → 422.

## UC-05 Parallel Agent Execution
Actor: scheduler/workflow. Trigger: tick / independent tasks. Flow: quota
slots acquired → concurrent attempts → isolated ledgers; excess defers with
`QUOTA_EXCEEDED` (never crashes). Evidence: 8-agent stress test (2+6).

## UC-06 Agent Communication
Actor: agents/operator. Trigger: message send. Flow: durable row → NATS
fan-out → recipient inbox / SSE. Operator composes with null-sender
attribution only. Failure: broker down → 503, row stays pending, replay later.

## UC-07 Agent Tool Execution
Actor: agent. Trigger: model decision → RUN markers. Flow: capability check →
allowlist → deny/approval patterns → HITL if gated → run (local/docker) →
compressed observation + evidence artifact → `TOOL_STARTED/COMPLETED/FAILED`.
Failure: denial → `SECURITY_BLOCK` outcome (never an escaping exception).

## UC-08 Agent Waiting on Dependency
Actor: workflow. Trigger: `DEPENDENCY_FAILURE`. Flow: unfinished pre-check →
`blocked` + durable signal wait (no busy loop) → dependency completes →
signal → resume; deadline → terminal. Evidence: signal + pre-check tests.

## UC-09 Agent Failure and Recovery
Actor: workflow. Trigger: failed attempt. Flow: classify → deterministic
decision → bounded action (retry/backoff/compact/switch/replace/debugger/
replan/wait/HITL/terminal). Evidence: `RECOVERY_SELECTED` + history; ladder
tests prove termination.

## UC-10 Model Failure and Fallback
Actor: registry. Trigger: transient provider error. Flow: bounded retries with
jitter → configured `fallback_role` once → terminal/HITL if exhausted. Budgets
checked first. Never an unapproved provider. Evidence: fallback tests.

## UC-11 HITL Approval
Actor: operator. Trigger: gated command / expensive recovery / resource strain.
Flow: durable request (what/why/options/evidence) → approve/reject/timeout/
cancel → workflow continues or terminates. Concurrent deciders: exactly one
winner (row-locked). UI: approval cards with notes + lockout.

## UC-12 Pause Execution
Actor: operator. Trigger: pause signal. Flow: checkpoint parks between
activities (`running → pause_requested → paused`, lawful transitions) →
`wait_condition`. Evidence: pause test (agent reaches paused).

## UC-13 Resume Execution
Actor: operator. Trigger: resume signal. Flow: `resuming → running` (lawful)
→ attempt continues, never re-runs. Evidence: 1-attempt completion after resume.

## UC-14 Requirement Verification
Actor: overseer/operator. Trigger: evidence submitted. Flow: validation record
→ criterion `verified` → requirement VERIFIED only if all mandatory verified.
Failure: missing evidence → blocked gate (409); vague → UNKNOWN forever.

## UC-15 Code Validation
Actor: toolchain service. Trigger: run/test/lint/build/format. Flow: detected
languages → argv-only execution → compressed observation + diagnostics.
Failure: exit ≠ 0 → failed outcome with stderr excerpt (classifier food).

## UC-16 Browser Validation
Actor: agent/operator. Trigger: browser session + Playwright script. Flow:
isolated session → screenshots as artifacts → observations. Opt-in only.

## UC-17 MCP Tool Execution
Actor: agent. Trigger: allow-listed MCP call. Flow: registry → server →
observation. Failure: unknown server → 503; gateway off by default.

## UC-18 Web Research
Actor: agent. Trigger: research query. Flow: DNS-aware SSRF guard → bounded
fetch → per-hop redirect revalidation → evidence artifact. Private nets denied
by default.

## UC-19 Agent Office Monitoring
Actor: operator. Trigger: open office. Flow: authoritative snapshot → SSE
incremental projection (dedupe/ordering) → targeted renders; degraded mode
falls back to visible slow resync. Evidence: smokes + reducer tests.

## UC-20 Execution Graph
Actor: operator. Trigger: open graph. Flow: persisted REQ→TASK→dependency
edges built by pure `graph/build.ts` (no derived edges without evidence).
Failure: missing links render as absent, never invented.

## UC-21 Timeline Replay
Actor: operator. Trigger: replay chip. Flow: bounded feed stepped oldest-first
with controls; panels keep showing CURRENT state (no fake history). New
arrivals disclosed; reduced-motion gets step-only controls.

## UC-22 Evidence Inspection
Actor: operator. Trigger: artifact reference. Flow: metadata → ranged content
streaming (206/416) → viewer. Pruned blobs 404 honestly (never fake success).

## UC-23 Command Center
Actor: operator. Trigger: Ask AI / intents. Flow: deterministic intent routing
over project data (costs, context, symbols) → grounded answers with refs.
No free-form model chat claims beyond the router's evidence.

## UC-24 Cost Monitoring
Actor: operator. Trigger: costs surfaces. Flow: per-task/agent ledger →
budgets gate execution AND recovery → over-budget stops with scope-carrying
event. UI: per-task + project tokens/calls.

## UC-25 Execution History
Actor: operator. Trigger: history view. Flow: paginated durable events
(500/page) with search + true replay entry; realtime feed stays a bounded
projection beside it, never a replacement.
