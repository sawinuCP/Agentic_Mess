// Activity bar (UI1): grouped compact rail with text labels, attention badges
// and canonical terminology (see docs/ui-ux/terminology.md). PRIMARY doors
// answer BUILD / ORCHESTRATE / UNDERSTAND; Tasks and Requirements deep-link
// into office tabs until dedicated views land (later phases). No view logic
// changed — every button only sets view/tab/selection state.

import type { JSX } from "react";

import { collectProblems } from "../../office/selectors";
import { runningAgents, useOffice } from "../../state/officeStore";
import { useStore, type ViewId } from "../../state/store";

const ICONS: Record<string, JSX.Element> = {
  explorer: (
    <svg viewBox="0 0 16 16" width="20" height="20" fill="currentColor" aria-hidden="true">
      <path d="M1.5 2.5A1.5 1.5 0 0 1 3 1h3.2l1.5 2H13a1.5 1.5 0 0 1 1.5 1.5V6H10l-2 3H1.5V2.5z" opacity=".85" />
      <path d="M1.5 15V10.5H8l2-3h6.5V13A1.5 1.5 0 0 1 15 14.5H1.5z" />
    </svg>
  ),
  search: (
    <svg viewBox="0 0 16 16" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <circle cx="6.5" cy="6.5" r="4.5" />
      <path d="m10 10 4 4" strokeLinecap="round" />
    </svg>
  ),
  git: (
    <svg viewBox="0 0 16 16" width="20" height="20" fill="currentColor" aria-hidden="true">
      <circle cx="4" cy="4" r="2" /><circle cx="4" cy="12" r="2" /><circle cx="12" cy="8" r="2" />
      <path d="M4 6v4M6 4h3a3 3 0 0 1 3 3v1h-2V7a1 1 0 0 0-1-1H6z" opacity=".8" />
    </svg>
  ),
  run: (
    <svg viewBox="0 0 16 16" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
      <path d="M4 2.8v10.4L13 8 4 2.8z" fill="currentColor" stroke="none" />
      <path d="M2 2h12" strokeLinecap="round" />
    </svg>
  ),
  office: (
    <svg viewBox="0 0 16 16" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
      <circle cx="5.5" cy="5" r="2.2" />
      <path d="M1.8 13.5c.4-2.6 1.9-4 3.7-4s3.3 1.4 3.7 4" strokeLinecap="round" />
      <circle cx="11.5" cy="4.2" r="1.8" />
      <path d="M9.6 8.6c.6-.7 1.2-1 1.9-1 1.5 0 2.7 1.2 3 3.4" strokeLinecap="round" />
    </svg>
  ),
  tasks: (
    <svg viewBox="0 0 16 16" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
      <path d="M2 4.5 3.5 6 6 3" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M8 4h6M2 8.5 3.5 10 6 7.5M8 8.5h6M2 13l1.5 1.5L6 12M8 13h6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
  requirements: (
    <svg viewBox="0 0 16 16" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
      <path d="M4 1.5h6l3 3V14.5H4z" strokeLinejoin="round" />
      <path d="M10 1.5v3h3M6.5 8h4M6.5 10.5h4" strokeLinecap="round" />
    </svg>
  ),
  graph: (
    <svg viewBox="0 0 16 16" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
      <circle cx="3" cy="8" r="1.8" />
      <circle cx="9" cy="3.5" r="1.8" />
      <circle cx="9" cy="12.5" r="1.8" />
      <circle cx="14" cy="8" r="1.5" />
      <path d="M4.6 7.2 7.4 4.4M4.6 8.8l2.8 2.8M10.6 4.3l1.9 2.4M10.6 11.7l1.9-2.4" strokeLinecap="round" />
    </svg>
  ),
  history: (
    <svg viewBox="0 0 16 16" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
      <circle cx="8" cy="8" r="6" />
      <path d="M8 4.5V8l2.5 1.5" strokeLinecap="round" />
    </svg>
  ),
  problems: (
    <svg viewBox="0 0 16 16" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
      <path d="M8 2 14.5 13.5h-13L8 2z" strokeLinejoin="round" />
      <path d="M8 6.5v3" strokeLinecap="round" />
      <circle cx="8" cy="11.5" r="0.9" fill="currentColor" stroke="none" />
    </svg>
  ),
  settings: (
    <svg viewBox="0 0 16 16" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
      <circle cx="8" cy="8" r="2.2" />
      <path d="M8 1.8v2M8 12.2v2M1.8 8h2M12.2 8h2M3.6 3.6l1.4 1.4M11 11l1.4 1.4M12.4 3.6 11 5M5 11l-1.4 1.4" strokeLinecap="round" />
    </svg>
  ),
  runtime: (
    <svg viewBox="0 0 16 16" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
      <rect x="2" y="2" width="12" height="4.5" rx="1" />
      <rect x="2" y="9.5" width="12" height="4.5" rx="1" />
      <circle cx="4.5" cy="4.2" r="0.9" fill="currentColor" stroke="none" />
      <circle cx="4.5" cy="11.7" r="0.9" fill="currentColor" stroke="none" />
    </svg>
  ),
  command: (
    <svg viewBox="0 0 16 16" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <path d="m3 5 3.5 3.5L3 12M7.5 12.5H13" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
  terminal: (
    <svg viewBox="0 0 16 16" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <rect x="1.5" y="2.5" width="13" height="11" rx="1.5" />
      <path d="m4 6 2.5 2L4 10M8 10.5h4" strokeLinecap="round" />
    </svg>
  ),
};

interface NavDoor {
  key: string;
  label: string;
  view: ViewId;
  officeTab?: "team" | "timeline" | "comms" | "oversight";
  badge?: number;
  badgeLabel?: string;
  title: string;
}

// PRIMARY doors answer BUILD / ORCHESTRATE / UNDERSTAND. Tasks and
// Requirements deep-link into office tabs until dedicated views land.
const PRIMARY: NavDoor[] = [
  { key: "workspace", label: "Workspace", view: "explorer", title: "Workspace — files and editor (Build)" },
  { key: "agents", label: "Agents", view: "office", officeTab: "team", title: "Agents — supervise running agents (Orchestrate)" },
  { key: "tasks", label: "Tasks", view: "office", officeTab: "team", title: "Tasks — work queue (Orchestrate)" },
  { key: "requirements", label: "Requirements", view: "office", officeTab: "oversight", title: "Requirements — verification (Understand)" },
  { key: "changes", label: "Changes", view: "git", title: "Changes — source control and diffs (Build)" },
  { key: "execution", label: "Execution", view: "graph", title: "Execution — requirement to evidence graph (Understand)" },
  { key: "history", label: "History", view: "history", title: "History — durable record and replay (Understand)" },
  { key: "command", label: "Command", view: "command", title: "Command Center — dispatch work (Orchestrate)" },
];

const SECONDARY: NavDoor[] = [
  { key: "search", label: "Search", view: "search", title: "Search files" },
  { key: "problems", label: "Problems", view: "problems", title: "Problems — triage failures" },
  { key: "tools", label: "Tools", view: "run", title: "Tools — run, test, format" },
  { key: "runtime", label: "Runtime", view: "runtime", title: "Runtime — ports and leases" },
  { key: "settings", label: "Settings", view: "settings", title: "Settings" },
];

export default function ActivityBar({ onNavigate }: { onNavigate: () => void }) {
  const view = useStore((s) => s.view);
  const panelOpen = useStore((s) => s.panelOpen);
  const output = useStore((s) => s.output);
  const setFn = useStore((s) => s.set);
  const officeTab = useOffice((s) => s.tab);
  const agents = useOffice((s) => s.agents);
  const tasks = useOffice((s) => s.tasks);
  const hitl = useOffice((s) => s.hitl);
  const setOffice = useOffice((s) => s.set);

  const approvals = hitl.length;
  const problemCount = collectProblems({ tasks, output, hitl }).length;

  const go = (door: NavDoor): void => {
    if (door.officeTab) setOffice({ tab: door.officeTab, selectedAgentId: null });
    setFn({ view: door.view, sidebarOpen: true });
    onNavigate();
  };

  const isActive = (door: NavDoor): boolean => {
    if (view !== door.view) return false;
    if (door.view === "office" && door.officeTab) return officeTab === door.officeTab;
    if (door.view === "office") return true;
    return true;
  };

  const renderDoor = (door: NavDoor): JSX.Element => {
    const badge = door.key === "agents" && approvals > 0
      ? { n: approvals, label: `${approvals} approvals needed` }
      : door.key === "problems" && problemCount > 0
        ? { n: problemCount, label: `${problemCount} problems` }
        : door.key === "agents" && runningAgents(agents).length > 0
          ? { n: runningAgents(agents).length, label: "agents working" }
          : null;
    const active = isActive(door);
    return (
      <button
        key={door.key}
        title={door.title}
        aria-label={badge ? `${door.label}, ${badge.label}` : door.label}
        aria-current={active ? "page" : undefined}
        className={`activity-btn nav-door ${active ? "active" : ""}`}
        onClick={() => go(door)}
      >
        {ICONS[door.key] ?? ICONS[door.view]}
        <span className="nav-label" aria-hidden="true">{door.label}</span>
        {badge && (
          <span className="nav-badge" aria-hidden="true">{badge.n > 9 ? "9+" : badge.n}</span>
        )}
      </button>
    );
  };

  return (
    <nav className="activity-bar" aria-label="Primary">
      <div className="nav-group" role="group" aria-label="Build, orchestrate, understand">
        {PRIMARY.map(renderDoor)}
      </div>
      <div className="nav-separator" aria-hidden="true" />
      <div className="nav-group" role="group" aria-label="System">
        {SECONDARY.map(renderDoor)}
      </div>
      <button className="activity-btn nav-door" title="Toggle sidebar" aria-label="Toggle sidebar"
        onClick={() => setFn({ sidebarOpen: !useStore.getState().sidebarOpen })}>☰<span className="nav-label" aria-hidden="true">Sidebar</span></button>
      <button className="activity-btn nav-door" title="Command palette (Ctrl+K)" aria-label="Command palette"
        onClick={() => setFn({ commandPalette: true })}>⌘<span className="nav-label" aria-hidden="true">Palette</span></button>
      <div className="activity-spacer" />
      <button
        title="Toggle panel"
        aria-label="Toggle bottom panel"
        aria-pressed={panelOpen}
        className={`activity-btn nav-door ${panelOpen ? "active" : ""}`}
        onClick={() => setFn({ panelOpen: !panelOpen })}
      >
        {ICONS.terminal}<span className="nav-label" aria-hidden="true">Panel</span>
      </button>
    </nav>
  );
}
