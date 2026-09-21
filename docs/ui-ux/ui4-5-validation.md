# UI-4.5 Validation Report — Trust & Causality Gate

Date: 2026-09-21. Method: source forensics (backend models, services,
workflows, activities; frontend projections) + live Chromium against real
backend (compose PG/NATS/Redis, Temporal UP, worker started) + direct
Temporal SDK queries. No production code changed. No fake state.

## 1. Executive Summary

**UI-5 readiness: READY WITH DATA GAPS.** The persisted causal core
(requirement→criterion→task→attempt→agent/evidence→validation) is
authoritative and durable; event-derived edges (files/tests/commits) are
honestly flagged; the graph projection never invents relationships. Two
structural trust findings constrain what UI-5 may claim: (a) verification
has NO invalidation model — VERIFIED survives code changes (confirmed live);
(b) NOTHING observes workflow-level failure — a failed Temporal run orphans
its task in `running` with zero product signal (confirmed live, root-caused).
Both are backend/runtime scope, explicitly not fixed here.

## 2. Current Causal Model

Three layers, strictly separated in code: PERSISTED rows (requirements,
criteria, tasks, dependencies, attempts with agent/outcome/evidence,
validations, artifacts by reference, HITL), DERIVED reads (overseer status
computation, coverage, attention, graph edge assembly), EVENT substrate
(durable sequenced events table = truth; SSE = projection; resync restores).
Full table: `docs/ui-ux/ui4-5-baseline.md`.

## 3. Relationship Authority Matrix

See baseline doc. Load-bearing verdicts: req→criterion→task→attempt→agent
all PERSISTED (FKs, SET NULL on delete — linkage can decay on deletes);
attempt→artifact PERSISTED (id lists); criterion→evidence PERSISTED at
verify time (validation row); artifact carries NO backlinks (forward-only
references); commit→task is EVENT+INFERRED (message regex, flagged
`derived:true`); requirement→approval DERIVED via task join; change→
verification-invalidation ABSENT; verification timestamps/history ABSENT.

## 4. Requirement → Verification Trace

Traced live on a real requirement (ui45proj): REQUIREMENT_CREATED →
PLAN_CREATED → TASK_CREATED → TASK_EXECUTION_STARTED → AGENT_CREATED →
TOOL_RUN_COMPLETED → artifact upload → verify ×2 → VERIFIED. Every edge
classified: requirement→criterion PERSISTED; criterion→task INFERRED at
bind time, PERSISTED after (validation.task_id); task→agent PERSISTED
(attempt row); attempt→file EVENT; attempt→artifact PERSISTED; artifact→
evidence PERSISTED reference; evidence→verification PERSISTED
(criterion.status + validation passed). Weak links: criterion→task before
binding (UI picker binds honestly); artifact→producer direction is
reference-only (no backlink — graph "verifies"/"produced" edges assemble
from the union of lists, correctly).

## 5. Evidence Semantics

Backend preserves the distinctions: agent claims live in attempt/payload
fields (never statuses); TEST RESULT = attempt outcome + TOOL_RUN exit +
validation status; ARTIFACT = content-addressed row (name/kind/mime/sha,
no task/agent FK); EVIDENCE = membership in attempt/validation id lists;
VERIFICATION = criterion.status + passed validation; APPROVAL = decided
HITL row with decider + note + timestamp. One conflation risk documented:
`failure_detail`/payload text can carry claim-like prose into evidence
views — UI renders payloads as data, never as verdicts (verified in
EventDetail sanitized-raw path).

## 6. Verification Invalidation Analysis

Gap CONFIRMED live (§14 scenario): requirement VERIFIED → source file
modified → new tool run executed → traceability still VERIFIED. Backend has
NO code version, commit SHA on validations, artifact versioning beyond
sha-addressing, verification timestamp, scope, staleness, or supersession.
`updated_at` exists on Requirement but nothing consumes it for trust.
Exact gap: verification is a point-in-time assertion with no temporal or
code binding. UI-5 must never imply "still verified"; recommend a
backend-owned `verified_at + verified_tree_sha` record as the future fix
(not implemented here).

## 7. Criterion-Level Evidence Analysis

Schema/API (source): validation row carries criterion_id + evidence_
artifact_id + task_id + kind + status + detail + created_at — complete and
durable. UI binding (VerifyCriterion picker over recorded artifacts) is
durable at submit (row written) but request-time selection (no standing
criterion→evidence link before verification — correct, nothing to persist
yet). Missing-evidence path is honest (empty-candidates note, 404
surfaced). Timestamps exist per validation but are unexposed in the report
— history UIs cannot be built without a backend addition (gap).

## 8. FAILED / BLOCKED State Analysis

Producer map (source): failed attempts ← Temporal execute/finish activities
(outcome/failure_class); failed tasks ← terminal_failure path; failed
validations ← security_scan / Temporal validation activities;
criterion FAILED ← failed validation rows; requirement FAILED ← derived;
HITL pending ← `hitl_service.create_request` from Temporal hitl activities
only (NO public create endpoint — decide/cancel only); BLOCKED tasks ←
dependency waits (Temporal); HITL timeout → fail-closed `timeout` status.
Live reproduction: NOT achieved — the executed workflow died at
`snapshot_attempt_activity` (unregistered on the worker) before any failure
path ran. FAILED/BLOCKED UI (pills, receipts, attention, failureTrace)
verified statically + unit-tested, not live. No backend state exists without
Temporal that the UI misrepresents; nothing to fix in UI.

## 9. Task / Run / Execution / Attempt Semantics (suitable for UI copy)

* Task: durable work unit (row; created by API/plan; owned by project;
  retryable per transition matrix; completion = status completed (human/
  workflow terminal); failure = status failed; relates to requirements via
  nullable FK).
* Run: UI word for one user-visible execution interaction (dispatch or
  workflow run); has identity only as Temporal workflow id (`task-exec-{id}`).
* Execution: one Temporal workflow run (durable history, retryable by
  re-dispatch; a task may have several across retries).
* Attempt: durable (task × number) row with agent, outcome, failure class/
  detail, evidence ids; created by the workflow, never rewritten.
* Agent: durable worker identity; linked to work ONLY via attempts.
* Tool call: NOT a row — a TOOL_RUN_COMPLETED event + optional artifacts;
  durable as event, replayable from history.

## 10. Requirement Identity

UUID PK (canonical, never title-dependent); title + project + created_at;
source/session; status derived. UI shows REQ 8ch mono secondary + title
headline — compliant. Duplicate titles across QA runs confirmed readable
via the id. Minimum safe secondary set: 8ch id + created date (created_at
is NOT currently exposed on RequirementOut — minor gap: UI cannot show
"created" per requirement; recommend adding the existing column to the DTO).

## 11. Causal Graph Readiness

Graph readiness: READY WITH DATA GAPS (see §20). Data: report + raw
requirements + tasks + agents + bounded events + worktrees (all recorded).
Nodes durable except event-derived test/commit/file/evidence nodes (bounded
feed → nodes vanish as the feed rolls; nodes carry no independent
durability). Edges: persisted (req-task, depends, executed-by) vs flagged
derived (commit-task) vs event-assembled (test/file/evidence links).
Live screenshot confirms the full chain renders from real data. Staleness:
graph reflects the store snapshot; event-bound nodes age out of the 120
feed — acceptable, disclosed via counts.

## 12. Timeline Readiness

Ready. Events carry durable id, occurred_at, actor (agent/system via roster
join), task/agent/execution/correlation/trace ids, payload. All §13 event
kinds producible except requirement-verified/invalidated (no such event
types exist — verification changes emit NO event; timeline cannot show
verification history — gap), agent-replaced/retry (Temporal-only, types
exist in recovery vocabulary), approval granted/rejected (HITL_* events
exist in taxonomy; EventDetail approval section reads live HITL rows).
Requirement-verified/invalidated events are the missing substrate for a
verification-history UI.

## 13. Investigation Journey Results

* A "Why VERIFIED?": Requirements → receipt chain → jumps. TRUSTWORTHY.
* B "Why UNKNOWN?": missing-list renders. TRUSTWORTHY.
* C "Why FAILED?": UI ready, no live FAILED producible here. UNVERIFIED LIVE.
* D "Which agent produced the change?": attempts → owners; file→task via
  tool events. TRUSTWORTHY where attempts exist.
* E "Which test produced the evidence?": TOOL_RUN event → artifacts;
  attempt outcomes. TRUSTWORTHY.
* F "Which evidence supports this criterion?": validation row (ids) +
  named artifacts. TRUSTWORTHY post-verify; pre-verify honestly empty.
* G "What changed after verification?": NOT ANSWERABLE — no invalidation
  substrate (gap §6). UI must not imply otherwise.
* H "Which requirement is affected by this failed task?": task.requirement_id
  → requirement; attention requirement-blocked items. TRUSTWORTHY.

## 14. Verified-Then-Changed Scenario

Executed live: VERIFIED → file modified → new tool run → state STILL
VERIFIED. Documented as trust-model gap (§6), not fixed (backend scope).

## 15. UI-4 Regression Results

List, filters, detail, criteria, verify UI (empty-candidates path),
receipts (VERIFIED + UNKNOWN), task/agent/evidence/approval sections,
NeedsYou (shared collector), context panel, office/task jumps, narrow
sheet, keyboard (focus/Enter/tab/2px-solid ring via real Tab) — all pass
live. One transient overflow flag during a reload flow could not be
reproduced with settled content at any viewport (culprit hunt empty);
watch item, not a defect finding.

## 16. Browser QA

1920/1440/1280/1024 live + 768 drawer flow: zero overflow with settled
content; graph/history/office/center/context all render real state;
screenshots retained in temp (not committed). Center + roster regression
smoke green, zero console errors (aside from environmental git-status 409
on a non-git scratch dir — handled empty-state path).

## 17. Accessibility

Real-Tab focus reaches rows; `:focus-visible` 2px solid confirmed live
(earlier programmatic-focus readings were measurement artifacts);
dialog/focus-trap untouched; native controls throughout; reduced-motion
guard verified in UI-2.5. Tab-from-top can stall at the mounted terminal
(xterm consumes Tab — pre-existing terminal behavior, not requirements
scope; recommend a documented Tab-exit in terminal work).

## 18. Performance

Traceability is one report read per resync; derivations memoized/pure;
evidence lists bounded (≤8 + note); graph caps files/evidence nodes with
disclosure; no virtualization evidence needed; no new caching introduced.

## 19. Backend/Data Gaps (exact)

1. No verification invalidation (no version/sha/timestamp/scope).
2. No requirement-verified/invalidated events (no verification history).
3. `snapshot_attempt_activity` implemented + called by workflow but NOT
   registered on the worker → any workflow reaching it fails (found live;
   one-line backend wiring fix, NOT made here per gate rules).
4. No workflow-failure reconciliation: failed/terminated runs orphan task
   rows in `running` with unfinished attempts and zero product signal
   (found live; 12 historical runs show the same terminal pattern).
5. No public HITL-create endpoint (Temporal-only production).
6. Artifact rows lack task/agent/criterion FKs (linkage via lists only).
7. RequirementOut omits created_at (existing column, DTO gap).
8. FAILED criterion/requirement unproducible without Temporal validation
   failures.

## 20. UI-5 Readiness Decision

**READY WITH DATA GAPS.** The persisted core + flagged derivations fully
support an investigation graph that labels edge authority. UI-5 MUST: keep
`derived:true` flagging, never render invalidation/staleness claims, treat
event-bound nodes as feed-scoped, and surface orphaned-running tasks as
"execution state unknown — check Temporal", not as running.

## 21. Recommended Next Work

1. Backend (out of UI scope): register the snapshot activity; add workflow-
   failure reconciliation (terminal event + task FAILED marking); add
   verified_at/tree_sha to validations; emit requirement-verified events;
   expose created_at on RequirementOut.
2. UI-5: causality overlay on the existing graph (authority-labeled edges),
   orphan-state surfacing, verification-history jumps (once events exist).
3. Docs: correct the "stop" control-kind word to Cancel in a UI pass.
