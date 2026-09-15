import Editor from "@monaco-editor/react";
import { useEffect, useRef } from "react";
import { monaco } from "../../state/monacoSetup";
import { isDirty, useStore, type FileTab } from "../../state/store";

export default function CodeEditor({ tab }: { tab: FileTab }) {
  const updateContent = useStore((s) => s.updateContent);
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
      theme="harness-dark"
      language={tab.language}
      value={tab.content}
      onChange={(value) => updateContent(tab.path, value ?? "")}
      onMount={(editor) => {
        editorRef.current = editor;
        editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => {
          void useStore.getState().saveActive();
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
