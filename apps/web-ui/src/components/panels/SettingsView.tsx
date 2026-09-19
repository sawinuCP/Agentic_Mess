import { useState } from "react";
import { getApiToken, setApiToken } from "../../api/client";
import { useOffice } from "../../state/officeStore";
import { useStore } from "../../state/store";
import { defaultLayout } from "../../state/layout";
import { StatusLabel } from "../shell/UiState";

// Settings view: local client configuration over existing mechanisms (Wave 6).
//
// Everything here acts on real local state: the bearer token in localStorage
// (used by subsequent API/WebSocket connections), the persisted panel layout,
// and live connection telemetry from the office store. No backend calls.

const LAYOUT_KEY = "harness.layout.v1";

export default function SettingsView() {
  const setFn = useStore((s) => s.set);
  const theme = useStore((s) => s.theme);
  const connectionState = useOffice((s) => s.connectionState);
  const gatewayMode = useOffice((s) => s.gatewayMode);
  const lastEventSequence = useOffice((s) => s.lastEventSequence);
  const [token, setToken] = useState("");
  const [saved, setSaved] = useState(getApiToken() !== "");
  const [notice, setNotice] = useState<string | null>(null);

  const saveToken = () => {
    setApiToken(token.trim());
    setToken("");
    setSaved(getApiToken() !== "");
    setNotice(
      "Token saved. It applies to new API requests and realtime connections; reload the page for a fully clean session.",
    );
  };

  const clearToken = () => {
    setApiToken("");
    setSaved(false);
    setNotice("Token cleared. The API is reachable only in local loopback mode without it.");
  };

  const resetLayout = () => {
    try {
      localStorage.removeItem(LAYOUT_KEY);
    } catch {
      // Storage may be disabled; defaults below still apply to this session.
    }
    setFn({ ...defaultLayout });
    setNotice("Panel layout reset to defaults.");
  };

  return (
    <aside className="sidebar">
      <header className="sidebar-header">SETTINGS</header>
      <div className="pad stack">
        <section>
          <h3 className="section-title">API token</h3>
          <p className="muted small">
            Bearer token for the control plane (Wave 1 auth). Status:{" "}
            <StatusLabel state={saved ? "verified" : "waiting"} />
          </p>
          <div className="row">
            <input
              className="text-input"
              type="password"
              aria-label="API token"
              placeholder={saved ? "Token is set — enter a new one to replace" : "Enter API token"}
              value={token}
              onChange={(e) => setToken(e.target.value)}
            />
          </div>
          <div className="row">
            <button className="button" disabled={token.trim() === ""} onClick={saveToken}>
              Save token
            </button>
            <button className="button secondary" disabled={!saved} onClick={clearToken}>
              Clear token
            </button>
          </div>
        </section>
        <section>
          <h3 className="section-title">Appearance</h3>
          <p className="muted small">
            Interface theme. Applies instantly to chrome, editor, and terminals.
          </p>
          <div className="row" role="group" aria-label="Color theme">
            {(["dark", "light"] as const).map((option) => (
              <button
                key={option}
                className="button secondary"
                aria-pressed={theme === option}
                disabled={theme === option}
                onClick={() => setFn({ theme: option })}
              >
                {option === "dark" ? "Dark" : "Light"}
              </button>
            ))}
          </div>
        </section>
        <section>
          <h3 className="section-title">Panel layout</h3>
          <p className="muted small">Sidebar and utility panel sizes persist across reloads.</p>
          <button className="button secondary" onClick={resetLayout}>
            Reset layout
          </button>
        </section>
        <section>
          <h3 className="section-title">Connection</h3>
          <p className="muted small">
            Stream: <StatusLabel state={connectionState} /> Gateway:{" "}
            <StatusLabel state={gatewayMode === "live" ? "verified" : gatewayMode} /> Last
            sequence: <span className="mono">{lastEventSequence ?? "—"}</span>
          </p>
        </section>
        {notice && (
          <p className="muted small" role="status">
            {notice}
          </p>
        )}
      </div>
    </aside>
  );
}
