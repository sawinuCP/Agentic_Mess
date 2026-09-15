import { useState } from "react";
import * as api from "../../api/client";
import type { SearchMatch } from "../../types";
import { useStore } from "../../state/store";

export default function SearchView() {
  const project = useStore((s) => s.project);
  const openFile = useStore((s) => s.openFile);
  const [query, setQuery] = useState("");
  const [regex, setRegex] = useState(false);
  const [caseSensitive, setCaseSensitive] = useState(false);
  const [results, setResults] = useState<SearchMatch[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    if (!project || !query.trim()) return;
    setBusy(true);
    setError(null);
    try {
      setResults(
        await api.searchFiles(project.id, { q: query, regex, case_sensitive: caseSensitive }),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setResults([]);
    } finally {
      setBusy(false);
    }
  };

  const grouped = new Map<string, SearchMatch[]>();
  for (const match of results ?? []) {
    const list = grouped.get(match.path) ?? [];
    list.push(match);
    grouped.set(match.path, list);
  }

  return (
    <aside className="sidebar">
      <header className="sidebar-header">SEARCH</header>
      <div className="pad stack">
        <input
          className="text-input"
          placeholder="Search… (Enter)"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && void run()}
        />
        <label className="check">
          <input type="checkbox" checked={regex} onChange={(e) => setRegex(e.target.checked)} /> Regex
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={caseSensitive}
            onChange={(e) => setCaseSensitive(e.target.checked)}
          />{" "}
          Match case
        </label>
        {error && <p className="error-text">{error}</p>}
        {results !== null && (
          <p className="muted">{busy ? "searching…" : `${results.length} match${results.length === 1 ? "" : "es"}`}</p>
        )}
      </div>
      <div className="tree">
        {[...grouped.entries()].map(([path, matches]) => (
          <div key={path}>
            <div className="tree-row file" title={path}>
              <span className="tree-name strong">{path}</span>
              <span className="muted"> ({matches.length})</span>
            </div>
            {matches.map((m) => (
              <div
                key={`${m.path}:${m.line}:${m.column}`}
                className="tree-row file match"
                style={{ paddingLeft: 24 }}
                onClick={() => void openFile(m.path, m.line)}
              >
                <span className="mono">
                  {m.line}: {m.text}
                </span>
              </div>
            ))}
          </div>
        ))}
      </div>
    </aside>
  );
}
