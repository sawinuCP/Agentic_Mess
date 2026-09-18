# AI Command Center performance — Wave 10

Measured 2026-09-18 (`src/intent/performance.test.ts`, node-side).

## Derivation measurements

```json
{"benchmark":"wave10-command-center","requests":1000,"gated":400,"elapsedMs":169}
```

1,000 requests classified, planned, identifier-extracted, and
context-assembled in 169 ms. Consequences:

- **No virtualization needed** for intent/context work: routing is
  microseconds per request by construction (ordered rules, no model).
- **Conversation history is bounded at 20 entries** holding references and
  labels only (no tool outputs, no payload values) — DOM cost stays flat no
  matter how long the session runs.
- **No per-event store writes**: the Center subscribes to existing office
  slices (tasks for live handoff, ledger once per project); SSE traffic
  causes no Center-specific rerenders beyond those shared subscriptions.
- **Lazy everything**: symbols/retrieval/research/costs/requirements fetch
  on demand per action; detail sections mount per entry; artifact content is
  never fetched.

## Live-handoff cost

Handoff cards subscribe to the office task list (already live). No extra
polling, no duplicate context retrieval: intel actions run once per entry
and cache results in the entry's findings.
