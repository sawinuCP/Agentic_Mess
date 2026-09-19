import Editor from "@monaco-editor/react";
import { useEffect, useRef } from "react";
import { monaco } from "../../state/monacoSetup";
import { isDirty, useStore, type FileTab } from "../../state/store";

export default function CodeEditor({ tab }: { tab: FileTab }) {
  const updateContent = useStore((s) => s.updateContent);
  const theme = useStore((s) => s.theme);
  const editorRef = useRef<monaco.editor.IStandaloneCodeEditor | null>(null);

  useEffect(() => {
    if (tab.pendingLine !== undefined) {
      editorRef.current?.revealLineInCenter(tab.pendingLine);
      editorRef.current?.setPosition({ lineNumber: tab.pendingLine, column: 1 });
    }
  }, [tab.pendingLine]);

  if (tab.isBinary) {
    return <div className="editor-empty">Binary file — editing is not supported.</div>;
  }

  return (
    <Editor
      theme={theme === "light" ? "harness-light" : "harness-dark"}
      language={tab.language}
      value={tab.content}
      onChange={(value) => updateContent(tab.path, value ?? "")}
      onMount={(editor) => {
        editorRef.current = editor;
        editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => {
          void useStore.getState().saveActive();
        });
        // Track text selection for the Command Center ("this" resolution).
        // Capped at 2000 chars; cleared on cursor-only moves and unmount.
        // The path resolves live from the store: this mount outlives tab switches.
        editor.onDidChangeCursorSelection((e) => {
          const model = editor.getModel();
          const text = e.selection.isEmpty() ? "" : (model?.getValueInRange(e.selection) ?? "").slice(0, 2000);
          const activePath = useStore.getState().activePath;
          useStore.getState().set({
            selection: text && activePath
              ? {
                  path: activePath,
                  startLine: e.selection.startLineNumber,
                  startColumn: e.selection.startColumn,
                  endLine: e.selection.endLineNumber,
                  endColumn: e.selection.endColumn,
                  text,
                }
              : null,
          });
        });
      }}
      options={{
        fontSize: 13,
        minimap: { enabled: false },
        scrollBeyondLastLine: false,
        renderWhitespace: "selection",
        automaticLayout: true,
      }}
      // aria label with dirty state for accessibility
      loading={<div className="editor-empty">Loading…</div>}
    />
  );
}

export function tabTitle(tab: FileTab): string {
  return isDirty(tab) ? `● ${tab.path.split("/").pop()}` : (tab.path.split("/").pop() ?? "");
}
