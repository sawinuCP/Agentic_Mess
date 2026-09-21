# UI-4 Baseline — Requirements/Traceability/Verification (UI4-01)

Date: 2026-09-20. Source: backend services + routes + frontend, all read directly.

## 1. What exists

* Backend model: `Requirement` (title/description/desired_outcome/priority
  must|should|could/status/version/source) + `AcceptanceCriterion`
  (description/kind automated_test|command|manual/mandatory/status
  unknown|verified|failed) + `Validation` (kind test|build|lint|security|
  requirement, status pending|passed|failed|error, evidence_artifact_id,
  task/criterion links, detail JSON, created_at).
* Derivation (overseer.py): criterion state from own status + validations;
  requirement VERIFIED iff tasks exist AND all mandatory criteria verified;
  FAILED if any mandatory failed; else UNKNOWN. No IN PROGRESS/BLOCKED
  requirement states anywhere in backend.
* Endpoints: list/create/get requirements, create plans, traceability
  report, `POST .../criteria/{id}/verify` (evidence_artifact_id required,
  404 without), completion gate (409 + blockers/warnings, 200 + report
  artifact). Verify endpoint has NO frontend client wrapper.
* Frontend: OversightTab (gate card, coverage, blockers, requirement
  `<details>` cards with criteria pills + linked tasks/owners/evidence
  counts, graph/analyze jumps, review pipeline); GraphDetail requirement
  section; Center `show_traceability` + CompletionReceipt; `ArtifactMetaView`;
  `ApprovalCard(taskIds)`; `collectAttention()`; ContextPanel requirement
  context (basic).

## 2. Already trustworthy

Gate fail-closed logic, evidence-required verification, traceability
report shape, review pipeline display, existing jumps.

## 3. Missing (UI may add without backend changes)

* Verify-criterion UI (endpoint exists, unwired).
* Named evidence links (counts only today).
* Requirement detail narrative (receipts for VERIFIED/FAILED/UNKNOWN).
* Task→requirement entry (inspector shows text only).
* Requirement attention items (failed/blocked verification).
* Dedicated primary surface (office tab is summary-grade).

## 4. Representable directly

Everything in §3 from existing endpoints + store state (tasks, attempts,
events, artifacts metadata, HITL, costs never needed here).

## 5. Requires backend support (GAPS — document, don't fake)

* Per-criterion evidence linkage (report carries states + flat id lists only).
* Verification timestamps/history (no per-requirement/criterion timestamps
  exposed; `generated_at` is snapshot time).
* Requirement-level test rollups (derive from attempts/tool runs, labelled).
* FAILED criterion/requirement production (no UI/test path sets failed
  without Temporal-driven validation failures).
* Requirement creation UI (no endpoint gap — POST exists — but no product
  flow wires it; out of UI-4 scope to invent one).

## 6. Out of scope

Graph/Timeline/Artifact/Diff internals, model/MCP/browser, orchestration,
Temporal/NATS/schema, second store/library/router, pagination framework.

## Go/no-go

GO: the data model supports the full trust chain UI. IN PROGRESS/BLOCKED
surface as derived work-state lines (labelled), never as backend states.
