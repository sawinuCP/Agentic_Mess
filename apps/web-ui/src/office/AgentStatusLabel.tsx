// Canonical agent status label (UI3): icon + text, never color alone.
// Display-only translation of backend lifecycle states (§7 blueprint);
// unknown states pass through muted. Tasks keep StatusLabel unchanged.

import { agentStatus } from "./agentStates";

export default function AgentStatusLabel({ state }: { state: string }) {
  const meta = agentStatus(state);
  return (
    <span className={`state-pill ${meta.tone}`} title={`Agent state: ${state}`}>
      <span aria-hidden="true">{meta.glyph} </span>
      {meta.label}
    </span>
  );
}
