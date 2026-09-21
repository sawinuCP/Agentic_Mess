import { useEffect, useState, type CSSProperties, type JSX } from "react";

import EditorArea from "./components/editor/EditorArea";
import BottomPanel from "./components/panels/BottomPanel";
import ExplorerView from "./components/panels/ExplorerView";
import GitView from "./components/panels/GitView";
import ProblemsView from "./components/panels/ProblemsView";
import RuntimeView from "./components/panels/RuntimeView";
import SettingsView from "./components/panels/SettingsView";
import GraphView from "./components/graph/GraphView";
import HistoryView from "./components/history/HistoryView";
import CenterView from "./components/command/CenterView";
import RequirementsView from "./components/requirements/RequirementsView";
import OfficeView from "./components/office/OfficeView";
import RunView from "./components/panels/RunView";
import SearchView from "./components/panels/SearchView";
import ActivityBar from "./components/shell/ActivityBar";
import { ConfirmHost } from "./components/shell/ConfirmHost";
import ContextPanel from "./components/shell/ContextPanel";
import { NoticeBanner } from "./components/shell/UiState";
import TopBar from "./components/shell/TopBar";
import PanelResize from "./components/shell/PanelResize";
import ViewBoundary from "./components/shell/ViewBoundary";
import CommandPalette from "./components/shell/CommandPalette";
import DiagnosticsDialog from "./components/shell/DiagnosticsDialog";
import McpDialog from "./components/shell/McpDialog";
import OpenProjectDialog from "./components/shell/OpenProjectDialog";
import QuickOpen from "./components/shell/QuickOpen";
import StatusBar from "./components/shell/StatusBar";
import SymbolSearch from "./components/shell/SymbolSearch";
import { useOffice } from "./state/officeStore";
import { useStore, type ViewId } from "./state/store";

const SIDEBARS: Record<ViewId, () => JSX.Element> = {
  explorer: ExplorerView,
  search: SearchView,
  git: GitView,
  run: RunView,
  office: OfficeView,
  problems: ProblemsView,
  runtime: RuntimeView,
  settings: SettingsView,
  // The graph lives in the main area; the sidebar keeps the last panel.
  graph: OfficeView,
  // History is a main-area surface over durable events, not a sidebar panel.
  history: ExplorerView,
  // Command Center is a main-area surface; the sidebar keeps office context.
  command: OfficeView,
  // Requirements is a main-area verification surface; sidebar keeps office.
  requirements: OfficeView,
};

export default function App() {
  const view = useStore((s) => s.view);
  const sidebarOpen = useStore((s) => s.sidebarOpen);
  const sidebarWidth = useStore((s) => s.sidebarWidth);
  const notice = useStore((s) => s.notice);
  const project = useStore((s) => s.project);
  const quickOpen = useStore((s) => s.quickOpen);
  const commandPalette = useStore((s) => s.commandPalette);
  const symbolSearch = useStore((s) => s.symbolSearch);
  const mcpDialog = useStore((s) => s.mcpDialog);
  const projectDialog = useStore((s) => s.projectDialog);
  const diagnosticsOpen = useStore((s) => s.diagnosticsOpen);
  const selectedAgentId = useOffice((s) => s.selectedAgentId);
  const selectedTaskId = useOffice((s) => s.selectedTaskId);
  const selectedRequirementId = useOffice((s) => s.selectedRequirementId);
  const saveActive = useStore((s) => s.saveActive);
  const setFn = useStore((s) => s.set);
  // UI1 shell chrome stays local: navigation drawer (narrow) and the
  // contextual panel are presentation state, not domain state.
  const [navOpen, setNavOpen] = useState(false);
  const [contextOpen, setContextOpen] = useState(false);
  const [contextWidth, setContextWidth] = useState(320);
  const selectionKey = `${selectedAgentId ?? ""}|${selectedTaskId ?? ""}|${selectedRequirementId ?? ""}`;

  // A new selection reveals its context; closing is always manual.
  useEffect(() => {
    if (selectedAgentId || selectedTaskId || selectedRequirementId) setContextOpen(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectionKey]);
  const projectId = project?.id;
  const Sidebar = SIDEBARS[view];

  // Start realtime monitoring as soon as a project is open so shell telemetry
  // (connection status) is truthful app-wide, not only inside the office view.
  useEffect(() => {
    if (projectId) useOffice.getState().start(projectId);
    return () => useOffice.getState().stop();
  }, [projectId]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        void saveActive().catch((error: unknown) => setFn({ notice: error instanceof Error ? error.message : String(error) }));
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "p") {
        event.preventDefault();
        setFn({ quickOpen: true });
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setFn({ commandPalette: !useStore.getState().commandPalette });
      }
      // Alt+K focuses the Command Center. e.code is layout-independent
      // (macOS Option+K types ˚ but still reports KeyK); plain Ctrl+K stays
      // the palette, and Monaco keeps its own Ctrl+K chord behavior.
      if (event.altKey && !event.ctrlKey && !event.metaKey && event.code === "KeyK") {
        event.preventDefault();
        const state = useStore.getState();
        setFn({ view: "command", sidebarOpen: true, centerFocusTick: state.centerFocusTick + 1 });
      }
      // Escape closes shell drawers (never dialogs: those trap keys themselves).
      if (event.key === "Escape" && !document.querySelector('[aria-modal="true"]')) {
        if (useStore.getState().symbolSearch) setFn({ symbolSearch: false });
        else if (useStore.getState().quickOpen) setFn({ quickOpen: false });
        else {
          setNavOpen(false);
          setContextOpen(false);
        }
      }
    };
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (useStore.getState().tabs.some((t) => t.kind === "file" && t.content !== t.savedContent)) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", beforeUnload);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("beforeunload", beforeUnload);
    };
  }, [saveActive, setFn]);

  return (
    <div
      className={`ide ${sidebarOpen ? "sidebar-expanded" : "sidebar-collapsed"}${navOpen ? " nav-open" : ""}${contextOpen ? " context-open" : ""}`}
      style={{ "--sidebarw": `${sidebarWidth}px`, "--ctxw": `${contextWidth}px` } as CSSProperties}
    >
      <TopBar onMenu={() => setNavOpen(true)} />
      <ActivityBar onNavigate={() => setNavOpen(false)} />
      {navOpen && <button className="nav-scrim" aria-label="Close navigation" onClick={() => setNavOpen(false)} />}
      <div className="sidebar-container" hidden={!sidebarOpen}>
        <ViewBoundary key={view} name="Sidebar"><Sidebar /></ViewBoundary>
        <PanelResize axis="sidebar" />
      </div>
      <main className="main-area">
        {notice && <NoticeBanner text={notice} tone="alert" onDismiss={() => setFn({ notice: null })} />}
        <div key={view} className="main-view view-enter">
          {view === "graph" ? (
            <ViewBoundary name="Execution graph"><GraphView /></ViewBoundary>
          ) : view === "history" ? (
            <ViewBoundary name="Execution history"><HistoryView /></ViewBoundary>
          ) : view === "command" ? (
            <ViewBoundary name="Command Center"><CenterView /></ViewBoundary>
          ) : view === "requirements" ? (
            <ViewBoundary name="Requirements"><RequirementsView /></ViewBoundary>
          ) : (
            <ViewBoundary name="Editor"><EditorArea /></ViewBoundary>
          )}
        </div>
        <ViewBoundary name="Utility panel"><BottomPanel /></ViewBoundary>
      </main>
      {contextOpen && (
        <ContextPanel
          width={contextWidth}
          onWidth={(width) => setContextWidth(width)}
          onClose={() => setContextOpen(false)}
        />
      )}
      <StatusBar />
      {projectDialog || !project ? (
        <OpenProjectDialog
          onClose={projectDialog ? () => setFn({ projectDialog: false }) : undefined}
        />
      ) : null}
      {quickOpen && <QuickOpen />}
      {commandPalette && <CommandPalette />}
      {symbolSearch && <SymbolSearch />}
      {mcpDialog && <McpDialog onClose={() => setFn({ mcpDialog: false })} />}
      {diagnosticsOpen && <DiagnosticsDialog onClose={() => setFn({ diagnosticsOpen: false })} />}
      <ConfirmHost />
    </div>
  );
}
