// Phase badge (UI2): icon+label pairing over state-pill tones (never color
// alone). Derivation lives in command/phases.ts (pure, tested).

import { PHASE_META, entryPhase } from "../../command/phases";
import type { CenterEntry } from "../../command/types";
import type { TaskInfo } from "../../types";

export function PhaseBadge({ entry, tasks }: { entry: CenterEntry; tasks: TaskInfo[] }) {
  const phase = entryPhase(entry, tasks);
  const meta = PHASE_META[phase];
  return (
    <span className={`state-pill ${meta.tone}`} title={`Entry phase: ${meta.label}`}>
      <span aria-hidden="true">{meta.glyph} </span>
      {meta.label}
    </span>
  );
}
