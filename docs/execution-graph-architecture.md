# Execution Graph architecture — Wave 8

Status: contract inspection completed before implementation (paths cited).
The graph is a client-side projection over existing endpoints — **no new
backend endpoint**: every required read already exists. No new event system,
no new state manager, no graph library (hand-rolled SVG, one renderer).

## 1. Existing data sources (all real)

| Source | Frontend access | Used for |
|---|---|---|
| Traceability report | `getTraceability` (store) | requirements, criteria states, coverage, task_ids, evidence lists, `generated_at` version stamp |
| Raw requirements | `listRequirements` (lazy in GraphView) | description, desired_outcome, priority, version |
| Tasks | store | status, depends_on, requirement/plan links, attempts (agent, outcome, failure, evidence) |
| Agents | store | name/role/model/state, roster |
| Events (bounded 120) | store | `TOOL_RUN_COMPLETED` (test runs + tool paths), `GIT_COMMIT` (message + paths), recovery/degrader set |
| Worktrees | store (lazy) | branch, task link, integration status |
| Sessions | detail fetch | runtime visibility (not graphed) |
| Artifacts metadata | NEW client fn `getArtifact` (`GET /api/artifacts/{id}`, existing route) | evidence inspection (no backend change) |
| Git log | existing `gitLog` client (GitView) | NOT used for the graph — `GIT_COMMIT` events are realtime and sufficient |

## 2. Existing relationships (persisted vs derived)

Persisted (edge without qualification): requirement→task
(`tasks.requirement_id`), task→task (`task_dependencies`), task→agent
(`attempts.agent_id`), requirement→criterion, criterion→validation→evidence
(`validations`), task→evidence (success-attempt `evidence_artifact_ids`),
commit→file (`GIT_COMMIT` payload paths), test-run→evidence/file (same
`TOOL_RUN_COMPLETED` payload), worktree→task (`worktrees.task_id`).

Derived and LABELED as derived: task→commit — merge messages are
deterministic (`Integrate {branch} (worktree {id})`,
`routes/orchestration/worktrees.py:80`), so `GIT_COMMIT` messages parse to
(branch, worktree) → task. Parse failures simply yield no edge, never a
guessed one.

Absent (shown as labeled gaps, never fabricated): plan metadata (plans are
POST-only, no GET — no PLAN nodes; `plan_id` shown as task metadata),
criterion→task mapping (no column; criterion detail shows requirement-level
tasks labeled as such), task→file attribution (`TOOL_RUN_COMPLETED` carries
no task/agent id — file nodes attach to commits and test runs only),
per-test durability (tool runs are events; `Validation` rows exist only for
security/requirement kinds), commit SHAs in worktree rows (ephemeral
`IntegrationOut.commit`).

## 3. Node types (only types with real data)

`requirement` (overseer status VERIFIED/FAILED/UNKNOWN from the report —
never from task completion), `task` (10 lifecycle states), `agent`
(lifecycle state), `file` (commit paths + tool paths), `commit` (message +
time + paths), `test` (`TOOL_RUN_COMPLETED` with tool test/lint/build +
duration/exit), `evidence` (artifact ids from attempts/validations/tool
runs). No plan nodes, no validation nodes (criteria states live in the
requirement detail).

## 4. Edge types (semantic, each with a source)

`requirement→task` (planned for), `task→task` (depends on),
`task→agent` (executed by attempt), `task→evidence` (evidence recorded),
`test→evidence` (run produced), `test→file` (run targeted),
`commit→file` (commit changed), `evidence→requirement` (verifies, from
report lists), `task→commit` (DERIVED via merge-message parse, labeled).

## 5. API strategy

Zero new backend endpoints. The graph builds from the office snapshot the
realtime layer already maintains; requirement descriptions come from the
existing list endpoint; evidence metadata from the existing artifact
endpoint (new thin client fn). Requirement detail criterion→evidence uses
report-level lists labeled at requirement scope (§9 outcome: the missing
criterion-level mapping is identified and safely derived at requirement
granularity — no migration, which would be disproportionate).

## 6. Frontend state strategy

- Shared selection in `officeStore`: `selectedRequirementId` (new) alongside
  existing agent/task selection; `activityFilter` (new) seeds TimelineTab.
- Graph UI state (pan/zoom, filters, focus, search, graph/text mode) is
  LOCAL to GraphView — not global store.
- Graph data is a MEMOIZED pure build (`src/graph/build.ts`) over store
  slices; SSE envelopes flow through the existing reducer/resync, so updates
  are incremental and the server stays authoritative. Deterministic node/edge
  ids make duplicate events idempotent.
- Shell: `ViewId += "graph"` rendered in the main area (editor swaps out,
  sidebar/panel/shortcuts preserved); sidebar keeps the Office for context.

## 7. Filtering strategy

Type, status, scope (requirement/task/agent focus), failures-only, search.
Filters hide nodes; edges require both endpoints visible; a "hidden by
filters" count prevents misleading emptiness. Type/status are hard filters;
scope/failures/search are focus lenses whose 1-hop neighborhood survives
(type/status permitting), so focus never manufactures disconnected edges.
Focus modes keep the full failure/requirement path in context. Filtering
never mutates the built graph.

## 8. Performance strategy

Bounded inputs (120 events, 200 messages unused here, file nodes capped at
150 with an honest "+N more" affordance, evidence capped at 200);
progressive disclosure (files/tests/evidence lanes render for the focused
requirement, counts elsewhere); O(n) pure build memoized on slice identity;
SVG scales to hundreds of nodes without virtualization (measured, see
performance doc). No polling; no rebuild per event beyond the memoized
projection.

## 9. Missing backend relationships (explicit)

Plan reads, criterion→task edges, task→file attribution, durable test runs,
worktree merge SHAs, validation listing. Each is surfaced in-UI as a labeled
limitation where it matters. None blocks the Wave 8 questions.

## 10. Security considerations

Project isolation via existing store guards; artifact metadata only (content
loads nowhere in the graph); message/evidence payload VALUES never rendered
(keys only, per Wave 7); no secrets in labels/titles; existing auth headers
on every fetch; file-open reuses the workspace-scoped `openFile` (no
path-escape UI of its own).
