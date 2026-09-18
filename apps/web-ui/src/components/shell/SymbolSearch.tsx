// Symbol search dialog: workspace-symbol lookup over the durable
// code-intel index (GET /api/projects/{id}/symbols). Results jump to the
// recorded file/line via the existing editor. An unindexed project honestly
// reports no symbols rather than fabricating any.

import { useEffect, useRef, useState } from "react";
import * as api from "../../api/client";
import type { SymbolInfo } from "../../types";
import { errorMessage } from "../../api/errors";
import { useStore } from "../../state/store";
import { useDialogFocus } from "./useDialogFocus";

export default function SymbolSearch() {
  const project = useStore((s) => s.project);
  const openFile = useStore((s) => s.openFile);
  const setFn = useStore((s) => s.set);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SymbolInfo[]>([]);
  const [selected, setSelected] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const dialogRef = useDialogFocus(() => setFn({ symbolSearch: false }));

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
        .searchSymbols(project.id, query)
        .then((symbols) => {
          if (!active) return;
          setResults(symbols);
          setSelected(0);
        })
        .catch((err: unknown) => {
          if (active) {
            setResults([]);
            setError(errorMessage(err));
          }
        })
        .finally(() => {
          if (active) setLoading(false);
        });
    }, 150);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [query, project]);

  const choose = (symbol: SymbolInfo | undefined) => {
    if (!symbol) return;
    void openFile(symbol.path, symbol.start_line)
      .then(() => setFn({ symbolSearch: false }))
      .catch((err: unknown) => setError(errorMessage(err)));
  };

  return (
    <div className="overlay" onClick={() => setFn({ symbolSearch: false })}>
      <div
        className="dialog quick-open"
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label="Search symbols"
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
      >
        {error && <p role="alert" className="error-text">{error}</p>}
        {!project && <p>Open a project to search symbols.</p>}
        {loading && <p role="status">Searching symbols…</p>}
        {project && !loading && !error && results.length === 0 && (
          <p>No matching symbols. The index may not have run for this project yet.</p>
        )}
        <input
          ref={inputRef}
          className="text-input"
          placeholder="Search symbols…"
          aria-label="Search symbols"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Escape") setFn({ symbolSearch: false });
            if (e.key === "ArrowDown") setSelected((s) => Math.min(s + 1, results.length - 1));
            if (e.key === "ArrowUp") setSelected((s) => Math.max(s - 1, 0));
            if (e.key === "Enter") choose(results[selected]);
          }}
        />
        <ul className="quick-results">
          {results.map((symbol, index) => (
            <li
              key={symbol.id}
              className={index === selected ? "selected" : ""}
              title={symbol.signature ?? `${symbol.path}:${symbol.start_line}`}
              onClick={() => choose(symbol)}
              onMouseEnter={() => setSelected(index)}
            >
              <span className="mono">
                {symbol.name}
              </span>{" "}
              <span className="muted small">
                {symbol.kind}{symbol.parent ? ` in ${symbol.parent}` : ""} · {symbol.path}:{symbol.start_line}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
