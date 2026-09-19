# Frontend UI/UX foundation audit — Wave 6

Audit gate completed 2026-09-17 before implementation. Inspected frontend components, shared types, clients, stores, reducer, transport, Monaco setup, repository architecture and Python browser-smoke conventions. Not a line-by-line review of the entire backend.

## Current architecture and strengths

React 18, TypeScript, Vite, plain CSS, Monaco, xterm. No URL router: App selects Explorer/Search/Git/Run/Office through the existing Zustand editor store. Existing Office Zustand store owns realtime projections. Real editor/git/terminal/approval workflows; local Monaco workers; typed DTOs; mostly stable entity/path keys. No framework or state-manager replacement needed.

Shell has fixed 48px rail, 280px sidebar, editor, terminal/output utility area, 26px status bar. Office replaces sidebar. No sidebar collapse/resize/persistence. Dark only. One 1091-line CSS file with basic colors but no semantic spacing/typography/radius scale. Duplicate button/input/state patterns and decorative text morphs/pulse effects.

Typed API client: projects/files/search/git/toolchains/terminals/agent and task reads/HITL/oversight/diagnostics. No frontend execution lifecycle, task creation, agent lifecycle, workspace symbol search, settings or runtime-view actions. Toolchain runs must not be mislabeled as orchestration executions.

Wave 3 uses authenticated fetch SSE, authoritative snapshots, sequence/dedup checks, generation isolation, reconnect backoff and degraded-only polling. Timeline capped at 120. Monitoring starts on first Office visit, not project open. Most subscriptions are granular. File children load on demand, Git history capped at 20, Quick Open debounced 120ms. Monaco eager bundle; content in Zustand. BottomPanel unmounts xterm on collapse/switch/output selection, closing its socket.

Shortcuts: Ctrl/Cmd+S saves (also registered in Monaco), Ctrl/Cmd+P opens files. Quick Open input handles arrows/Enter/Escape. Dialogs are custom overlays for project, quick open, diagnostics and explorer input; no shared modal focus management.

## Concrete problems

- Recent-project click sets rootPath then submit reads stale state: may do nothing or open wrong directory. First targeted fix.
- Project switching clears tabs without dirty confirmation and retains terminal IDs/output/git until updates.
- Explorer rename/delete helper awaits fn instead of calling fn(). Empty tree renders Loading forever.
- TreeRow and Explorer subscribe to entire editor store: every edit notifies every mounted node. Git Row defined inside parent remounts. No browser commit-time profile yet.
- Duplicate file/diff requests can create duplicate keys. Quick Open can apply stale responses and hides errors as empty success; recent-project list also hides errors.
- Several async controls lack error feedback. Approvals lack pending guard/error feedback; Office notice is not rendered.
- Office resyncRequired overrides offline as resyncing. Oversight undefined completion permission appears blocked. Connection loss must not imply failed execution.
- Missing error boundaries, focus trapping/restoration, explicit labels and global focus-visible/reduced-motion rules. Diagnostics lacks Escape and close button during loading/error. Tree names, editor tabs and search results are mouse-only; tree actions hover-only.
- Fixed dimensions clip narrow layouts. Arbitrary font sizes, borders/radii/spacing; duplicated Team/Oversight/Diagnostics status mappings.
- API/presentation mixed in Git/Search/Explorer/dialogs. Git working-file fetch and completion POST bypass common authorization. Avoid broad rewrites.

## Proposed minimal changes / likely files

1. Fix explicit recent-project submission in apps/web-ui/src/components/shell/OpenProjectDialog.tsx and add Python Playwright regression for exact submitted path.
2. Refine App/shell/existing store with real command registry, project-scoped monitoring, collapsible/resizable panels and dirty-buffer protection.
3. Reuse index.css and lightweight dialog/status patterns. Contextual state/errors and keyboard controls. Preserve terminal mounts, ResizeObserver, granular tree selectors; disclose recent-only history.
4. Create companion token/interaction documents as changes land. Full Office/Graph/Command Center remain out of scope.

## Baseline and risks

Initial production build passed: main JS 3,871.99 kB, gzip 1,010.91 kB; Vite build 78s, large-chunk warning. ESLint zero errors, one existing CodeEditor Fast Refresh warning. Vitest invoked; capture untruncated totals for final validation. No measured React timing claims; defer virtualization/bundle redesign.

Extensive uncommitted earlier-wave work exists: preserve it, never stage whole repository. Stream changes must preserve StrictMode cleanup/project isolation. Panel hiding must not terminate terminals. No backend orchestration/contract changes planned. No model calls in validation.

## Continuation status (2026-09-17)

Implemented: token layer; searchable palette; App-owned monitoring; offline precedence and snapshot notices; resizable/collapsible persisted panels; retained terminal mounts and ResizeObserver cleanup; dirty-switch/beforeunload guards; project-scoped response checks; duplicate-tab prevention; focus-managed dialogs; view error boundaries; approval pending/error feedback; task execute/pause/resume adapters; granular Explorer selectors and keyboard buttons. The resize separator uses dedicated resize-sidebar/resize-bottom classes to avoid colliding with sidebar layout rules. See frontend-interaction-model.md for limitations and the exact acceptance results. No backend orchestration behavior was changed in this wave.

## Follow-up increment (2026-09-18)

Closed three remaining foundation gaps without backend changes: `execution.build` palette command (existing toolchain endpoint, builder-detected guard); task "Cancel task" in TeamTab and palette via existing FR-014 cancel endpoint (non-finished tasks only, finished tasks keep recorded outcome); last-toolchain-run status in the shell status bar (recorded result + output-panel action, never a live-progress claim). Vitest 35 → 37, task-controls smoke extended for cancel and shell run status; typecheck/lint/palette/shell-status smokes green. Retry of failed tasks, durable execution history, agent lifecycle commands, and problems/runtime/settings views remain explicit gaps (no safe contract or no placeholder policy). Task creation and symbol search previously sat in this gap list; both now exist end-to-end (verified 2026-09-18).

## Verification round (2026-09-18)

Independent verification pass over Phases 1–8, all frontend/test-side:

- Office smoke repaired (accessible-role selectors replacing glyph-sensitive
  exact text and drifted tab indices) — `OFFICE UI SMOKE PASSED` live.
- Registry header + interaction-model counts corrected (28 static + per-task
  controls); verified task/spawn/symbol dialogs perform real API actions.
- Palette, office, and task-controls Playwright smokes green against the live
  stack; Vitest, typecheck, lint, and production build green (see validation).
- No backend changes; backend suite not rerun for this round.

## Validation plan

First fix: deterministic Python Playwright using intercepted project/initialization APIs and submitted-path assertions, no backend/model calls. Run Vitest, TypeScript, lint, production build. Extend browser coverage for palette search/focus/disabled actions, dialogs, desktop/narrow layout, connection transitions, terminal retention and approvals when implemented. Mocked tests do not replace live smokes. Record unfinished work explicitly. Light theme not applicable.
