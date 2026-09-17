# Frontend design system — Wave 6 Phase 2

Scope: a restrained token layer over the existing single-CSS-file approach. No component library, no second styling system, dark theme only (no light theme exists to support). Primitives keep the original variable names so existing rules, Monaco, and xterm themes remain valid. Source of truth: `apps/web-ui/src/index.css` (section 1).

## Application of tokens

Semantic tokens alias primitives; utility classes, tree, tabs, panel, status bar, state pills, approval/reject buttons and badges consume them. Dialog/button/input migration is incomplete; some tokens are reserved rather than applied. Feature-specific one-off values remain and migrate opportunistically; new styles must use tokens.

## Typography

| Token | Value | Role |
|---|---|---|
| `--text-2xs` | 10px | badges, severity/risk chips |
| `--text-xs` | 11px | metadata, status bar, section labels |
| `--text-sm` | 12px | secondary text, dense lists, terminal |
| `--text-md` | 13px | body/default |
| `--text-lg` | 15px | dialog/page titles |
| `--text-xl` | 18px | application title (reserved) |
| `--font-sans` / `--font-mono` | Segoe UI / ui-monospace | prose / code+terminal (`.mono`) |
| `--weight-strong` `--weight-bold` | 600 700 | `.strong`, badges |
| `--tracking-label` | 0.8px | uppercase section labels |

## Spacing scale

`--space-1..5` = 4 / 8 / 12 / 16 / 24 px. Utility classes (`.pad`, `.stack`, `.row`) and shared panels use the scale; arbitrary gaps migrate opportunistically.

## Surfaces

`--surface-app` `#0f1117` (app background) · `--surface-workspace` `#0d1017` (tab strip, panel, status bar) · `--surface-panel` `#171a23` (cards, active tab) · `--surface-panel-alt` `#13161e` (sidebar, tabs) · `--surface-elevated` `#1c2030` (dialogs, popovers) · `--surface-selected` / `--surface-hover` accent washes (selected/hovered item) · `--surface-code` `#101319` (matches Monaco `harness-dark`; terminal uses `#0d1017`).

## Borders & radius

1px borders: `--border` (default), `--border-strong` (emphasis), `--border-soft` (subtle dividers). Radius: `--radius-sm` 4 (badges) · `--radius-md` 6 (buttons, inputs, activity) · `--radius-lg` 8 (cards) · `--radius-xl` 10 (dialogs, approval cards) · `--radius-full` (pills/chips).

## Semantic states

Colors: ok `#2ecc71`, warn `#e6b450`, down `#e74c3c`, accent `#5b8cff`, muted `#8b93a7`, each with `--*-bg` / `--*-border` translucent washes. Current mapping (existing classes; never color alone — every pill carries its text label, dots pair with titles/text):

| State | Presentation |
|---|---|
| Running / live / completed / verified | `.state-pill.ok`, `.live-dot.on` |
| Paused | Existing task/agent `.state-pill.warn` |
| Blocked / waiting / recovering | `StatusLabel` preserves contract text with warning tone in Team view |
| Degraded / resyncing / connecting / reconnecting | Explicit connection text, separate from execution status |
| Failed / rejected / offline | Explicit text plus `.state-pill.down` / contextual error feedback |
| Permission denied | HTTP 401/403 explanation from `errorMessage`, with authentication/access guidance |
| Blocked task (dependency wait) | Warning-tone status text; execution disabled until dependencies are completed |
| Requires approval | `.approval-card` warn border + risk badge text |
| Paused execution | `paused` pill (warn) |

Wave 3 connection states (live/connecting/reconnecting/offline/degraded/resyncing) remain presentation-distinct in the Office header; a disconnected stream must never render as a failed execution.

## Accessibility rules

- Never color alone: state always pairs color + text label (+ icon/dot where present).
- `:focus-visible` 2px accent outline globally; `.visually-hidden` helper for icon-only labels. Existing input-specific focus rules may override the outline; full focus/contrast auditing remains required.
- `prefers-reduced-motion` disables decorative animation (live-dot pulse, card entrance) globally.

## Validation

`scripts/smoke_design_tokens.py` (Playwright, intercepted APIs) asserts computed body/button token application, visible keyboard focus ring, and the reduced-motion rule; passing as of this phase. The existing suite, typecheck, lint, and production build must stay green on every token migration commit.
