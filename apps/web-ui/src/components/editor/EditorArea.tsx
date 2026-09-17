import { DiffEditor } from "@monaco-editor/react";
import { isDirty, useStore, type FileTab } from "../../state/store";
import CodeEditor from "./CodeEditor";

export default function EditorArea() {
  const tabs = useStore((s) => s.tabs);
  const activePath = useStore((s) => s.activePath);
  const setActive = useStore((s) => s.setActive);
  const closeTab = useStore((s) => s.closeTab);

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
      {active === null && <div className="editor-empty">Open a file from the explorer, or press Ctrl+P.</div>}
      {active?.kind === "file" && <CodeEditor tab={active as FileTab} />}
      {active?.kind === "diff" && (
        <DiffEditor
          theme="harness-dark"
          original={active.original}
          modified={active.modified}
          language="plaintext"
          options={{ readOnly: true, automaticLayout: true, fontSize: 12 }}
        />
      )}
    </section>
  );
}
