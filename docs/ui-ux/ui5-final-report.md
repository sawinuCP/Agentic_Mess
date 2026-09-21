# UI-5 Final Report

Date: 2026-09-21. Method: continued the committed UI5-01..08 series; this gate
(UI5-09) re-ran the full regression, executed live-browser QA on real backend
data with real Chromium, fixed one graph-detail defect and two smoke-locator
drifts it surfaced, and records the deliverable below.

## 1. Objective

Ship the Engineering Investigation Experience: the graph answers "why did the
system reach this result" — requirement → criterion → task → agent → attempt →
change → validation → evidence → verification — with every relationship's
authority explicit, without inventing data and without duplicating Requirements,
Agent Office, Timeline, or Artifact surfaces.

## 2. Baseline

`docs/ui-ux/ui5-baseline.md` (UI5-01): 7 node types, 9 edge types, only the
commit edge carried any provenance flag; no focus mode, no why-panel, no
legend, provenance type absent in the frontend. Backend hardening gate
(READY for UI-5) had already added durable verification provenance
(`verified_at`, source sha/branch/dirty), criterion events, workflow-failure
reconciliation, and the worker activity registration.

## 3. Graph Data Model

Unchanged architecture: pure projection in `graph/build.ts` (no React, no
fetch) over the existing office snapshot (`useOffice`: tasks, agents, events,
traceability, worktrees) plus `GET /api/projects/{id}/requirements`. No graph
backend, no graph database, no new store, no new router, no graph library.
UI-5 additions: `authority` on every edge, `EDGE_EXPLANATION` registry,
`investigationNeighborhood` (BFS, bounded), `explain.ts` (deterministic
investigation chains), `WhyPanel`, `FailurePath` in the detail panel.

## 4. Authority Model

Vocabulary from UI-4.5, defined at `GraphAuthority`:
**PERSISTED** (durable row/FK), **EVENT-DERIVED** (assembled from durable
events, feed-bounded), **INFERRED** (heuristic), **DERIVED**/**UNAVAILABLE**
(reserved; no built edge uses them today — documented, not faked). Every edge
is stamped by `makeEdge` from the `EDGE_EXPLANATION` registry — hand-rolled
authority is impossible. Displayed via: edge line treatment (solid = persisted,
long-dash = event-derived, amber short-dash = inferred), edge `<title>`
(`"{type} — {AUTHORITY}: {reason}"`), toolbar legend (line samples + words),
authority filter chips, and per-relationship `AuthorityTag`s in every detail
panel. Never color alone (§24).

## 5. Node Types

`requirement`, `task`, `agent`, `file`, `commit`, `test`, `evidence` — the
objects the backend actually provides. Deliberately absent: attempt nodes
(attempts render inside task/agent details from durable attempt rows), fake
criterion nodes (criterion→task binding exists only at verify time), approval
and recovery nodes (they render as state/receipt content, not graph objects).
No invented nodes.

## 6. Edge Types

| Edge | Authority | Source of truth |
|---|---|---|
| requirement `planned for` task | PERSISTED | `task.requirement_id` FK |
| task `depends on` task | PERSISTED | task dependency table |
| task `executed by` agent | PERSISTED | durable attempt rows |
| task `evidence recorded` evidence | PERSISTED | attempt `evidence_artifact_ids` |
| evidence `verifies` requirement | PERSISTED | validation row bound at verify time |
| test `produced` evidence | EVENT-DERIVED | tool-run event payload `artifact_ids` |
| test `targeted` file | EVENT-DERIVED | tool-run event payload `path` |
| commit `changed` file | EVENT-DERIVED | commit event payload `paths` |
| task `integrated as` commit | INFERRED | merge-message parse + worktree link |

## 7. Investigation Experience

Investigate button (toolbar + every detail panel) scopes the canvas to a
bounded neighborhood (BFS, `MAX_INVESTIGATION_DEPTH`, node cap + truncation
disclosure); Expand/Collapse walk hops; selection follows the causal chain
(`follow`); Escape exits investigation or clears selection; Center selection /
Fit / zoom (+/−/wheel/0); type lenses are bypassed inside investigation so the
chain renders as-is; the authority filter still applies. Filters: object type,
failures-only, authority, requirement/task/agent focus, search. Text view
(screen-reader-first per-requirement trees + unlinked tasks) remains the
non-geometry path.

## 8. Requirement Investigation

Requirement detail: description, priority/desired outcome, acceptance criteria
(each with verified/failed/unknown state; explicit "no criterion-level mapping
is invented" note), Tasks (PERSISTED tag), Agents (PERSISTED), Evidence list,
Verification status, **WhyPanel** (`Why VERIFIED/UNKNOWN/FAILED`), overseer
semantics note, and jumps: Office oversight, Requirements, Command Center.
Evidence honesty: "No evidence recorded for this requirement's tasks." when
absent.

## 9. Task Investigation

Task detail: linked/unlinked status, priority, attempt count, failure classes,
worktree branch/status, recovery pill, **waiting explanation**
(`Waiting for {dep} ({status})` for any non-terminal task with unresolved
dependencies — see §22 note), Attempts (Task/attempt/execution/tool-call
vocabulary note per §10, per-attempt agent/outcome/failure/evidence),
Depended on by / Depends on (PERSISTED), Agents (PERSISTED), Integrated-as
commit (INFERRED tag), evidence (PERSISTED), Failure path for failed tasks,
jumps: Office, View activity, Full history, View requirement.

## 10. Agent Investigation

Agent detail: role, model, lifecycle state, current task (PERSISTED), attempts
across tasks (bounded, outcomes + failures), failures list, recoveries, tool
runs from the event feed (newest-first, bounded, with exit codes), and jumps:
Inspect in Office (team tab), View activity (Timeline filter), Inspect current
task. Office remains the agent surface; the graph supplies causality.

## 11. Failure / Recovery Investigation

`failureTrace` builds the path: failed criterion/requirement impact → agents
involved → recovery events (RECOVERY_SELECTED/RETRY/replan/terminal, human
wording) → recovery decision → retried attempts → verdict
("Verified by a later successful attempt" / "No successful attempt recorded")
→ "Requirement still blocked". Rendered as an ordered, clickable chain in the
task detail for failed tasks. Decisions and evidence only — no hidden
chain-of-thought anywhere.

## 12. Evidence / Verification Investigation

Evidence detail: artifact metadata (existing `ArtifactMetaView`), the claim
ladder note ("Claim ≠ result ≠ evidence ≠ verification: this artifact is
evidence only"), backward chain: "Recorded by:" attempts (PERSISTED) and
"Bound at verify time to criterion …" (PERSISTED validation row), with honest
absence lines ("No recording attempt found in the loaded tasks — see Timeline
for older events."; "Not bound to any verified criterion — recorded evidence,
not verification."). WhyPanel chains carry verified timestamps when recorded.

## 13. Cross-Surface Navigation

Graph → Office (task/agent/oversight with selection), Timeline (View activity
with agent/task filter; Full history → History view), Editor (files/commit
paths via `openFile`), Requirements (View requirement), Command Center
(Analyze coverage prefill). Requirements → Graph: "Investigate in graph" on
the selected requirement (UI5-07). No new router; all via existing
`ViewId`/office selection state. Graph selection syncs both ways with Office.

## 14. Timeline Integration

Graph stays causal; Timeline stays chronological. Feed-bounded nodes say so
("see Timeline for older events") and every task detail offers View activity
(pre-filtered) and Full history. No Timeline duplication as a graph; no new
filtering architecture.

## 15. Responsive Behavior

UI-1 shell rules preserved. ≤768px the rail becomes a drawer ("Open
navigation"); the graph, toolbar chips, legend, and detail panel reflow.
Live-verified zero horizontal overflow at 1920×1080, 1440×900, 1280×720,
1024×768, 768×1024 with the graph view open (`ui5shots/vp-*.png`). No
separate mobile graph architecture.

## 16. Accessibility

Nodes are buttons with `aria-label` ("{type}: {label}, {status}"), keyboard
select (Enter/Space), canvas keys (+/−/0/arrows/Escape), visible focus,
edge `<title>` relationship descriptions, legend as `role=note`, authority
chips as `aria-pressed` buttons, non-color authority distinction (line style +
text labels + tags), investigation/disclosure notes as `aria-live=polite`,
text view as the full textual graph. Reduced motion inherited from the design
system (UI-2.5 guard re-verified by `smoke_design_tokens`).

## 17. Performance

Measured: unit benchmark builds+filters+lays out **500 tasks → 909 nodes /
1403 edges in 351ms** (budget <5s; `graph/build.test.ts`). Live: first graph
paint 0.29s, settle 1.8s, selection response ~0.2s, investigate toggle 0.38s
at 14 nodes (ui4proj real project). Investigation bounds the visible
neighborhood instead of virtualizing; caps stay (150 files / 200 evidence with
counts). No virtualization needed; no speculative optimization added.

## 18. Live Scenarios

All executed on real backend data, real Chromium (`ui5shots/`):
- **A (verified)** ui4proj "Payroll summary endpoint" VERIFIED: why-panel shows
  criterion → verified timestamp → evidence (bound at verify time) →
  "recorded verification point" line. ✓
- **B (unknown)** UNKNOWN requirement: precise missing list, "stays UNKNOWN",
  no manufactured edges. ✓
- **C (failed task)** wf-d333b71a: failure path with failure class, tool run,
  events. ✓
- **D (waiting)** ui3proj: "Waiting for Backend login (pending)" +
  Depends-on (PERSISTED). ✓
- **E (multiple agents)** wf-724f0084: distinct agents per attempt. ✓
- **F (evidence backward)** evidence → recording attempts → verifying
  criteria (where recorded). ✓
- **G (source changed after verification)** real file edit on the verified
  project: requirement stays VERIFIED with the historical line; no
  current-validity claim anywhere. ✓
- **H (recovery)** "Recovery decision: request_hitl" recorded and rendered. ✓

## 19. Regression Results

- TypeScript (`tsc --noEmit`) clean; production `vite build` success (1m10s,
  pre-existing chunk-size warning only).
- ESLint: 0 errors (1 pre-existing `react-refresh` warning in CodeEditor).
- Vitest: **182/182 passed** (25 files; 166 before UI-5, +16 graph/investigation).
- Backend pytest: **560 passed** (3m45s).
- Smoke battery (19): editor, durable, recovery, scheduler, runtime,
  integrations, oversight, office, agent_office, command_center,
  command_palette, design_tokens, graph, history, intelligence,
  panel_retention, project_picker, shell_status, task_controls — **all PASS**
  (recovery/scheduler on live Temporal; office on the real UI with HITL).

## 20. Browser QA

23/23 checks passed live (see §18 + authority legend/chips/edge-titles,
keyboard, viewports, overflow, page errors). Screenshots in `ui5shots/`
(retained, not committed, matching UI-4.5 practice). One earlier battery run
was abandoned when the runner process was killed externally (no results
recorded); every smoke was then re-run individually to a recorded result.

## 21. Remaining Data Gaps

Unchanged from UI-4.5 and honestly surfaced, never invented: no
invalidation/current-validity model (graph says so explicitly); no
criterion→evidence standing link outside verify-time validation rows; no
verification history events; artifact rows carry no task/agent FKs (backward
chains assembled from durable id lists); in-progress tool activity not in the
feed; commit→task remains INFERRED. DERIVED/UNAVAILABLE authority values
remain unused (no current built edge qualifies).

## 22. Known Limitations

- The dependency-wait explanation now renders for any non-terminal task with
  unresolved dependencies. Backend truth: the durable workflow parks
  dependency waits in `running` with `DEPENDENCY_WAIT_STARTED` (signal wait),
  and plan-created dependents may sit in `pending` until scheduled — the UI
  names the unresolved dependency with its live status in both cases.
- Expand at depth 1 on a fully-connected small neighborhood may not add nodes
  (QA observed 4→4) — the bound is correct, just saturated.
- Edge `<title>` tooltips are desktop-hover only; the text view and detail
  tags carry the same authority text for keyboard/touch users.
- `smoke_graph.py` needed two locator updates: UI-5 features (WhyPanel naming
  unknown criteria; attempt rows linking agents) added legitimate second
  matches — locators were scoped (`.first` / summary-scoped), assertions
  unchanged in strength.

## 23. Architecture Changes

None of the forbidden kind: no second store, no graph backend, no graph
database, no event bus, no router, no persistence, no state machine, no graph
library, no new UI framework, no new dependencies. Product fix within the
existing graph module: dependency labels were inverted in TaskDetail
("Depends on"/"Depended on by" swapped relative to edge direction and to the
text tree/Office selectors) — corrected and covered by live QA; waiting
explanation now covers durable dependency waits (see §22).

## 24. Files Changed

UI5-01..08 (committed): `graph/build.ts`, `graph/explain.ts` (new),
`graph/testFixtures.ts` (new), `graph/build.test.ts`, `graph/explain.test.ts`
(new), `components/graph/GraphView.tsx`, `components/graph/GraphDetail.tsx`,
`components/graph/WhyPanel.tsx` (new), `components/requirements/
RequirementsView.tsx`, `types.ts`, `index.css`, `docs/ui-ux/ui5-baseline.md`
(+1442/−85 lines total).
UI5-09 (this gate): `components/graph/GraphDetail.tsx` (dependency label fix
+ durable waiting explanation), `scripts/smoke_graph.py` (2 locator drift
fixes), `docs/ui-ux/ui5-final-report.md` (this file).

## 25. Tests

- Frontend: 182/182 vitest (24 graph build tests, 9 explain tests among them);
  tsc clean; eslint 0 errors; build success.
- Backend: 560/560 pytest; live Temporal scheduler + recovery smokes.
- UI smokes: 19/19 including the real-UI office and graph smokes.
- Live QA script (temporary, not committed): 23/23.

## 26. Final Assessment

- **A. Investigate why a requirement reached its state?** Yes — WhyPanel chains
  criterion → validation/evidence → task → attempt → agent, with provenance
  and honest absence lines.
- **B. Distinguish authoritative from derived/inferred?** Yes — edge line
  grammar + text labels + legend + filter + per-relationship tags, all from one
  registry.
- **C. Move requirement → task → agent → attempt → evidence → verification?**
  Yes — clickable chains in both directions (verified live in A and F).
- **D. Investigate failure and recovery?** Yes — failure path with failure
  class, tool run, recovery decision, retried attempts, verdict.
- **E. Understand waiting/dependencies?** Yes — "Waiting for X (status)" from
  durable depends_on + live statuses, with PERSISTED dependency edges.
- **F. Distinguish historical verification from current validity?** Yes —
  "Verified at the recorded verification point … No invalidation model exists"
  (provenance sha/branch when recorded); Scenario G confirms no current-validity
  claim after a real source change.
- **G. Useful without becoming unreadable?** Yes — bounded investigation,
  caps + disclosure, type/authority lenses, text view.
- **H. UI-2/3/4 and backend hardening intact?** Yes — full regression green
  (§19); no contracts changed; no backend code touched in UI5-09.

**UI-5 is complete. STOP — no further waves started.**

Recommendation for UI-6 (only if a next wave is explicitly requested): the
highest-value remaining trust gap is backend verification history (emit
requirement-verified/invalidated events) to unlock a real Timeline
verification-history jump and current-validity statements; UI-side, the
residuals in §22 are the honest backlog. Per the stop condition, nothing was
started.
