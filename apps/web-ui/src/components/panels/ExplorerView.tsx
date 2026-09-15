import { useState } from "react";
import * as api from "../../api/client";
import type { TreeNode } from "../../types";
import { useStore } from "../../state/store";

function InputDialog(props: { title: string; onSubmit: (value: string) => void; onClose: () => void }) {
  const [value, setValue] = useState("");
  return (
    <div className="overlay" onClick={props.onClose}>
      <div className="dialog" onClick={(e) => e.stopPropagation()}>
        <h2>{props.title}</h2>
        <input
          autoFocus
          className="text-input"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && value.trim()) props.onSubmit(value.trim());
            if (e.key === "Escape") props.onClose();
          }}
        />
        <div className="dialog-actions">
          <button className="button" onClick={() => (value.trim() ? props.onSubmit(value.trim()) : undefined)}>
            OK
          </button>
          <button className="button secondary" onClick={props.onClose}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

function TreeRow({ node, depth }: { node: TreeNode; depth: number }) {
  const { tree, expanded, toggleDir, openFile } = useStore((s) => s);
  const project = useStore((s) => s.project);
  const [dialog, setDialog] = useState<"rename" | "delete" | null>(null);

  const isDir = node.kind === "directory";
  const isOpen = expanded[node.path];

  const act = async (fn: () => Promise<unknown>) => {
    await fn;
    await useStore.getState().loadChildren(node.path.includes("/") ? node.path.split("/").slice(0, -1).join("/") : "");
  };

  return (
    <>
      <div className={`tree-row ${isDir ? "" : "file"}`} style={{ paddingLeft: depth * 12 + 8 }}>
        {isDir ? (
          <>
            <button className="tree-disclosure" onClick={() => void toggleDir(node.path)}>
              {isOpen ? "▾" : "▸"}
            </button>
            <span className="tree-name" onClick={() => void toggleDir(node.path)}>
              {node.name}
            </span>
          </>
        ) : (
          <span className="tree-name" onClick={() => void openFile(node.path)}>
            {node.name}
          </span>
        )}
        {project && (
          <span className="tree-actions">
            <button className="tree-action" title="Rename" onClick={() => setDialog("rename")}>
              ✏
            </button>
            <button className="tree-action" title="Delete" onClick={() => setDialog("delete")}>
              ✕
            </button>
          </span>
        )}
      </div>
      {dialog === "rename" && (
        <InputDialog
          title={`Rename ${node.name}`}
          onClose={() => setDialog(null)}
          onSubmit={(newName) => {
            const parent = node.path.includes("/") ? node.path.split("/").slice(0, -1).join("/") : "";
            const target = parent ? `${parent}/${newName}` : newName;
            void act(async () => {
              if (project) await api.renameEntry(project.id, node.path, target);
            });
            setDialog(null);
          }}
        />
      )}
      {dialog === "delete" && (
        <InputDialog
          title={`Delete ${node.name}?`}
          onClose={() => setDialog(null)}
          onSubmit={() => {
            void act(async () => {
              if (project) await api.deleteEntry(project.id, node.path);
            });
            setDialog(null);
          }}
        />
      )}
      {isDir && isOpen && (tree[node.path] ?? []).map((child) => <TreeRow key={child.path} node={child} depth={depth + 1} />)}
    </>
  );
}

export default function ExplorerView() {
  const project = useStore((s) => s.project);
  const tree = useStore((s) => s.tree);
  const { loadChildren, refreshTree } = useStore((s) => s);
  const [dialog, setDialog] = useState<{ kind: "file" | "directory" } | null>(null);

  if (!project) {
    return <aside className="sidebar"><p className="muted pad">Open a project to browse its files.</p></aside>;
  }
  const roots = tree[""] ?? [];

  return (
    <aside className="sidebar">
      <header className="sidebar-header">
        <span>EXPLORER</span>
        <span className="sidebar-actions">
          <button className="tree-action" title="New file" onClick={() => setDialog({ kind: "file" })}>＋</button>
          <button className="tree-action" title="New folder" onClick={() => setDialog({ kind: "directory" })}>⊕</button>
          <button className="tree-action" title="Refresh" onClick={() => void refreshTree()}>⟳</button>
        </span>
      </header>
      <div className="tree">
        {roots.length === 0 && <p className="muted pad">Loading…</p>}
        {roots.map((node) => (
          <TreeRow key={node.path} node={node} depth={0} />
        ))}
      </div>
      {dialog && (
        <InputDialog
          title={`New ${dialog.kind}`}
          onClose={() => setDialog(null)}
          onSubmit={(name) => {
            void loadChildren("")
              .then(() => api.createEntry(project.id, name, dialog.kind))
              .then(() => loadChildren(""));
            setDialog(null);
          }}
        />
      )}
    </aside>
  );
}
