// Inline gated-action approval (UI2): the entry pauses on a consequential
// action and asks here — Approve & run / Skip step / Cancel all. Resolves
// the gate waiter in command/gate.ts. No window.confirm anywhere.

import { decideGate } from "../../command/gate";
import type { CenterEntry } from "../../command/types";

export default function ApprovalInline({ entry }: { entry: CenterEntry }) {
  const awaiting = entry.awaiting;
  if (!awaiting) return null;
  return (
    <div className="cc-approval" role="group" aria-label={`Approve ${awaiting.label}`}>
      <div className="text-section">Ready to execute</div>
      <div className="strong small">{awaiting.label}</div>
      {awaiting.detail && <div className="small muted">{awaiting.detail}</div>}
      {entry.intent.confirmReason && (
        <div className="small warn">{entry.intent.confirmReason}</div>
      )}
      <div className="row wrap gap4">
        <button className="btn btn-small btn-primary" onClick={() => decideGate(entry.id, "run")}>
          Approve &amp; run
        </button>
        <button className="btn btn-small" onClick={() => decideGate(entry.id, "skip")}>
          Skip step
        </button>
        <button className="btn btn-small" onClick={() => decideGate(entry.id, "cancel")}>
          Cancel all
        </button>
      </div>
    </div>
  );
}
