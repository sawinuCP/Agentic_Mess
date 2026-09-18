// MCP tool-call dialog (Wave 10 completion): discovery + authorized
// invocation over the existing gateway routes. Every call confirms first
// (the gateway enforces its own deny/approval policy server-side), results
// render truncated with artifact refs, and the disabled gateway explains
// itself instead of failing silently.

import { useEffect, useState } from "react";

import { errorMessage } from "../../api/errors";
import {
  mcpCall,
  mcpDiscover,
  mcpStatus,
  parseMcpArgs,
  type McpCallResult,
  type McpServerDef,
} from "../../api/client";
import { useStore } from "../../state/store";
import { useDialogFocus } from "./useDialogFocus";

function summarizeContent(content: unknown): string {
  const text = typeof content === "string" ? content : JSON.stringify(content, null, 2);
  return text.length > 2000 ? `${text.slice(0, 2000)}…[truncated, see artifact]` : text;
}

export default function McpDialog({ onClose }: { onClose: () => void }) {
  const dialogRef = useDialogFocus(onClose);
  const [status, setStatus] = useState<{ enabled: boolean } | null>(null);
  const [servers, setServers] = useState<McpServerDef[]>([]);
  const [server, setServer] = useState("");
  const [tool, setTool] = useState("");
  const [args, setArgs] = useState("{}");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<McpCallResult | null>(null);
  const setWorkspace = useStore((s) => s.set);

  useEffect(() => {
    let active = true;
    mcpStatus()
      .then((s) => { if (active) setStatus({ enabled: s.enabled }); })
      .catch((err: unknown) => { if (active) setError(errorMessage(err)); });
    return () => { active = false; };
  }, []);

  const discover = async (): Promise<void> => {
    setBusy(true);
    setError(null);
    try {
      const res = await mcpDiscover();
      setServers(res.servers);
      const first = res.servers[0];
      if (first) {
        setServer(first.server);
        setTool(first.tools[0]?.name ?? "");
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const tools = servers.find((s) => s.server === server)?.tools ?? [];
  const parsed = parseMcpArgs(args);

  const call = async (): Promise<void> => {
    if (!server || !tool || !parsed.ok || busy) return;
    if (!window.confirm(
      `Call MCP tool ${server}.${tool}?\n\nExternal side effects apply. The gateway enforces its deny/approval policy server-side.`,
    )) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await mcpCall(server, tool, parsed.value);
      setResult(res);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="overlay" onClick={onClose}>
      <div
        className="dialog"
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label="Call MCP tool"
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
      >
        <h2>Call MCP tool</h2>
        {error && <p role="alert" className="error-text">{error}</p>}
        {status !== null && !status.enabled && (
          <p className="muted small">
            The MCP gateway is disabled on this server
            (HARNESS_MCP_ENABLED=true required). Discovery and calls will return 503.
          </p>
        )}
        <div className="row wrap gap4">
          <button className="button secondary" disabled={busy} onClick={() => void discover()}>
            {busy ? "Working…" : "Discover servers"}
          </button>
          <button className="button secondary" onClick={onClose}>Close</button>
        </div>
        {servers.length > 0 && (
          <>
            <label className="small stack">
              Server
              <select className="text-input" aria-label="MCP server" value={server} onChange={(e) => {
                setServer(e.target.value);
                setTool(servers.find((s) => s.server === e.target.value)?.tools[0]?.name ?? "");
                setResult(null);
              }}>
                {servers.map((s) => (
                  <option key={s.server} value={s.server}>
                    {s.server}{s.error ? ` (discovery error)` : ""}
                  </option>
                ))}
              </select>
            </label>
            <label className="small stack">
              Tool
              <select className="text-input" aria-label="MCP tool" value={tool} onChange={(e) => { setTool(e.target.value); setResult(null); }}>
                {tools.map((t) => (
                  <option key={t.name} value={t.name}>
                    {t.name}{t.allowed ? "" : " (not allowed)"}{t.description ? ` — ${t.description.slice(0, 80)}` : ""}
                  </option>
                ))}
              </select>
            </label>
            <label className="small stack">
              Arguments (JSON object)
              <textarea
                className="text-input mono"
                aria-label="MCP arguments JSON"
                rows={4}
                value={args}
                onChange={(e) => setArgs(e.target.value)}
              />
            </label>
            {!parsed.ok && <p role="alert" className="error-text small">{parsed.error}</p>}
            <div className="dialog-actions">
              <button className="button" disabled={!server || !tool || !parsed.ok || busy} onClick={() => void call()}>
                {busy ? "Calling…" : "Call tool"}
              </button>
            </div>
          </>
        )}
        {result && (
          <div className="stack small">
            <div className={`state-pill tiny ${result.is_error ? "down" : "ok"}`}>
              {result.is_error ? "tool reported an error" : "tool completed"}
            </div>
            <pre className="raw-payload mono">{summarizeContent(result.content)}</pre>
            {result.artifact_id && (
              <span className="muted">
                Full result stored as artifact{" "}
                <span className="mono">{result.artifact_id.slice(0, 8)}</span>
                <button
                  className="link"
                  onClick={() => {
                    const id = result.artifact_id ?? "";
                    if (navigator.clipboard) {
                      void navigator.clipboard.writeText(id)
                        .then(() => setWorkspace({ notice: "Artifact reference copied." }))
                        .catch(() => setWorkspace({ notice: `Artifact reference: ${id}` }));
                    } else {
                      setWorkspace({ notice: `Artifact reference: ${id}` });
                    }
                  }}
                >
                  (copy reference)
                </button>
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
