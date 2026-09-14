import { useEffect, type JSX } from "react";

import ActivityBar from "./components/ActivityBar";
import BottomPanel from "./components/BottomPanel";
import EditorArea from "./components/EditorArea";
import ExplorerView from "./components/ExplorerView";
import GitView from "./components/GitView";
import OpenProjectDialog from "./components/OpenProjectDialog";
import QuickOpen from "./components/QuickOpen";
import RunView from "./components/RunView";
import SearchView from "./components/SearchView";
import StatusBar from "./components/StatusBar";
import { useStore, type ViewId } from "./state/store";

const SIDEBARS: Record<ViewId, () => JSX.Element> = {
  explorer: ExplorerView,
  search: SearchView,
  git: GitView,
  run: RunView,
};

export default function App() {
  const view = useStore((s) => s.view);
  const project = useStore((s) => s.project);
  const quickOpen = useStore((s) => s.quickOpen);
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
      {!project && <OpenProjectDialog />}
      {quickOpen && <QuickOpen />}
    </div>
  );
}
