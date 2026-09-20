// Completion receipt (UI2): what ran, what it produced, and where to look.
// Never claims more than recorded state: dispatches (ran/skipped with
// detail), reviewer verdicts (claim, not verification), finding refs
// (evidence links), and jumps. Verification itself lives in Requirements.

import { useState } from "react";

import type { CenterEntry } from "../../command/types";
import { useOffice } from "../../state/officeStore";
import { useStore } from "../../state/store";
import ArtifactPreview from "./ArtifactPreview";

export default function CompletionReceipt({ entry }: { entry: CenterEntry }) {
  const setWorkspace = useStore((s) => s.set);
  const tasks = useOffice((s) => s.tasks);
  const [previewId, setPreviewId] = useState<string | null>(null);

  const ran = entry.dispatches.filter((d) => d.ok);
  const skipped = entry.dispatches.filter((d) => !d.ok);
  const verdicts = entry.dispatches.map((d) => d.reviewVerdict).filter((v): v is string => !!v);
  const evidence = entry.findings.filter((f) => f.artifactId);
  const linkedIds = new Set(entry.dispatches.map((d) => d.taskId).filter((id): id is string => !!id));
  const openWork = tasks.some((t) => linkedIds.has(t.id) && !["completed", "cancelled", "failed"].includes(t.status));

  return (
    <div className="cc-receipt">
      <div className="text-section">Receipt</div>
      {ran.length > 0 && (
        <ul className="plain-list small">
          {ran.map((d, i) => (
            <li key={i}>✓ {d.label}{d.detail ? <span className="muted"> — {d.detail}</span> : null}</li>
          ))}
        </ul>
      )}
      {verdicts.length > 0 && (
        <p className="small">Reviewers: {verdicts.join(", ")} <span className="muted">(claim — verify in Requirements)</span></p>
      )}
      {evidence.length > 0 && (
        <div className="row wrap gap4">
          {evidence.map((f, i) => (
            <button key={i} className="btn btn-small" onClick={() => f.artifactId && setPreviewId(f.artifactId)}>
              View evidence: {f.title.slice(0, 40)}
            </button>
          ))}
        </div>
      )}
      {skipped.length > 0 && (
        <p className="small muted">Skipped: {skipped.map((d) => d.label).join(", ")}</p>
      )}
      {openWork && (
        <p className="small muted">Request complete — work continues in Agents.</p>
      )}
      <div className="row wrap gap4">
        <button className="btn btn-small" onClick={() => setWorkspace({ view: "git", sidebarOpen: true })}>
          Review changes
        </button>
        <button className="btn btn-small" onClick={() => setWorkspace({ view: "office", sidebarOpen: true })}>
          Inspect in Agents
        </button>
      </div>
      {previewId && <ArtifactPreview artifactId={previewId} onClose={() => setPreviewId(null)} />}
    </div>
  );
}
