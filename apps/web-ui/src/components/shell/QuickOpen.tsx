import { useEffect, useRef, useState } from "react";
import * as api from "../../api/client";
import { useStore } from "../../state/store";
import { useDialogFocus } from "./useDialogFocus";

export default function QuickOpen() {
  const project = useStore((s) => s.project);
  const openFile = useStore((s) => s.openFile);
  const setFn = useStore((s) => s.set);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<string[]>([]);
  const [selected, setSelected] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const dialogRef = useDialogFocus(() => setFn({ quickOpen: false }));
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!project) return;
    let active = true;
    setLoading(true);
    setError(null);
    const timer = window.setTimeout(() => {
      api
        .listFilePaths(project.id, query)
        .then((paths) => {
          if (!active) return;
          setResults(paths);
          setSelected(0);
        })
        .catch((err) => { if (active) { setResults([]); setError(String(err)); } })
        .finally(() => { if (active) setLoading(false); });
    }, 120);
    return () => { active = false; window.clearTimeout(timer); };
  }, [query, project]);

  const choose = (path: string | undefined) => {
    if (!path) return;
    void openFile(path).then(() => setFn({ quickOpen: false })).catch((err) => setError(String(err)));
  };

  return (
    <div className="overlay" onClick={() => setFn({ quickOpen: false })}>
      <div className="dialog quick-open" ref={dialogRef} role="dialog" aria-modal="true" aria-label="Go to file" tabIndex={-1} onClick={(e) => e.stopPropagation()}>
        {error && <p role="alert" className="error-text">{error}</p>}
        {!project && <p>Open a project to search files.</p>}
        {loading && <p role="status">Searching files…</p>}
        {project && !loading && !error && !results.length && <p>No matching files.</p>}
        <input
          ref={inputRef}
          className="text-input"
          placeholder="Go to file…"
          aria-label="Search files"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Escape") setFn({ quickOpen: false });
            if (e.key === "ArrowDown") setSelected((s) => Math.min(s + 1, results.length - 1));
            if (e.key === "ArrowUp") setSelected((s) => Math.max(s - 1, 0));
            if (e.key === "Enter") choose(results[selected]);
          }}
        />
        <ul className="quick-results">
          {results.map((path, index) => (
            <li
              key={path}
              className={index === selected ? "selected" : ""}
              onClick={() => choose(path)}
              onMouseEnter={() => setSelected(index)}
            >
              {path}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
