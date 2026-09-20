// Artifact evidence preview (UI2): metadata + small text preview + raw
// download for an evidence artifact. Uses only existing endpoints
// (/api/artifacts/{id}, /content). Binary/large blobs get an honest
// download link instead of a fake preview. Size-guarded fetch (64 KiB).

import { useEffect, useState } from "react";

import ArtifactMetaView from "../shared/ArtifactMeta";
import { useDialogFocus } from "../shell/useDialogFocus";

const PREVIEW_LIMIT = 64 * 1024;

export default function ArtifactPreview({ artifactId, onClose }: {
  artifactId: string;
  onClose: () => void;
}) {
  const dialogRef = useDialogFocus(onClose);
  const [text, setText] = useState<string | null>(null);
  const [previewState, setPreviewState] = useState<"loading" | "ready" | "unavailable">("loading");
  const contentUrl = `/api/artifacts/${encodeURIComponent(artifactId)}/content`;

  useEffect(() => {
    let active = true;
    fetch(contentUrl, { headers: { Range: "bytes=0-65535" } })
      .then((response) => {
        if (!active) return;
        const type = response.headers.get("content-type") ?? "";
        if (!response.ok || (!type.startsWith("text/") && !type.includes("json"))) {
          setPreviewState("unavailable");
          return;
        }
        return response.text().then((body) => {
          if (!active) return;
          setText(body.slice(0, PREVIEW_LIMIT));
          setPreviewState("ready");
        });
      })
      .catch(() => { if (active) setPreviewState("unavailable"); });
    return () => { active = false; };
  }, [contentUrl]);

  return (
    <div className="overlay">
      <div
        ref={dialogRef}
        className="dialog artifact-preview anim-enter"
        role="dialog"
        aria-modal="true"
        aria-label="Evidence artifact preview"
      >
        <div className="row spread">
          <span className="text-heading">Evidence</span>
          <button className="tree-action" title="Close preview" aria-label="Close preview" onClick={onClose}>×</button>
        </div>
        <ArtifactMetaView artifactId={artifactId} />
        {previewState === "loading" && <p className="muted small">Loading preview…</p>}
        {previewState === "ready" && text !== null && (
          <pre className="artifact-preview-body text-code">{text}</pre>
        )}
        {previewState === "unavailable" && (
          <p className="muted small">No text preview for this artifact kind. The raw bytes are intact.</p>
        )}
        <div className="row dialog-actions">
          <a className="btn btn-small" href={contentUrl} download>
            Download raw
          </a>
          <button className="btn btn-small" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}
