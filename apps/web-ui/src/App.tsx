import { useEffect, type JSX } from "react";

import EditorArea from "./components/editor/EditorArea";
import BottomPanel from "./components/panels/BottomPanel";
import ExplorerView from "./components/panels/ExplorerView";
import GitView from "./components/panels/GitView";
import OfficeView from "./components/office/OfficeView";
import RunView from "./components/panels/RunView";
import SearchView from "./components/panels/SearchView";
import ActivityBar from "./components/shell/ActivityBar";
import PanelResize from "./components/shell/PanelResize";
import ViewBoundary from "./components/shell/ViewBoundary";
import CommandPalette from "./components/shell/CommandPalette";
import DiagnosticsDialog from "./components/shell/DiagnosticsDialog";
import OpenProjectDialog from "./components/shell/OpenProjectDialog";
import QuickOpen from "./components/shell/QuickOpen";
import StatusBar from "./components/shell/StatusBar";
import { useOffice } from "./state/officeStore";
import { useStore, type ViewId } from "./state/store";

const SIDEBARS: Record<ViewId, () => JSX.Element> = {
  explorer: ExplorerView,
  search: SearchView,
  git: GitView,
  run: RunView,
  office: OfficeView,
};

export default function App() {
  const view = useStore((s) => s.view);
  const sidebarOpen = useStore((s) => s.sidebarOpen);
  const sidebarWidth = useStore((s) => s.sidebarWidth);
  const notice = useStore((s) => s.notice);
  const project = useStore((s) => s.project);
  const quickOpen = useStore((s) => s.quickOpen);
  const commandPalette = useStore((s) => s.commandPalette);
  const projectDialog = useStore((s) => s.projectDialog);
  const diagnosticsOpen = useStore((s) => s.diagnosticsOpen);
  const saveActive = useStore((s) => s.saveActive);
  const setFn = useStore((s) => s.set);
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
    <div className={`ide ${sidebarOpen ? "sidebar-expanded" : "sidebar-collapsed"}`}
      style={{ gridTemplateColumns: `48px ${sidebarOpen ? `min(${sidebarWidth}px, 45vw)` : "0px"} minmax(0, 1fr)` }}>
      <ActivityBar />
      <div className="sidebar-container" hidden={!sidebarOpen}>
        <ViewBoundary key={view} name="Sidebar"><Sidebar /></ViewBoundary>
        <PanelResize axis="sidebar" />
      </div>
      <main className="main-area">
        {notice && <div className="office-notice" role="alert">{notice}
          <button className="link" onClick={() => setFn({ notice: null })}>Dismiss</button>
        </div>}
        <ViewBoundary name="Editor"><EditorArea /></ViewBoundary>
        <ViewBoundary name="Utility panel"><BottomPanel /></ViewBoundary>
      </main>
      <StatusBar />
      {projectDialog || !project ? (
        <OpenProjectDialog
          onClose={projectDialog ? () => setFn({ projectDialog: false }) : undefined}
        />
      ) : null}
      {quickOpen && <QuickOpen />}
      {commandPalette && <CommandPalette />}
      {diagnosticsOpen && <DiagnosticsDialog onClose={() => setFn({ diagnosticsOpen: false })} />}
    </div>
  );
}
