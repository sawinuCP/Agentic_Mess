// Shared artifact metadata reader: name/kind/MIME/size/SHA on demand.
// Raw content is never fetched here (graph and timeline show metadata only).

import { useEffect, useState } from "react";

import { getArtifact, type ArtifactMeta } from "../../api/client";
import { errorMessage } from "../../api/errors";

export default function ArtifactMetaView({ artifactId }: { artifactId: string }) {
  const [meta, setMeta] = useState<ArtifactMeta | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    getArtifact(artifactId)
      .then((row) => { if (active) setMeta(row); })
      .catch((err: unknown) => { if (active) setError(errorMessage(err)); });
    return () => { active = false; };
  }, [artifactId]);
  if (error) return <span className="error-text small">metadata unavailable ({error})</span>;
  if (!meta) return <span className="muted small">loading metadata…</span>;
  return (
    <span className="small" title={`sha256 ${meta.sha256}`}>
      {meta.name} · {meta.kind} · {meta.mime} · {meta.size} bytes
    </span>
  );
}
