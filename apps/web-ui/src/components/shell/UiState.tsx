import type { ReactNode } from "react";

export function UiState({ title, children, error = false, retry }: {
  title: string; children?: ReactNode; error?: boolean; retry?: () => void;
}) {
  return <div className={`pad ${error ? "error-text" : "muted"}`} role={error ? "alert" : "status"}>
    <strong>{title}</strong>{children && <div>{children}</div>}
    {retry && <button className="button secondary" onClick={retry}>Retry</button>}
  </div>;
}

const tones: Record<string, string> = {
  running: "ok", working: "ok", completed: "ok", verified: "ok",
  waiting: "warn", blocked: "warn", paused: "warn", pending: "warn",
  recovering: "warn", resuming: "warn", retrying: "warn", requires_approval: "warn",
  verifying: "warn",
  planning: "muted",
  failed: "down", lost: "down", cancelled: "muted",
};

// Text glyphs (aria-hidden): status is never color-alone. Glyphs use text
// presentation only — no emoji.
const glyphs: Record<string, string> = {
  running: "▶", working: "▶", resuming: "▶",
  paused: "⏸",
  completed: "✓", verified: "✓",
  failed: "✗", lost: "✗",
  waiting: "!", blocked: "!", pending: "!", recovering: "!",
  retrying: "!", requires_approval: "!", verifying: "!",
};
// Preserve the actual contract string: unknown values never become success.
export function StatusLabel({ state }: { state: string }) {
  return (
    <span className={`state-pill ${tones[state] ?? "muted"}`}>
      <span aria-hidden="true">{glyphs[state] ?? "•"} </span>
      {state.replaceAll("_", " ")}
    </span>
  );
}
