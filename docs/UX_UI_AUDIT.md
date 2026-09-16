# UX/UI Audit

**Scope:** `apps/web-ui` (React 18 + Vite + TS + zustand + Monaco), current as of Phase 10.
**Method:** component/IA inspection against spec §36–§41 and the master prompt §25–§46.

## 1. Current information architecture (verified)

- **Shell:** activity bar (Explorer · Search · Source Control · Run & Toolchains ·
  Engineering Office) → sidebar views; main area = editor tabs (Monaco/diff) + bottom
  panel (terminal with real PTY, output); status bar (project, branch, dirty count,
  office activity, diagnostics, API health dot).
- **Office view:** tabs Team (agent cards with Torph-morphing state pills, task board
  with review action) · Timeline (durable event feed, kind-filter chips) · Oversight
  (completion-gate card with blockers/warnings/report generation, traceability tree,
  review-pipeline visualization with verdict pills); HITL approval cards above tabs.
- **Dialogs/overlays:** Open project, QuickOpen (Ctrl+P files), Diagnostics.
- **Design tokens:** dark theme, `--bg/--panel/--border/--text/--muted/--ok/--down/
  --warn/--accent`; state pills, live-dot pulse, verdict pills, approval cards
  (aicss-inspired); Torph text morphing; Typehug non-breaking typography.

## 2. What works well (keep)

- Editor-first identity: fully usable without AI (spec FR-028) — Monaco, tabs, search,
  git, terminals are first-class, not AI-gated.
- Office is genuinely live-state driven from durable data (agents, tasks, events,
  traceability, HITL) with honest empty/error handling for its own fetches.
- Fail-closed UX mirrors backend semantics (blocked gate shows explicit blockers;
  approval cards show risk/kind/choices).
- Consistent token-based theming; restrained motion (state pills, live dot) — matches
  the "dynamic ≠ decorative" principle.
- Interactive typography (Torph morphing on state transitions) and glue()-protected
  labels demonstrate the referenced UI libraries without gimmicks.

## 3. Weaknesses (evidence-based)

| # | Weakness | Impact | Spec ref |
|---|----------|--------|----------|
| U-01 | **No action command palette** — Ctrl+P opens files only; no Ctrl+K for start/pause/resume/review/diagnostics | Discoverability + keyboard-first workflows | §37 |
| U-02 | **Polling, not push** — office refreshes every 2.5 s; failure/recovery progressions appear up to seconds late; wasted requests | Liveness; spec §41 live events | §41 |
| U-03 | **Production states incomplete** — office handles fetch errors, but there is no offline banner, no reconnecting state, no resync cursor after API restart | Trust during failures | §41 |
| U-04 | **No execution graph** — task dependencies exist in the API (TaskOut.depends_on) but are not visualized; office shows lists only | Signature experience missing | §38 |
| U-05 | **Timeline lacks depth filters** (by agent/task/file) and virtualization beyond the 120-event window | Long runs | §39 |
| U-06 | **No requirement traceability drill-down** — traceability is flat per requirement; no REQ→TASK→ATTEMPT→artifact navigation | Spec §37 traceability | §37 |
| U-07 | **Contextual AI absent** — no selection-based actions (explain/refactor/tests) or test-failure affordances | §40 | §40 |
| U-08 | **No cost/token surface** — the cost ledger exists in the API but is not rendered | Spec §46/§50 | — |
| U-09 | **Accessibility gaps** — dialogs trap focus informally, tabs/pills lack ARIA roles, reduced-motion not honored | §43 | §43 |
| U-10 | **No virtualization** — event/timeline lists render capped arrays; large histories underperform | §42 | §42 |
| U-11 | **Ad-hoc error surfaces** — office notice string vs toasts elsewhere; no unified error component | Consistency | — |
| U-12 | **No UX for execution replay** — events are listed but not replayable as a story | §39 | — |

## 4. Opportunities (mapped to the master prompt)

- **Agent Office → signature experience (§29):** extend agent cards with current task,
  worktree, elapsed time, token/cost meters (from the durable cost ledger), and an
  agent-to-agent message lane (durable messages already exist) so collaboration lines
  like "A → B: auth done" become visible.
- **Execution Graph (§31):** render the durable task DAG (already queryable) with live
  status pills; zoom/pan optional — start with a dependency tree in the office sidebar,
  promote to a full view later.
- **Traceability drill-down (§32):** the data chain exists (requirement → tasks →
  attempts → evidence artifacts); needs a navigable UI, not new backend work.
- **Timeline (§33):** one event store already powers it; add agent/task/type filters
  (API supports `event_type`), then replay scrubbing (§34) by `occurred_at` cursor.
- **Command palette (§36):** one component, a registry of actions, keyboard-first.
- **Contextual AI (§35):** leverage the existing review/spawn endpoints from
  selection/test-failure context menus — backend capabilities already exist.

## 5. Design-system verdict

Tokens + pills + cards are consistent; the gap is *component reuse under the hood*
(e.g., three list-row styles) and missing states (§40 list). Recommended: formalize
`components/ui/` primitives (StatePill, LiveDot, EmptyState, ErrorBanner, MetricChip,
SectionHeader) and refactor office/oversight to consume them — no visual redesign
required, consistency and a11y come along for free.
