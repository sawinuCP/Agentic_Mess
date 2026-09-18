# Requirement traceability — Wave 8

How the product answers: **"Why is this requirement considered complete,
and what evidence proves it?"**

## Verification rules (from `services/quality/overseer.py`)

Criterion states (lowercase) are the OR of the stored
`acceptance_criteria.status` and durable `validations` rows, with `failed`
taking precedence. Requirement states (uppercase) derive as:

- `VERIFIED` — tasks exist, mandatory criteria exist, and ALL mandatory
  criteria are `verified`.
- `FAILED` — any mandatory criterion is `failed`.
- `UNKNOWN` — everything else, **including** completed tasks whose criteria
  were never validated, and verified criteria with zero tasks.

Task `COMPLETED` therefore never implies requirement `VERIFIED`. The UI
renders both side by side (`Task: COMPLETED / Requirement: UNKNOWN`) and
explains the distinction wherever a verdict appears.

## The traceability chain (what links what)

```
Requirement ──planned for──▶ Tasks ──depends on──▶ Tasks
     │                           │──executed by──▶ Agents
     │                           │──evidence recorded──▶ Evidence ──verifies──▶ Requirement
     │                           └──integrated as──▶ Commit ──changed──▶ Files
     │                                                    (derived from merge messages, labeled)
Test runs ──targeted──▶ Files    Test runs ──produced──▶ Evidence
```

- Requirement → task: `tasks.requirement_id` FK. Tasks without it are
  **unlinked** — shown in a labeled group, never silently attached.
- Task → agent: `attempts.agent_id`. Agents without attempts don't appear.
- Criterion → task: **not persisted anywhere** (`acceptance_criteria` has no
  task/evidence columns; `Task.acceptance_criteria` JSONB is never written).
  Criterion detail therefore shows requirement-level tasks and evidence with
  an explicit "associated at requirement level — no criterion-level mapping
  is recorded" note. No migration was added: the durable change would be
  disproportionate to the display need, and the §9 procedure (identify →
  derive safely at requirement granularity → document) is followed instead.
- Criterion → evidence: only via `Validation` rows (created by the verify
  endpoint or security scans). Attempt evidence alone never verifies —
  surfaced as evidence, never as verification.
- Task → file: not persisted (`TOOL_RUN_COMPLETED` carries no task/agent
  id). Files attach to the commits and test runs that recorded their paths;
  the graph states this limitation on every file node.
- Task → commit: derived from deterministic integration messages
  (`Integrate {branch} (worktree {id})`), dashed and labeled "derived";
  unparseable messages yield no edge. Worktree → task is a real FK shown in
  task details.
- Plans: POST-only, no read endpoint — no plan nodes; `plan_id` appears as
  task metadata only.

## UNKNOWN semantics

UNKNOWN is a first-class verdict (warn tone, never muted into success):
unvalidated criteria, evidence without validation, completed tasks awaiting
verification, and missing index data (symbols/files) all render as UNKNOWN
or "not recorded". Filters and coverage count UNKNOWN explicitly.

## Evidence inspection

Evidence nodes resolve artifact metadata (`GET /api/artifacts/{id}`: name,
kind, MIME, size, SHA-256) on demand; raw content is never pulled into
graph state. Missing artifacts (404) render "no longer stored" instead of
breaking the chain. Payload *values* are never rendered (keys only) so
secrets cannot leak through the graph.

## Realtime behavior

The graph rebuilds memo-per-snapshot from the office store: SSE envelopes
project through the existing reducer (deduplicated, gap-checked, resynced),
so requirement/task/agent states update live and the server stays
authoritative. Deterministic node/edge ids make duplicate deliveries
idempotent (unit-tested). A full reload replays the authoritative snapshot
— verified in the browser smoke by mutating a fixture and reloading.

## Performance

Bounded inputs (120 events, 150 files / 200 evidence with honest "+N more"
disclosure), progressive disclosure by requirement focus, O(n) memoized
build, SVG rendering without virtualization. Measured
(`src/graph/build.test.ts`): 500 tasks + 120 events → 909 nodes / 1403
edges built, failure-filtered, and laid out in 343 ms node-side; unit bound
5 s guards against quadratic blowups. The numbers above are derivation only
— browser frame timing for thousand-node SVGs remains unprofiled, and the
focus/type filters exist precisely to keep the rendered set small.

## Known limitations

- No plan nodes or plan reads (POST-only backend).
- No criterion-level task/evidence mapping (see above).
- No per-test durability beyond the event feed (only security/requirement
  `Validation` rows persist).
- No commit-range diff view (commit nodes link files into the existing
  editor; history beyond `HEAD`-vs-worktree diffs is out of scope).
- Timeline has no requirement-scoped filter (events carry no
  `requirement_id`); "View activity" seeds agent/task filters only.
- The graph lives in the main area with the Office in the sidebar; a
  three-pane desktop arrangement remains a future shell wave.
