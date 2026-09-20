# UI-1 Follow-ups (UI-0.5 §23 — recorded, not expanded)

## 1. docs/frontend-interaction-model.md reference

*Class: Documentation — RESOLVED.* The file DOES exist at `docs/`
root (not `docs/ui-ux/`); the references in `commands/registry.ts:8`
and `CommandPalette.tsx:7` resolve. No action needed.

## 2. dispatch_tool hardcodes runTool("test")

*Class: Frontend correctness.* `CenterView.tsx:347-355` always runs the
`test` tool regardless of intent. *Do now:* nothing (Center internals are
UI-7). *Later:* resolve tool from intent/plan in UI-7. *Out of scope:* no.

## 3. window.confirm at gated/research paths

*Class: Frontend correctness / Architecture (UX).*
`CenterView.tsx:387,409`, `McpDialog`, `TeamTab` control confirm,
`RuntimeView` release. UI-1 created the replacement primitive
(`shell/confirm.ts` + `ConfirmHost`, piloted on terminal close) but
deliberately did NOT migrate feature flows. *Later:* migrate per surface
in UI-3..UI-6 with per-flow validation. *Out of scope:* backend confirm
semantics (none exist — all client-side).

## 4. Tasks/Requirements rail doors share the office surface

*Class: Architecture (UX).* Rail has Tasks + Requirements doors but no
dedicated views exist yet; both deep-link into office tabs. *Later:*
dedicated views in UI-3 (tasks) / UI-4 (requirements); doors already point
at the right tabs. *Out of scope:* backend.

## 5. Model/provider configuration has no UI surface

*Class: Backend gap (documented, not faked).* Spawn takes free-text model;
no list/edit/keys/budgets UI. Settings shows client prefs only. *Later:*
models section reads `models_config_path`; edit capability requires
backend support — GAP until then. *Out of scope for UI phases:* backend.

## 6. In-progress tool activity not exposed

*Class: Backend gap.* Code explicitly notes it (`AgentDetail`). UI-1 labels
idle state honestly instead. *Later:* backend event → ToolStream rows.
