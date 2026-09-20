import { DiffEditor } from "@monaco-editor/react";
import { isDirty, useStore, type FileTab } from "../../state/store";
import CodeEditor from "./CodeEditor";

const STARTERS = [
  "Implement OAuth login with tests",
  "Fix the failing migration",
  "Explain the payment module",
  "Where is retry logic used?",
];

function FirstUse() {
  const setWorkspace = useStore((s) => s.set);
  const startWith = (request: string): void => {
    setWorkspace({ centerPrefill: request, view: "command", sidebarOpen: true });
  };
  return (
    <div className="editor-empty">
      <div className="stack first-use">
        <div className="text-heading">Build something with your AI engineering team</div>
        <p className="muted small">
          Describe what to build, fix, refactor, test, or investigate. The Command
          Center turns it into a reviewed plan before agents run anything.
        </p>
        <div className="row wrap gap4" aria-label="Example requests">
          {STARTERS.map((example) => (
            <button key={example} className="btn btn-small" onClick={() => startWith(example)}>
              {example}
            </button>
          ))}
        </div>
        <div className="row wrap gap4">
          <button className="btn btn-small btn-primary" onClick={() => setWorkspace({ view: "command", sidebarOpen: true })}>
            Start with a request
          </button>
          <button className="btn btn-small" onClick={() => setWorkspace({ view: "office", sidebarOpen: true })}>
            Open Agents
          </button>
        </div>
      </div>
    </div>
  );
}

export default function EditorArea() {
  const tabs = useStore((s) => s.tabs);
  const activePath = useStore((s) => s.activePath);
  const setActive = useStore((s) => s.setActive);
  const closeTab = useStore((s) => s.closeTab);
  const theme = useStore((s) => s.theme);
  const monacoTheme = theme === "light" ? "harness-light" : "harness-dark";

  const active =
    activePath === null
      ? null
      : (tabs.find((t) => (t.kind === "file" ? t.path : `diff:${t.path}`) === activePath) ?? null);

  return (
    <section className="editor-area">
      <div className="tab-strip">
        {tabs.map((tab) => {
          const key = tab.kind === "file" ? tab.path : `diff:${tab.path}`;
          const title = tab.kind === "file" ? (isDirty(tab) ? `● ${tab.path}` : tab.path) : `diff: ${tab.path}`;
          return (
            <div
              key={key}
              className={`tab ${key === activePath ? "active" : ""}`}
              title={title}
              onClick={() => setActive(key)}
            >
              <button className="link tab-label" aria-pressed={key === activePath} onClick={() => setActive(key)}>
                {tab.kind === "file" ? (isDirty(tab) ? "● " : "") : "⇄ "}
                {tab.path.split("/").pop()}
              </button>
              <button className="tab-close" aria-label={`Close ${tab.path}`} title="Close" onClick={(e) => (e.stopPropagation(), closeTab(key))}>
                ×
              </button>
            </div>
          );
        })}
      </div>
      {active === null && (tabs.length === 0 ? <FirstUse /> : (
        <div className="editor-empty">Open a file from the explorer, or press Ctrl+P.</div>
      ))}
      {active?.kind === "file" && <CodeEditor tab={active as FileTab} />}
      {active?.kind === "diff" && (
        <DiffEditor
          theme={monacoTheme}
          original={active.original}
          modified={active.modified}
          language="plaintext"
          options={{ readOnly: true, automaticLayout: true, fontSize: 12 }}
        />
      )}
    </section>
  );
}
