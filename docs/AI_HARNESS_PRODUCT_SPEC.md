# AI Harness Code Editor — Normalized Product Specification (Index)

**Status:** authoritative index · **Source of truth:** `AI_Harness_Code_Editor_Complete_Implementation_Specification.md` (repo root)
**Note:** the `.docx` variant named in the master plan is not present in this repository. The markdown
specification is the working authoritative copy (ADR-0009 in `ARCHITECTURE.md` records that the provided
`.md` matches the archived `.docx`). This document normalizes it into a searchable requirement index so
implementation and audit work can reference stable IDs. No requirement here is invented: every ID maps to
the authoritative specification.

## 1. Canonical execution model

```
Requirement → Task → Agent → Context → Tool → Artifact → Validation → Evidence → Task completion
```

Invariants (spec §4, §30):

- **Durable:** requirements, tasks, code, artifacts, evidence, execution history.
- **Replaceable:** agents, models, tools, containers/runtimes.
- The database is the source of truth; no critical execution state may live only in an
  in-memory agent process.

## 2. Functional requirements (FR)

| ID | Requirement (abbreviated) | Spec § |
|----|---------------------------|--------|
| FR-001 | Open/create/clone/manage local projects | §6 |
| FR-002 | Arbitrary languages via configurable toolchains | §7 |
| FR-003 | Detect project languages/build systems | §7 |
| FR-004 | Configure compilers/interpreters/formatters/linters/test runners/debuggers/package managers/LSP | §7 |
| FR-005 | Accept natural-language requirements + desired outcomes | §8 |
| FR-006 | Decompose requirements into durable tasks | §9 |
| FR-007 | Dynamically spawn agents per task requirements | §10 |
| FR-008 | Agents disposable/replaceable without losing task identity | §11 |
| FR-009 | Bounded concurrent multi-agent execution | §10 |
| FR-010 | Agent communication (messages, artifacts, dependency unblocking) | §14 |
| FR-011 | Bounded scheduler | §13 |
| FR-012 | Worktree isolation + controlled integration | §17 |
| FR-013 | Code intelligence (symbols/retrieval) | §16 |
| FR-014 | HITL approvals/interventions | §25 |
| FR-015 | Pause/resume without destroying durable state | §27 |
| FR-016 | Classify failures, bounded recovery | §26 |
| FR-017 | Independent validation of high-risk decisions (review/debate) | §24 |
| FR-018 | Isolated runtimes for execution | §19 |
| FR-019 | Compiler/interpreter + formatter as first-class tools | §7 |
| FR-020 | Browser-based debugging | §20 |
| FR-021 | MCP discovery/invocation/permissions | §21 |
| FR-022 | Web research with evidence/provenance | §22 |
| FR-023 | Normalize/compress tool observations pre-context | §15 |
| FR-024 | Persist events/artifacts/audit info | §28 |
| FR-025 | Engineering-office UI for live agent activity | §36-37 |
| FR-026 | No completion from agent self-report alone | §23 |
| FR-027 | Final evidence-backed completion report | §23 |
| FR-028 | Editor usable without AI | §5 |
| FR-029 | Project-level configuration, no hard-coded framework | §7 |
| FR-030 | Security boundaries independent of model instructions | §31 |

## 3. Quality-attribute families

| Family | IDs | Spec § |
|--------|-----|--------|
| Language/toolchain | LANG-001..005 | §7 |
| Task/recovery | TASK-001..003 | §13 |
| Messaging | MSG-001..003 | §14 |
| Context | CTX-001..004 | §15 |
| Recovery | REC-001..003 | §26 |
| Security | SEC-001..007 | §31 |
| Performance | PERF-001..008 | §43 |
| Acceptance criteria | AC-001..018 | §44 |

## 4. Required UI experiences (spec §36–§41)

Code editor (always usable) · AI command center · Agent office (live team) ·
Execution graph (real time, zoom/pan/inspect) · Requirements + traceability
(REQ → TASK → AGENT → FILE → COMMIT → TEST → VERIFIED) · Diff/review · Runtime
· Terminal · Browser preview · History/timeline with filters · Diagnostics ·
Command palette (Ctrl+K, searchable) · contextual AI actions on
selection/tests/requirements · production states (loading/empty/error/offline/
reconnecting) · accessibility (keyboard-first, ARIA, reduced motion).

## 5. Non-goals / explicit deferrals

Tracked in `docs/IMPLEMENTATION_STATUS.md` (post-completion deferred register) and
`docs/REQUIREMENTS_MATRIX.md`. Nothing in this index adds requirements beyond the
authoritative specification.
