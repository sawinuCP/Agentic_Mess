# Frontend interaction model — Wave 6 incremental delivery

Status: implemented foundation acceptance run passed on 2026-09-17 (34 unit tests and six offline Chromium scripts). Full requested Wave 6 coverage is NOT claimed: unsupported commands and live-workflow validation gaps are listed below. The acceptance update at the end supersedes the historical incremental sections.

## Shell and monitoring

App selects Explorer/Search/Git/Run/Office through existing Zustand stores. App owns monitoring for the current project ID and stops it on change/unmount. No framework, router, state-manager replacement or backend orchestration changes.

Transport status is distinct from execution status. Offline wins over pending resync; recovery exposes the existing resync action. Office renders snapshot/connection notices rather than treating failed loading as empty success. The status bar additionally surfaces the last toolchain run (`<tool> ✓/✗ <exit>`, e.g. `test ✓`, `build ✗ 1`) from the existing store output; activating it opens the output panel. It reports only the recorded result — never a live progress claim.

Sidebar and utility panels collapse and resize with pointer or keyboard (arrows, Home/End). Size/open preferences persist through the existing store in `harness.layout.v1`, with bounds and storage-failure handling. Sidebar width is viewport-constrained; collapsed views remain reachable from the activity bar. Chromium checks cover 1280px, 820px and 640px scenarios, not every mobile viewport.

Terminal sessions remain mounted while hidden or selecting Output/another terminal. Closing/leaving a project disposes mounts and sockets. ResizeObserver handles geometry changes; delayed initialization and disposed-observer guards avoid xterm StrictMode startup errors. Real xterm DOM identity and intercepted socket counts survive tab/collapse switches in the regression test.

Dirty project switches are rejected with instructions to save/close modified files; browser unload is guarded. Tabs, terminals, git, output and toolchains reset when switching. Stale-response and duplicate-file-open tests cover selected store paths, not all concurrent requests.

## Command palette

Ctrl+K / Cmd+K toggles a conditionally mounted palette. Search matches label, category, and keywords case-insensitively. Arrow keys wrap over enabled commands; Enter executes; Escape closes. Tab/Shift+Tab remain in the combobox. Selection resets to the first enabled result on filtering. Option IDs link to aria-activedescendant. Disabled reasons remain readable. Focus returns to the original element on close. Async command errors remain visible with an alert; repeated execution is guarded while pending. Closing does not cancel an already-started tool request.

Existing Ctrl/Cmd+P and Ctrl/Cmd+S are unchanged. There is no new execution scheduler or simulated agent activity.

### Implemented registry (19 commands)

- Workspace: Open project (includes recent list), Go to file, Search in files, Show changed files.
- Navigation: Show explorer, Show run and toolchains, Open engineering office.
- Execution/tooling: Run active file, Format active file, Run tests, Run build, Show tool output, Open terminal.
- Validation: Run linter, Show system diagnostics.
- Agents/oversight: View active agents (Team), Open event timeline (Activity), Open agent communication (Comms), Open requirement coverage (Oversight).

Toolchain commands are NOT orchestration lifecycle controls. Timeline is the existing bounded event feed, NOT durable execution history or replay. Office is the existing sidebar, NOT the full Agent Office. Project switching is protected against dirty buffers and clears project-scoped terminal IDs.

Additional task-specific commands: Start task execution, Request pause, Send resume signal, Cancel task. Task titles/IDs identify the target; guards require unattempted pending/ready tasks with completed dependencies for start. Pause/resume target an active durable workflow. Cancel targets a non-finished task via the existing `POST /api/tasks/{id}/cancel` human-intervention endpoint (FR-014); finished tasks (completed/cancelled/failed) keep their recorded outcome and the command explains why it is unavailable. Confirmation warns about tool/model use for start, checkpoint semantics for pause/resume, and history preservation for cancel. A signal acknowledgement is explicitly NOT represented as an authoritative paused/running state. Team buttons and palette use the same availability builder and existing POST endpoints, with pending lockout and contextual failures.

### Missing capabilities and required follow-up

Task execute/pause/resume/cancel routes exist; execute/pause/resume/cancel are now exposed and tested with intercepted responses. Failed-task retry remains omitted: re-executing an attempted task has no distinct backend endpoint and loosening the start guard would misrepresent Temporal re-run semantics. Agent creation/session routes exist, but their existence alone does not establish a safe spawn/replace-agent UX.

Not implemented: failed-task retry, durable execution history, task creation, agent lifecycle commands, workspace symbol search, dedicated problems/runtime/settings views, or a Command Center. These are explicit acceptance gaps, not disguised navigation aliases. No inert commands were added.

## States, focus and failure containment

`UiState` provides contextual status/error/retry presentation; `StatusLabel` preserves actual state text and maps known task/agent states to semantic tones. Unknown states never imply success. Office snapshot failures, partial project initialization, permission failures, empty Explorer and recent-only timeline are distinguished. Quick Open surfaces errors and guards stale results. Approval decisions preserve notes, disable repeated submission, report failure and refresh after success.

`useDialogFocus` provides topmost-dialog Tab containment, Escape and focus restoration for existing project, diagnostics, Quick Open and Explorer dialogs. Palette retains its combobox-specific keyboard interaction. Editor tabs and Explorer filenames use native buttons. `ViewBoundary` contains render failures independently in sidebar/editor/utility surfaces. Not all interactive controls have undergone a complete screen-reader/contrast audit.

## Acceptance results — 2026-09-17

- TypeScript: exit 0.
- ESLint: exit 0, one existing CodeEditor Fast Refresh warning.
- Vitest: 8 files, 34 tests passed (registry, task adapters, layout persistence, workspace safety, realtime tests and bounded-projection benchmark).
- Production build: exit 0; latest build 72 seconds. Main JS measured 3,892.75 kB / gzip 1,016.85 kB, versus original about 3,872 / 1,011 kB. Existing large-chunk warning remains.
- `git diff --check`: exit 0.
- Six Python Chromium smokes: all exit 0. Project-picker paths/failure; design-token computed styles/focus/reduced-motion CSS; palette open/search/disabled execution/Tab/Escape/focus/navigation; offline telemetry/resync/820px Office layout; xterm DOM/socket retention/resize persistence/640px navigation/dialog focus; Team and palette task adapters/pending/403/retry plus approval notes/lockout/failure/reject refresh. Page-error assertions passed.

Browser API and PTY endpoints were intercepted. No real provider, model or terminal process was invoked. Task-control and approval browser tests validate frontend request/response handling, not live Temporal execution. No backend contract was modified, so backend tests were not rerun in this acceptance pass.

## Measured performance and limits

Local deterministic fixture: 100 buffer edits produced 100 broad-store notifications and zero directory-child selector invalidations. Explorer now subscribes to required slices instead of the entire store. A 10,000-event reducer loop completed in 880 ms on the final run (1,117 ms on the prior run), retaining 120 events and 512 dedup IDs. Those bounds already existed; no new event-processing performance claim is made. This is a node test with assertion overhead, not browser frame time or a before/after React profile. Terminal identity checks prove retention rather than remount churn.

No speculative virtualization or Monaco redesign. Large-log rendering, large-repository DOM cost, Monaco commit timing, full successful reconnect/recovery flows, real PTY processes and live orchestration remain unprofiled/unverified. Light theme is not present in the product. Token migration/contrast and keyboard coverage remain incremental.

## Final workspace-race regression addendum

A deferred-response test reproduced overlapping project opens replacing a newer selection with an older response. A request-generation guard now ignores superseded project results and initialization notices. The test failed before the fix and passed afterward. Final validation: 35/35 tests, typecheck/lint exit 0, production build exit 0 (56.79s), diff check clean; affected project-picker and terminal-retention smokes passed. The six-script acceptance results above precede this targeted store fix.

## Follow-up increment — 2026-09-18

- Registry 17 → 18 commands: `execution.build` ("Run build") wired to the existing `runTool("build")` toolchain endpoint, guarded by detected build systems (`go`/`cargo`/`dotnet` per the backend registry). No backend change.
- Task stop coverage: `taskCommands` gains "Cancel task" via the existing `POST /api/tasks/{id}/cancel` (FR-014); enabled only for non-finished tasks, exposed identically in TeamTab and the palette with history-preserving confirmation copy. No backend change.
- Shell test/build status: StatusBar shows the last recorded toolchain result with an output-panel action. Label + dot + tooltip; never color alone.
- Tests: Vitest 35 → 37 (build availability/execution, cancel guards); `smoke_task_controls.py` extended with cancel confirm/request/feedback/disabled-state assertions and a palette-driven test run asserting the shell status indicator. Typecheck, lint (one pre-existing warning), palette/shell-status smokes green. Production build validation below still applies.

## Handoff and remaining acceptance gaps

Complete the omitted capability list above and live reconnect/editor/terminal/orchestration acceptance before declaring every Wave 6 requirement met. The current implementation is a tested foundation increment, not full production signoff. Do not begin the full Office/Graph/traceability/replay/Command Center to hide those gaps.

Git: prior-wave realtime files and mixed OfficeView changes remain in the working tree intentionally. Separable Wave 6 commits depend on that existing workspace baseline; they are not a standalone clean-clone release. Preserve and review the earlier-wave changes separately.

No complete Agent Office, graph, replay, traceability explorer, or AI Command Center was implemented.
