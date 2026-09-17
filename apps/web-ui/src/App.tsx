import { useEffect, type JSX } from "react";

import EditorArea from "./components/editor/EditorArea";
import BottomPanel from "./components/panels/BottomPanel";
import ExplorerView from "./components/panels/ExplorerView";
import GitView from "./components/panels/GitView";
import OfficeView from "./components/office/OfficeView";
import RunView from "./components/panels/RunView";
import SearchView from "./components/panels/SearchView";
import ActivityBar from "./components/shell/ActivityBar";
import CommandPalette from "./components/shell/CommandPalette";
import DiagnosticsDialog from "./components/shell/DiagnosticsDialog";
import OpenProjectDialog from "./components/shell/OpenProjectDialog";
import QuickOpen from "./components/shell/QuickOpen";
import StatusBar from "./components/shell/StatusBar";
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
  const project = useStore((s) => s.project);
  const quickOpen = useStore((s) => s.quickOpen);
  const commandPalette = useStore((s) => s.commandPalette);
  const projectDialog = useStore((s) => s.projectDialog);
  const diagnosticsOpen = useStore((s) => s.diagnosticsOpen);
  const saveActive = useStore((s) => s.saveActive);
  const setFn = useStore((s) => s.set);
  const Sidebar = SIDEBARS[view];

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        void saveActive();
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
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [saveActive, setFn]);

  return (
    <div className="ide">
      <ActivityBar />
      <Sidebar />
      <main className="main-area">
        <EditorArea />
        <BottomPanel />
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
