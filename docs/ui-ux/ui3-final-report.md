# UI-3 Final Report — Agent Experience & Engineering Office

Date: 2026-09-20. Baseline: pre-UI3 office (sidebar cards, `window.confirm`
controls, dual-verb Stop/Cancel, ID-prefix evidence, unattributed attention
gap). No `merged.md` exists in the repo — UI-0.5 docs in `docs/ui-ux/` plus
source reads served as the baseline record.

## 1. Files changed

`TeamTab.tsx` (roster), `AgentDetail.tsx` (hierarchy reorder), `ApprovalCard.tsx`
(taskIds filter), `CommsTab.tsx` (agent filter, task scope, recipient prefill),
`NeedsYou.tsx` (attention collector), `CompletionReceipt.tsx` (pending wording),
`CenterView.tsx` (truncation note), `ContextPanel.tsx` (agent summary),
`selectors.ts` (attention collector, Cancel wording), `useBulkAction.ts`
(confirm migration), `store.ts` (`centerDropped`, `commsRecipient` — additive),
`index.css` (roster/attention styles, F2 fix, focus ring).

## 2. Files created

`office/agentStates.ts` (+test), `office/AgentRow.tsx`,
`office/AgentStatusLabel.tsx`, `office/OfficeAttention.tsx`,
`office/attention.test.ts`.

## 3. Components reused

`StatusLabel` (tasks), `UiState`, `ConfirmHost`/`confirmAction`, `DepMap`,
`TaskInspector`, `ArtifactMetaView`, `ApprovalCard` (extended, not forked),
`ContextPanel`, TopBar/rail/palette/shell contracts.

## 4. Agent roster changes

AgentCard grid replaced by compact rows: status pill, name, role·model,
current-task link, activity/waiting line, elapsed + worktree branch, Open /
state-dependent Pause-or-Resume / Message. Search + state filters
(All/Working/Waiting/Needs you/Failed/Completed), attention-first sort,
empty + no-match states, arrow-key roving focus, Enter opens.

## 5. Agent row information hierarchy

Who (name+role) → state → current task → activity-or-attention →
elapsed/branch → actions. Needs-you flag inline; IDs never headline.

## 6. Agent activity summaries

Latest recorded event in plain words + elapsed ("tool run completed ·
12:04:31"), task assignment fallback, honest silence note. No reasoning
exposure, no invention.

## 7. Agent detail

Reordered to State → Tasks → Activity (+full-activity jump) →
Dependencies (+graph jump) → Tools → Files → Evidence → Worktree (new) →
Approvals (new, scoped) → Communication → Recovery → Sessions → Cost.
Header uses canonical status + attention flag; Release uses ConfirmHost.

## 8. Task relationship

Tasks own work; agents own execution; attempts render per task. Inspector,
owners, depends_on jumps unchanged; rows link both directions.

## 9. Dependencies

Inline waiting reasons + dep buttons in roster context and detail; DepMap
kept; graph jump added. Office summarizes, graph investigates.

## 10. Worktree visibility

Branch (+count) on rows; dedicated detail section with integration status,
honest empty, graph jump. Raw paths stay secondary.

## 11. Communications

Agent filter, task-scoped compose (`task_id` supported by API), contextual
Message action prefills recipient + opens compose; sender/recipient/task
jumps; delivery states shown from recorded fields. Poll-only honesty kept.

## 12. Recovery/failure

Recovery chains + failure classes inline; failed/blocked tasks surface via
attention; retry stays per-task confirmed. No invented recovery buttons.

## 13. Needs You — F1 FIXED

`collectAttention()` (pure, tested) merges failed/blocked tasks, failed
tool runs (deduped per failure signature), and pending approvals from
RECORDED state. Office strip + Center strip share it. Verified live: real
exit-1 run produced "Tool failed: run (exit 1)". Agent-attributable
failures also flag the roster row and the Needs-you filter.

## 14. Approvals

Same `ApprovalCard` everywhere (no second component); agent-scoped section
with own empty text; WHAT/WHY/SCOPE present, note optional, per-id busy.
Risk/impact/reversibility beyond the backend model documented as GAP.

## 15. Costs

Unchanged logic; honest non-accounting notes kept; project totals +
attribution labels retained. No USD invented.

## 16. Evidence/verification

ID prefixes replaced by named `ArtifactMetaView` (≤8, overflow noted);
validation events kept; verification stays in Requirements (linked).

## 17. ContextPanel integration

Agent summary: canonical status, attention flag, role/model, current task,
latest activity, branch, active-for, detail jump. Task/file/requirement
contexts untouched.

## 18. Responsive behavior

Rows stack <768px; roster verified at 1920/1280/768 with zero overflow;
sidebar overlays as drawer on narrow (verified live). Detail inherits the
overlay sheet.

## 19. Accessibility

Roving ArrowUp/Down on roster, Enter opens, Back returns to roster,
native buttons throughout, `role=note` attention, labelled filters,
focus-ring extended to text inputs, reduced-motion guard inherited.
No hover-only controls added.

## 20. Performance observations

Roster derivations memoized; pure selectors; bounded feeds unchanged;
50-agent scale stays row-based (no virtualization — existing perf budgets
green, no evidence of need).

## 21. UI-2.5 fixes

* F1: FIXED (see §13).
* F2: FIXED — `.cc-entry` header gets `min-width: 0` + wrapping
  (trigger was long request titles in flex headers).
* Center truncation: FIXED — `centerDropped` counter + "Showing the latest
  20 of N" note, reset on clear.
* Pending-task wording: FIXED — receipt line "Request complete — work
  continues in Agents."
* Focus ring: FIXED — text inputs gain the ring shadow alongside the
  accent border.
* `ui1-followups.md` item 1 CORRECTED (referenced doc exists at docs/ root).

## 22. Tests

tsc clean; eslint 0 errors (1 pre-existing warning); **159/159 vitest**
(144 untouched + 15 new: gate/phases/agentStates/attention); no test
modified to pass (one tiered-fuzzy scare resolved in implementation, not
in tests).

## 23. Browser QA

Live Chromium + real backend (Temporal disabled): seeded 4 agents, 4 tasks,
2 requirements, exit-1 tool run, operator message. Roster, filters, search,
keyboard (focus → arrows → Enter → detail → context → Back), detail
sections, comms rows + filter, attention strip, narrow drawer — all
screenshot-verified, zero console errors.

## 24. Viewports tested

1920×1080, 1280×800, 768×1024 live; 1440/1280/1024 rules inherit UI-1
verification. Zero overflow in all UI-3 surfaces.

## 25. States that could not be reproduced

Task-failed rows, HITL-pending cards, Verifying phase, blocked-by-Temporal
waits, recovery chains with history (no Temporal worker in this env).
Implementation verified statically + via unit tests; live Temporal state
not reproduced.

## 26. Backend gaps discovered

* No USD costs; no per-agent accounting (noted in UI, unchanged).
* Approval model lacks scope/impact/reversibility fields (card shows
  kind/question/task/choices only).
* In-progress tool activity unexposed (honest labels kept).
* Task→agent linkage exists only via attempts (pre-execution agents show
  "no task recorded" — truthful).
* Unattributed (agent-less, task-less) failures render strip-only by
  necessity — roster filter cannot claim them.

## 27. Features deliberately NOT implemented

Requirements/Graph/Timeline/Artifact/Diff internals, model/MCP/browser
config, execution from office beyond existing controls, virtualization,
router/deep-links, second store/library, pagination for Center, jump-return
infrastructure, message retry button (no endpoint observed — verify before
adding).

## 28. Remaining UX problems

* Duplicate seeded names in QA exposed weak identity disambiguation
  (name + role only) — real fleets need avatar/initial + created-time.
* "No task recorded" for pre-execution agents invites a dead-end; a
  "Assign task" shortcut would close the loop (UI-4 task views).
* Attention strip and roster filter diverge for unattributed items
  (documented above; acceptable, watch for confusion).
* Header keeps "Engineering office" while rail says "Agents" — deliberate
  (room vs roster) but revisit if users stumble.

## 29. Recommendation for UI-4

Requirements + traceability + verification receipts, building directly on
`ApprovalCard`, `CompletionReceipt`, and `collectAttention` patterns proven
here. Then graph causality overlay — the lineage data already flows.
