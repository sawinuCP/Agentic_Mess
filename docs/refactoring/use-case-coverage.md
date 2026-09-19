# Use-Case Coverage Grading (Phase F0)

Honest grading of UC-01..UC-25 against actual tests (not mentions). Levels:
UNIT_ONLY / INTEGRATION / E2E (real user path incl. UI or full stack) /
EVALUATION / MULTI_LAYER. "Covered?" columns are strict.

| UC | Tests | Level | Main | Failure | Persist | UI | Backend | Realtime | True E2E? |
|---|---|---|---|---|---|---|---|---|---|
| 01 Project | projects_api, project-picker smoke | MULTI_LAYER | ✓ | ✓ (422) | ✓ | ✓ | ✓ | — | YES |
| 02 Requirement | planning/overseer suites, journey | INTEGRATION | ✓ | ✓ (UNKNOWN) | ✓ | — | ✓ | — | PARTIAL (no UI test) |
| 03 Planning | tasks_graph unit, durable_core_api | INTEGRATION | ✓ | ✓ (cycles) | ✓ | — | ✓ | — | PARTIAL |
| 04 Spawn agents | agent_runtime, lifecycle unit | INTEGRATION | ✓ | ✓ | ✓ | — | ✓ | ✓ (events) | PARTIAL |
| 05 Parallel | 8-agent stress, scheduler suite | INTEGRATION | ✓ | ✓ (quota) | ✓ | — | ✓ | — | PARTIAL |
| 06 Comms | message_delivery, eval-metrics | INTEGRATION | ✓ | ✓ (503/orphans) | ✓ | — | ✓ | ✓ (fan-out) | PARTIAL (no UI compose test) |
| 07 Tools | gateway unit, execution, docker | MULTI_LAYER | ✓ | ✓ (deny/timeout) | ✓ | ✓ (output panel smoke) | ✓ | ✓ (TOOL_*) | YES |
| 08 Dependencies | recovery_workflow (pre-check + signal) | INTEGRATION | ✓ | ✓ (deadline) | ✓ | — | ✓ | — | PARTIAL |
| 09 Recovery | recovery_workflow/executor, ladder units | INTEGRATION | ✓ | ✓ (exhaustion) | ✓ | ✓ (timeline shows) | ✓ | ✓ | YES (via smoke timeline) |
| 10 Fallback | provider_retry unit, chaos model test | INTEGRATION | ✓ | ✓ (exhaust) | ✓ (ledger) | — | ✓ | — | PARTIAL |
| 11 HITL | approve/timeout/cancel/race, office smoke | MULTI_LAYER | ✓ | ✓ (timeout/cancel/race) | ✓ | ✓ | ✓ | ✓ | YES |
| 12 Pause | pause workflow test | INTEGRATION | ✓ | ✓ (InvalidTransition regressions) | ✓ | — | ✓ | — | PARTIAL |
| 13 Resume | same test (1-attempt completion) | INTEGRATION | ✓ | ✓ | ✓ | — | ✓ | — | PARTIAL |
| 14 Verification | overseer, gates, journey | INTEGRATION | ✓ | ✓ (blocked gate) | ✓ | ✓ (oversight smoke) | ✓ | — | YES |
| 15 Validation | toolchains unit, run smokes | MULTI_LAYER | ✓ | ✓ (exit codes) | ✓ | ✓ | ✓ | — | YES |
| 16 Browser | browser integration (real chromium, honest skip) | INTEGRATION | ✓ | ✓ | — | — | ✓ | — | PARTIAL |
| 17 MCP | mcp_gateway (round-trip, allowlist, off) | INTEGRATION | ✓ | ✓ (deny/503) | — | ✓ (dialog smoke) | ✓ | — | YES |
| 18 Research | ssrf matrix unit, research integration | INTEGRATION | ✓ | ✓ (blocked) | ✓ (artifacts) | — | ✓ | — | PARTIAL |
| 19 Office | office/reducer/selector units, 3 smokes | MULTI_LAYER | ✓ | ✓ (degraded) | — (projection) | ✓ | ✓ (APIs) | ✓ | YES |
| 20 Graph | build.test.ts, smoke_graph | UNIT+smoke | ✓ | ✓ (absent links) | — | ✓ | ✓ | — | YES |
| 21 Replay | reducer/panel units, smoke_history | MULTI_LAYER | ✓ | ✓ (bounded feed) | ✓ (pages) | ✓ | ✓ | ✓ | YES |
| 22 Evidence | artifact ranges/retention, overseer | INTEGRATION | ✓ | ✓ (404/prune) | ✓ | — | ✓ | — | PARTIAL |
| 23 Command Center | intent unit/perf, smoke_command_center | UNIT+smoke | ✓ | ✓ | — | ✓ | ✓ | — | YES |
| 24 Cost | costs/budgets suites, ledger UI reads | INTEGRATION | ✓ | ✓ (exceeded) | ✓ | — (read-only surfaces) | ✓ | — | PARTIAL |
| 25 History | pagination, HistoryView smoke | MULTI_LAYER | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | YES |

## Corrections to Phase A–E analysis

1. UC coverage is NOT uniformly "test-covered end-to-end": 9 UCs are YES,
   13 PARTIAL (missing UI or live-path leg), 0 NOT_ACTUALLY_COVERED. The
   use-cases.md claim is softened accordingly — the table above governs.
2. `test_browser.py` skips honestly without chromium — UC-16 is environment-
   dependent, not guaranteed.
3. No UC lacks backend coverage entirely. The thinnest legs are UI assertions
   for UC-02/03/04/05/06/08/10/12/13/18/22/24 (backend-proven, UI-unasserted).
