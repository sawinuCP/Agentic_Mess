# Agent Office performance — Wave 7

Measured 2026-09-18. Strategy per `docs/agent-office-architecture.md` §6:
bounded lists, memoized derivation, lazy detail sections. No virtualization
— the measurements below say it is not needed at the required scale
(10–50+ agents, hundreds of tasks, thousands of events).

## Derivation baseline (node, no React)

`src/office/derivationPerformance.test.ts` — synthetic 50 agents / 500 tasks
with attempts / 5000 events, projecting the full control-room mapping
(agent→tasks, current task, 120-row timeline grouping, 120 task recovery
chains, execution summary):

```json
{"benchmark":"wave7-derivation","agents":50,"tasks":500,"events":5000,
 "ownedMappings":500,"groups":120,"tasksWithRecovery":20,
 "summary":"Needs attention","elapsedMs":9}
```

9 ms for the entire selector layer. The per-render cost is a fraction of
that: components memoize over store slices (`useMemo` on `agents/tasks/
events`), and only visible rows derive (team cards, at most 120 grouped
timeline rows, one detail panel at a time).

## Bounds (existing or mirrored)

| Surface | Bound | Where |
|---|---|---|
| Timeline events | 120 | `eventReducer.MAX_TIMELINE_EVENTS` (pre-existing) |
| Grouped activity rows | ≤ 120 input rows | `ActivityTab` groups the bounded feed |
| Messages | 200 merged, 40/agent inbox | `officeStore.loadMessages` (+ id dedupe) |
| Worktrees | 100 | `listWorktrees` limit |
| Costs | 1000-row server cap | backend `costs.summary` (pre-existing) |
| Event dedup window | 512 ids | `eventReducer` (pre-existing) |
| Detail lists | 6–10 rows/section | `AgentDetail` slices (activity 8, tools 6, files 10, comms 10) |
| Agent timeline filter | agents in snapshot | `<select>` over recorded agents only |

## Rendering behavior

- SSE envelopes project incrementally via the pure reducer; a resync
  replaces snapshots wholesale (authoritative, unchanged from Wave 3).
- Messages/worktrees/costs fetch once per project on first view open
  (store-guarded `*Loading` flags); tab switches never refetch.
- Bulk execution fans out sequentially (never parallel bursts against the
  control plane), then performs a single resync; per-task results are
  reported, so partial failures are visible rather than silent.
- `AgentDetail` mounts only for the selected agent; closing it unmounts all
  sections (no hidden DOM accumulation).
- Timeline grouping is O(n) over the bounded feed per render input change.
- No `setInterval` polling added: the 1 s office clock (relative-time label)
  and the degraded-mode 10 s fallback poll pre-date this wave.

## Production build

`npm run build` (tsc + vite): exit 0. Main chunk ~3,894 kB / gzip ~1,017 kB
— Monaco-dominated, unchanged from the Wave 6 baseline; the Office delta is
new components + one tab, no new dependencies.

## What was NOT optimized (deliberately)

- No list virtualization: 9 ms derivation + ≤120 rendered rows need none.
- No Monaco/xterm changes: editor/terminal paths untouched.
- No event-store redesign: the 120-event cap is a product decision
  (bounded feed, disclosed in-UI), not a perf workaround.
- Browser frame timing / large-repo tree cost remain unprofiled (same as
  Wave 6 handoff); the numbers above are node-side derivation only.

## Regression coverage for scale

- `derivationPerformance.test.ts`: 50/500/5000 projection < 5 s guard +
  mapping-count assertions (fails on accidental quadratic blowups).
- `foundationPerformance.test.ts` (Wave 6): 100-edit selector invalidation
  + 10,000-event reducer bound — still green.
- `smoke_agent_office.py`: multi-agent fixture renders without page errors.
