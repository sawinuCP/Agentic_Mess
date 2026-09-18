import type { JSX } from "react";
import { useStore, type ViewId } from "../../state/store";

const ICONS: Record<string, JSX.Element> = {
  explorer: (
    <svg viewBox="0 0 16 16" width="22" height="22" fill="currentColor">
      <path d="M1.5 2.5A1.5 1.5 0 0 1 3 1h3.2l1.5 2H13a1.5 1.5 0 0 1 1.5 1.5V6H10l-2 3H1.5V2.5z" opacity=".85" />
      <path d="M1.5 15V10.5H8l2-3h6.5V13A1.5 1.5 0 0 1 15 14.5H1.5z" />
    </svg>
  ),
  search: (
    <svg viewBox="0 0 16 16" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.6">
      <circle cx="6.5" cy="6.5" r="4.5" />
      <path d="m10 10 4 4" strokeLinecap="round" />
    </svg>
  ),
  git: (
    <svg viewBox="0 0 16 16" width="22" height="22" fill="currentColor">
      <circle cx="4" cy="4" r="2" /><circle cx="4" cy="12" r="2" /><circle cx="12" cy="8" r="2" />
      <path d="M4 6v4M6 4h3a3 3 0 0 1 3 3v1h-2V7a1 1 0 0 0-1-1H6z" opacity=".8" />
    </svg>
  ),
  run: (
    <svg viewBox="0 0 16 16" width="22" height="22" fill="currentColor">
      <path d="M4 2.8v10.4L13 8 4 2.8z" />
    </svg>
  ),
  office: (
    <svg viewBox="0 0 16 16" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="5.5" cy="5" r="2.2" />
      <path d="M1.8 13.5c.4-2.6 1.9-4 3.7-4s3.3 1.4 3.7 4" strokeLinecap="round" />
      <circle cx="11.5" cy="4.2" r="1.8" />
      <path d="M9.6 8.6c.6-.7 1.2-1 1.9-1 1.5 0 2.7 1.2 3 3.4" strokeLinecap="round" />
    </svg>
  ),
  graph: (
    <svg viewBox="0 0 16 16" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="3" cy="8" r="1.8" />
      <circle cx="9" cy="3.5" r="1.8" />
      <circle cx="9" cy="12.5" r="1.8" />
      <circle cx="14" cy="8" r="1.5" />
      <path d="M4.6 7.2 7.4 4.4M4.6 8.8l2.8 2.8M10.6 4.3l1.9 2.4M10.6 11.7l1.9-2.4" strokeLinecap="round" />
    </svg>
  ),
  history: (
    <svg viewBox="0 0 16 16" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="8" cy="8" r="6" />
      <path d="M8 4.5V8l2.5 1.5" strokeLinecap="round" />
    </svg>
  ),
  command: (
    <svg viewBox="0 0 16 16" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.6">
      <path d="m3 5 3.5 3.5L3 12M7.5 12.5H13" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
  terminal: (
    <svg viewBox="0 0 16 16" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.6">
      <rect x="1.5" y="2.5" width="13" height="11" rx="1.5" />
      <path d="m4 6 2.5 2L4 10M8 10.5h4" strokeLinecap="round" />
    </svg>
  ),
};

const MAIN_VIEWS: { id: ViewId; title: string }[] = [
  { id: "explorer", title: "Explorer" },
  { id: "search", title: "Search" },
  { id: "git", title: "Source Control" },
  { id: "run", title: "Run & Toolchains" },
  { id: "office", title: "Engineering Office" },
  { id: "graph", title: "Execution Graph" },
  { id: "history", title: "Execution History" },
  { id: "command", title: "Command Center" },
];

export default function ActivityBar() {
  const view = useStore((s) => s.view);
  const panelOpen = useStore((s) => s.panelOpen);
  const setFn = useStore((s) => s.set);

  return (
    <nav className="activity-bar">
      {MAIN_VIEWS.map(({ id, title }) => (
        <button
          key={id}
          title={title}
          className={`activity-btn ${view === id ? "active" : ""}`}
          aria-label={title}
          onClick={() => setFn({ view: id, sidebarOpen: true })}
        >
          {ICONS[id]}
        </button>
      ))}
      <button className="activity-btn" title="Toggle sidebar" aria-label="Toggle sidebar"
        onClick={() => setFn({ sidebarOpen: !useStore.getState().sidebarOpen })}>☰</button>
      <button className="activity-btn" title="Command palette" aria-label="Command palette"
        onClick={() => setFn({ commandPalette: true })}>⌘</button>
      <div className="activity-spacer" />
      <button
        title="Toggle panel"
        className={`activity-btn ${panelOpen ? "active" : ""}`}
        onClick={() => setFn({ panelOpen: !panelOpen })}
      >
        {ICONS.terminal}
      </button>
    </nav>
  );
}
