# UI-4 Final Report — Requirements, Traceability & Verification Experience

Date: 2026-09-21. No `merged.md`-independent audit needed — UI-0.5 docs plus
direct backend/source reads served as baseline (`docs/ui-ux/ui4-baseline.md`).

## 1. Baseline

Office OversightTab (gate card + requirement `<details>` cards, counts only
for evidence), GraphDetail requirement section, Center traceability finding +
CompletionReceipt, `ArtifactMetaView`, `ApprovalCard(taskIds)`,
`collectAttention()`, ContextPanel requirement context (basic). Backend:
Requirement/Criterion/Validation models, overseer derivation
(VERIFIED/FAILED/UNKNOWN — no other states), traceability + verify +
completion endpoints. The verify endpoint had NO frontend client.

## 2. Files changed

`client.ts` (verify/create wrappers), `store.ts` (ViewId + requirements),
`App.tsx` (view branch + sidebar mapping), `ActivityBar.tsx` (door retarget
+ failed-requirements badge), `registry.ts` (palette retarget),
`TeamTab.tsx` (inspector requirement jump), `ContextPanel.tsx` (extended
requirement context), `OversightTab.tsx` (Requirements jump),
`selectors.ts` (requirement attention kinds), `OfficeAttention.tsx`,
`NeedsYou.tsx`, `index.css` (requirements + fixes).

## 3. Files created

`requirements/requirementModel.ts` (+test), `components/requirements/`
`RequirementsView.tsx`, `RequirementDetail.tsx`, `VerifyCriterion.tsx`,
`VerificationReceipt.tsx`, `NewRequirementDialog.tsx`, `docs/ui-ux/ui4-baseline.md`.

## 4. Requirements implementation

Main-area two-pane surface: header (coverage, gate pill, completion request,
blockers), filter chips (All/Verified/Failed/Unknown), compact rows (status
pill + title + work-state + criteria/priority), detail pane, New requirement
dialog (existing create endpoint). Rail + palette + context retargeted;
office tab kept as summary surface (no duplication: summary vs detail).

## 5. Status semantics

Backend VERIFIED/FAILED/UNKNOWN pass through (case-normalized). IN
PROGRESS/BLOCKED surface ONLY as derived work-state lines ("2/4 tasks
complete · 1 blocked"), never as verification states.

## 6. Acceptance criteria

First-class rows: state pill, description, kind, mandatory flag; unverified
mandatory criteria get evidence-backed Verify UI (recorded-artifact
candidates only; honest empty-candidates path; 404 surfaced).

## 7. Traceability

Vertical narrative per requirement: criteria → tasks (owners/status) →
agents → recorded files → attempts → evidence → receipt. Every level
navigates (task/agent/file/graph/command jumps). Graph stays the causal
surface (linked, not duplicated).

## 8. Evidence

Named `ArtifactMetaView` lists (validation + task evidence, bounded);
evidence candidates derived from recorded attempt/validation artifacts.
Per-criterion evidence linkage: BACKEND GAP (report carries states + flat
id lists) — verify UI bridges it by letting the user bind evidence.

## 9. Tests

Attempt outcomes + recorded-files + honest "no validation tests" path.
No invented pass counts, no skipped-test claims.

## 10. Verification receipt

`VerificationReceipt` in `CompletionReceipt` language: VERIFIED shows why
(criteria, work, attempts, agents, evidence); FAILED names failed criteria;
UNKNOWN lists precisely what's missing. Claim/test/evidence/verification/
approval never merged.

## 11. Needs You

`collectAttention()` extended (backward-compatible 4th param): failed and
blocked requirements with requirement jumps; approvals enriched with
requirement context. Office + Center share it.

## 12. Approval

`ApprovalCard(taskIds)` reused per requirement; gate blockers inline;
completion request flow unchanged.

## 13. Cross-surface navigation

Task→requirement, requirement→task/agent/file/graph/command/office,
context→requirement, office→requirements, rail/palette doors — all via
existing ViewId + selection state. No router.

## 14. ContextPanel

Requirement context: verification pill, priority, derived work-state,
criteria fraction, evidence count, open jump.

## 15. Responsive behavior

Two-pane → stacked ≤1024px with capped list; rows wrap; live-verified at
1920/1440/1280/1024/768 with zero overflow (one transient overflow flag
during a reload flow could not be reproduced with content settled —
culprit hunt empty; watching brief in §25).

## 16. Accessibility

Row buttons with labels + focus ring, native details/selects/dialogs,
`role=note` missing-lists, alert/error roles, arrow-free logical tab order
verified live, reduced-motion inherited.

## 17. Performance

Memoized lists, bounded evidence (≤8 + overflow note), existing resync,
no new fetching beyond descriptions + verify POST. Full suite green.

## 18. Trust gaps discovered

* Per-criterion evidence linkage absent server-side (verify UI binds it
  at action time instead).
* No verification timestamps/history (no "last verified"; snapshot
  `generated_at` only).
* Backend auto-defaults `manual` criteria to non-mandatory (service-layer
  inference — UI renders the recorded flag, never assumes).
* FAILED/failed-criterion production has no UI/test path without Temporal.

## 19. Backend limitations

As §18, plus: requirement creation exists but no product flow wired it
(UI adds the dialog on the existing endpoint); orphan-task (scope drift)
surfaces as warnings only.

## 20. States not reproducible

FAILED requirement/criterion, blocked-verification attention, Verifying
phase linkage, approval-on-requirement cards (no Temporal worker; no
HITL source in env). Statically + unit covered; live Temporal needed.

## 21. Tests

tsc clean; eslint 0 errors; **166/166 vitest** (159 untouched + 7 new:
requirementModel 6, verifyCriterion 1). No test modified to pass.

## 22. Browser QA

Live Chromium + real backend: seeded payroll requirement (3 criteria),
2 tasks, exit-0 tool run, uploaded artifact, API + UI creation, UNKNOWN
receipt with missing list, verify flow to VERIFIED ×2 live, completion
gate allowed, task→requirement jump with selection, narrow detail sheet,
keyboard (focus/Enter/tab/focus-ring), zero console errors (aside from
environmental git-status 409 on a non-git scratch dir, handled by UI).

## 23. Screenshots/observations

`ui4shots/`: list, unknown detail, verified detail, gate, created dialog,
viewport set, narrow detail. Notable: VERIFIED + "0/2 tasks complete"
coexist honestly (criteria verified, work pending) — the receipt explains
the split; duplicate seeded titles across QA runs confirmed the need for
REQ-id secondary metadata (present).

## 24. Features deliberately NOT implemented

Graph/Timeline/Artifact/Diff internals, model/MCP/browser config,
pagination framework, per-criterion evidence history, verification
timestamps UI (no data), jump-return infrastructure, second store/library.

## 25. Remaining UX problems

* Transient overflow flag during reload flow (unreproduced; watch).
* Same-titled requirements need stronger disambiguation (created-time).
* Verify picker submit path (with candidates) not live-exercised —
  requires Temporal-produced attempt evidence.
* Office OversightTab now overlaps the new surface (summary role kept
  deliberately; revisit if users confuse them).

## 26. Recommendation for UI-5

Execution Graph causality overlay reusing the lineage already flowing
(task→agent→file→evidence edges exist in traceability + events); then
Timeline verification-history jumps. The trust data is now one import away
everywhere.
