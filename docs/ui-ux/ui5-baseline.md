# UI-5 Baseline — Causality & Engineering Investigation Experience (UI5-01)

Date: 2026-09-21. Method: source reads (no production code changed).
Gate inputs: `ui4-5-validation.md` (READY WITH DATA GAPS), backend hardening
final report (READY for UI-5). No new backend, store, router, or library.

## 1. Current graph implementation

- `components/graph/GraphView.tsx` (526 lines): main-area view, memoized pure
  projection over the office snapshot. No graph library, no polling, no fetch
  except `listRequirements` + `loadWorktrees`.
- `components/graph/GraphDetail.tsx` (398 lines): side inspector per node type.
- `graph/build.ts` (722 lines, no React): `buildGraph`, `filterGraph`,
  `coverageCounts`, `failureTrace`, `textTree`, `layoutGraph`.
- Rendering: custom SVG, column layout (requirements x=0, tasks by
  dependency depth, agents, then file/commit/test/evidence lanes). Wheel zoom,
  keyboard `+/-/0/arrows`, pan on empty canvas only. Node click/Enter/Space
  selects; 1-hop neighbor dimming. `graph`/`text` mode toggle (text = per-
  requirement chain + unlinked tasks). Filters: type chips, failures-only,
  focus requirement/task/agent selects, search query.
- Tests: `graph/build.test.ts` (353 lines) — merge-parse, persisted links,
  `derived:true`, caps, idempotence, filters, failureTrace, textTree, layout
  determinism, 500-task `<5s` budget.

## 2. Data sources (no dedicated graph endpoint)

`useOffice` snapshot (tasks/agents/events/traceability/worktrees) +
`GET /api/projects/{id}/requirements` + traceability
`GET .../oversight/traceability` (loaded in `officeStore.resync`).
Artifacts on demand via `ArtifactMetaView` (`GET /api/artifacts/{id}`).

## 3. Node types (7)

`requirement` (traceability rows), `task` (all tasks), `agent` (all agents),
`file` (union of test/commit paths, cap 150), `commit` (`GIT_COMMIT` events),
`test` (`TOOL_RUN_COMPLETED` with tool in {test,lint,build}),
`evidence` (union of attempt/requirement/test artifact ids, cap 200).

## 4. Edge types (9) → UI-5 authority classification

| Edge | Built from | UI-5 authority |
|---|---|---|
| `planned for` req→task | `task.requirement_id` FK | PERSISTED |
| `depends on` task→task | `task_dependencies` | PERSISTED |
| `executed by` task→agent | `task_attempts.agent_id` | PERSISTED |
| `evidence recorded` task→evidence | `attempt.evidence_artifact_ids` lists | PERSISTED |
| `verifies` evidence→req | validation evidence lists | PERSISTED |
| `produced` test→evidence | event payload `artifact_ids` | EVENT-DERIVED |
| `targeted` test→file | event payload `path` | EVENT-DERIVED |
| `changed` commit→file | event payload `paths` | EVENT-DERIVED |
| `integrated as` task→commit | merge-message regex + worktree | INFERRED (keeps `derived:true`) |

Current code flags ONLY the commit edge (`derived?: boolean`, amber dash +
title). All other edges render identical muted solids — the core UI-5 gap:
no visual authority distinction anywhere.

## 5. Verification data available (unused by graph)

Traceability criterion entries carry `verification: {validation_id,
verified_at, status, evidence_artifact_id, task_id, source_head_sha,
source_branch, source_dirty} | null` (`overseer.py:50-71,101`). The frontend
`TraceabilityCriterion` type (`types.ts:267`) does NOT declare it — runtime
present, type absent. No requirement-verified/invalidated events exist; no
invalidation substrate; verification stays HISTORICAL (hardening gate).

## 6. Existing investigation pieces (reuse, don't fork)

- `failureTrace` (`build.ts:533`) + `FailurePath` (`GraphDetail.tsx:368`):
  req→task→agents→recovery events→retry→verdict, clickable nodeIds.
- `waitingReason` / `waitingSince` / `recoveryState` (`office/selectors.ts`).
- `textTree` per-requirement chain (screen-reader path).
- `RequirementDetail`/`TaskDetail` in GraphDetail with Office/timeline/
  editor jumps (`openInOffice`, `viewActivity`, `openFile`).
- ContextPanel: agent/task/requirement/file summaries keyed off office
  selection (`ContextPanel.tsx`); graph `select()` already syncs office
  selection both ways (`GraphView.tsx:151-161`).
- Navigation: `ViewId` + `useStore.set` / `useOffice.set`; no router.
  Requirements view notes graph/detail jumps land there
  (`RequirementsView.tsx:5`).

## 7. Limitations (UI-5 scope)

1. No authority model beyond one boolean; no legend; edges imply equal weight.
2. No focus/investigate mode: whole-project render + filter lenses only; no
   expand/collapse; no per-object bounded neighborhood (§6 trees missing).
3. No "why" panel: no WHY VERIFIED/UNKNOWN/FAILED chain; provenance block
   untyped and unconsumed; honesty wording ("recorded verification point")
   absent.
4. Attempt vs execution vs tool-call undistinguished in task view (attempt
   rows exist in `TaskInfo.attempts` but graph has no attempt nodes — by
   design: attempts render inside task detail, not as nodes).
5. File/test nodes unattributed (server-side truth); feed-bounded nodes
   vanish without in-graph disclosure (only filter counts disclosed).
6. Filters lost on unmount; zoom resets on data arrival (`fit` on dims
   change); pan undiscoverable; labels 22ch truncated.
7. Text tree covers requirement chains only (no failure/verification chains).

## 8. Missing data (UNAVAILABLE — document, don't invent)

Criterion→evidence standing link (binding is action-time); verification
history/events; invalidation/staleness; in-progress tool activity;
attempt→agent session; USD/per-agent cost; approval scope/impact.

## 9. Performance characteristics

Memoized build/filter/layout; caps 150 files / 200 evidence with counts;
500-task build budget `<5s` (tested); derivations pure. Strategy: shrink
visible neighborhood (focus mode), no virtualization without evidence.

## 10. UI5 commit plan

UI5-02 authority model (edge `authority` + legend + tests) → UI5-03 focus/
investigate + expand/collapse → UI5-04 why-panel requirement/task →
UI5-05 agent/failure/recovery → UI5-06 evidence/verification chain →
UI5-07 cross-surface jumps → UI5-08 responsive/a11y/perf →
UI5-09 regression + `ui5-final-report.md`.
