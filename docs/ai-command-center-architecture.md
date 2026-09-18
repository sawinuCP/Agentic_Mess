# AI Command Center architecture — Wave 10

Status: contract inspection completed before implementation. The central
finding shapes everything below: **no freeform chat/ask/completion endpoint
exists** (`app/api` has zero such routes), the Context Broker has no HTTP
surface, and evaluation is CLI-only. The Command Center is therefore a
**deterministic intent router + structured plan preview + existing-action
dispatcher**: zero model calls from the Center itself, every behavior
unit-testable, no prompt containing the feature list.

## 1. Existing capabilities reused (no new backend)

- Tasks: list/create/execute/pause/resume/cancel (+ bulk/agentscoped fan-out).
- Agents: list/spawn/sessions/messages/operator notes.
- Requirements/traceability/oversight/completion/HITL decide.
- Toolchains run (format/lint/test/run/build) + last-run output panel.
- Code intel: file tree, text search, workspace symbols (palette), **file
  document symbols + hybrid retrieval + research search/fetch** (routes
  exist; thin frontend clients added, no backend change).
- Reviews: `runReview` — the ONE model-backed action the Center dispatches,
  always confirmation-gated and labeled with cost implications.
- Costs ledger, diagnostics, git status/diff/log, artifacts metadata,
  events/history, worktrees, office/graph/timeline views + shared selection.

## 2. Interaction flow

```
Context (auto chips + explicit selects)
   ↓
Natural-language request
   ↓
Deterministic intent classification (high/medium/low confidence)
   ↓
Context assembly (budgeted, redacted, previewable)
   ↓
Structured plan preview (goal/steps/affected/estimates)
   ↓
Confirmation (only when consequential)
   ↓
Existing action dispatch (task/review/tool/research/navigate)
   ↓
Live handoff card (office-store state + costs + surface links)
```

Freeform chat, model synthesis, and prompt-constructed replies are
explicitly OUT — there is no endpoint to back them, and inventing one
client-side would fake autonomy.

## 3. Intent model (`src/intent/`)

`EngineeringIntent { intentType, request, scope{project/requirement/task/
agent/file+selection/symbol}, requestedOutcome, constraints,
confirmationRequired + reason, confidence }`. Rule-based classification over
(verbatim text, resolved scope): 16 types (implement, fix, explain×2,
usages, affected, run_tests, review×3, create_plan, start/control execution,
open_surface, architecture, research, cost, unknown). "This" resolves via
scope priority (explicit mention > selection > focused entity > project).
Ambiguous input clarifies with selectable scope — never guesses. The 14
§34 evaluation cases are a deterministic unit table over this function.

## 4. Context assembly (`src/context/assemble.ts`)

Client-side T0–T3 (+T4 attempts/events, +T5 artifact refs only), mirroring
broker tiering without duplicating it: T0 action/scope/safety, T1 selected
entity + task + requirement, T2 file slice (≤80 lines around selection) +
symbols (≤15) + related tests via retrieval (≤6), T3 execution state +
agents + deps + recent events (≤10). Budgets enforced, secrets redacted via
the shared sanitizer, and the assembled context is previewable — nothing
hidden. Editor selection tracked in the store (≤2000 chars).

## 5. Modes, responses, handoff

Modes are scope presentation (Project/Requirement/Code/Error/Agent/
Execution chips), not separate flows. Responses are typed cards:
derived-analysis (deterministic facts labeled as such), plan preview,
live-execution (store-driven), evidence (refs + metadata), navigation.
"Explanations" are structured code facts (symbols, dependents, tests,
commits, coverage) — generative explanation is declined for lack of an
endpoint. Handoff shows live task status/attempts/costs + office/graph/
timeline links; AI statements and evidence are visually separated (§20).

## 6. Confirmation, HITL, errors, costs

Confirmation gates: execute/retry/cancel/stop/bulk, tool runs, research
network calls, model-backed reviews. Read-only intel never confirms.
HITL decide flows reused untouched. Failures map to contextual recovery
(401/403 admin guidance, 503 research-disabled, offline, timeouts) with
expandable diagnostics — never raw stack traces as the primary surface.
Costs shown from the ledger on execution cards (tokens/calls/budget).

## 7. State, performance, security, a11y

Conversation = bounded (20) structured entries (request + intent + action
refs only — no tool outputs, no payload values). No per-event store writes;
memoized derivation; lazy detail loads; artifact refs. Perf test: 1k intent
parses + 100-turn render model. Security: project-scoped calls, redacted
previews, confirmations, existing auth/HITL. A11y: native controls,
aria-live plan/result announcements, focus-in on open, reduced-motion
(nothing animates anyway), never color-alone.

## 8. Explicitly declined (with reason)

- Generative chat/synthesis (no endpoint; would fake autonomy).
- Conversation branching (no supporting infra; risks mutating main execution).
- MCP-call UI (gateway stays backend-owned; research covers the required
  external-info path).
- New keyboard shortcuts (Ctrl+J/Ctrl+E conflict with browser/Monaco;
  palette-only, documented).
- Backend eval-harness changes (CLI harness is model-quality oriented;
  routing accuracy is unit-evaluated instead).
