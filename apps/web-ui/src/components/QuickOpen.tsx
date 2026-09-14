import { useEffect, useRef, useState } from "react";
import * as api from "../api/client";
import { useStore } from "../state/store";

export default function QuickOpen() {
  const project = useStore((s) => s.project);
  const openFile = useStore((s) => s.openFile);
  const setFn = useStore((s) => s.set);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<string[]>([]);
  const [selected, setSelected] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!project) return;
    const timer = window.setTimeout(() => {
      api
        .listFilePaths(project.id, query)
        .then((paths) => {
          setResults(paths);
          setSelected(0);
        })
        .catch(() => setResults([]));
    }, 120);
    return () => window.clearTimeout(timer);
  }, [query, project]);

  const choose = (path: string | undefined) => {
    if (!path) return;
    setFn({ quickOpen: false });
    void openFile(path);
  };

  return (
    <div className="overlay" onClick={() => setFn({ quickOpen: false })}>
      <div className="dialog quick-open" onClick={(e) => e.stopPropagation()}>
        <input
          ref={inputRef}
          className="text-input"
          placeholder="Go to file…"
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
