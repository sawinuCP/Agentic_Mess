// Global IDE state (zustand). Slices: project, explorer, editor, git, run, panel.

import { create } from "zustand";

import * as api from "../api/client";
import type { GitStatus, ProjectInfo, ProjectToolchains, ToolRunResult, TreeNode } from "../types";
import { monacoLanguageFor } from "../util/languages";
import { readLayout, saveLayout } from "./layout";

export type ViewId = "explorer" | "search" | "git" | "run" | "office";

export interface FileTab {
  kind: "file";
  path: string;
  content: string;
  savedContent: string;
  isBinary: boolean;
  language: string;
  pendingLine?: number;
}

export interface DiffTab {
  kind: "diff";
  path: string;
  original: string;
  modified: string;
}

export type Tab = FileTab | DiffTab;

interface AppState {
  project: ProjectInfo | null;
  toolchains: ProjectToolchains | null;
  git: GitStatus | null;
  tree: Record<string, TreeNode[]>;
  expanded: Record<string, boolean>;
  tabs: Tab[];
  activePath: string | null;
  view: ViewId;
  sidebarOpen: boolean;
  sidebarWidth: number;
  panelHeight: number;
  notice: string | null;
  panelOpen: boolean;
  panelTab: "terminal" | "output";
  terminalIds: string[];
  activeTerminal: string | null;
  quickOpen: boolean;
  commandPalette: boolean;
  symbolSearch: boolean;
  projectDialog: boolean;
  diagnosticsOpen: boolean;
  output: ToolRunResult | null;

  openProject: (rootPath: string) => Promise<void>;
  refreshToolchains: () => Promise<void>;
  refreshGit: () => Promise<void>;
  loadChildren: (dirPath: string) => Promise<void>;
  toggleDir: (dirPath: string) => Promise<void>;
  refreshTree: () => Promise<void>;
  openFile: (path: string, line?: number) => Promise<void>;
  openDiff: (path: string, original: string, modified: string) => void;
  closeTab: (path: string) => void;
  setActive: (path: string) => void;
  updateContent: (path: string, content: string) => void;
  saveActive: () => Promise<void>;
  runTool: (tool: string, path?: string) => Promise<void>;
  createTerminal: () => Promise<void>;
  closeTerminal: (id: string) => void;
  set: (partial: Partial<AppState>) => void;
}

// Only the latest requested project may replace the workspace.
let projectOpenGeneration = 0;
export const useStore = create<AppState>((set, get) => ({
  project: null,
  toolchains: null,
  git: null,
  tree: {},
  expanded: { "": true },
  tabs: [],
  activePath: null,
  view: "explorer",
  ...readLayout(),
  notice: null,
  panelTab: "terminal",
  terminalIds: [],
  activeTerminal: null,
  quickOpen: false,
  commandPalette: false,
  symbolSearch: false,
  projectDialog: false,
  diagnosticsOpen: false,
  output: null,

  set: (partial) => set(partial),

  openProject: async (rootPath) => {
    if (get().tabs.some((t) => t.kind === "file" && isDirty(t))) {
      throw new Error("Save or close modified files before switching projects. Your edits were preserved.");
    }
    const generation = ++projectOpenGeneration;
    const project = await api.openProject(rootPath);
    if (generation !== projectOpenGeneration) return;
    // A request may complete after the user edits a buffer: check again.
    if (get().tabs.some((t) => t.kind === "file" && isDirty(t))) {
      throw new Error("A file changed while opening the project. Save it before switching.");
    }
    set({ project, tree: {}, expanded: { "": true }, tabs: [], activePath: null,
      terminalIds: [], activeTerminal: null, toolchains: null, git: null, output: null, notice: null });
    const results = await Promise.allSettled([
      get().refreshTree(), get().refreshToolchains(), get().refreshGit(), get().createTerminal(),
    ]);
    if (generation !== projectOpenGeneration) return;
    const failures = results.filter((r) => r.status === "rejected");
    if (failures.length) set({ notice: "Project opened with partial data. " + failures.map(
      (r) => r.status === "rejected" ? String(r.reason) : "").join("; ") });
  },

  refreshGit: async () => {
    const project = get().project;
    if (!project) return;
    try {
      const git = await api.gitStatus(project.id);
      if (get().project?.id === project.id) set({ git });
    } catch (err) {
      // Not a repository (409) is a normal state; keep the panel usable.
      if (err instanceof api.ApiError && err.status === 409) {
        set({ git: null });
      } else {
        throw err;
      }
    }
  },

  refreshToolchains: async () => {
    const project = get().project;
    if (!project) return;
    const toolchains = await api.getProjectToolchains(project.id);
    if (get().project?.id === project.id) set({ toolchains });
  },

  refreshTree: async () => {
    await get().loadChildren("");
    for (const dir of Object.keys(get().expanded)) {
      if (dir && get().expanded[dir]) {
        await get().loadChildren(dir);
      }
    }
  },

  loadChildren: async (dirPath) => {
    const project = get().project;
    if (!project) return;
    const children = await api.getTree(project.id, dirPath);
    if (get().project?.id === project.id) set((state) => ({ tree: { ...state.tree, [dirPath]: children } }));
  },

  toggleDir: async (dirPath) => {
    const expanded = get().expanded;
    const next = { ...expanded, [dirPath]: !expanded[dirPath] };
    set({ expanded: next });
    if (next[dirPath] && !get().tree[dirPath]) {
      await get().loadChildren(dirPath);
    }
  },

  openFile: async (path, line) => {
    const project = get().project;
    if (!project) return;
    const existing = get().tabs.find((t) => t.kind === "file" && t.path === path);
    if (existing && existing.kind === "file") {
      set({
        activePath: path,
        view: "explorer",
        tabs: get().tabs.map((t) =>
          t.kind === "file" && t.path === path ? { ...t, pendingLine: line } : t,
        ),
      });
      return;
    }
    const content = await api.readFile(project.id, path);
    if (get().project?.id !== project.id) return;
    if (get().tabs.some((t) => t.kind === "file" && t.path === path)) { set({ activePath: path }); return; }
    const tab: FileTab = {
      kind: "file",
      path,
      content: content.is_binary ? "" : content.content,
      savedContent: content.is_binary ? "" : content.content,
      isBinary: content.is_binary,
      language: monacoLanguageFor(path),
      pendingLine: line,
    };
    set({ tabs: [...get().tabs, tab], activePath: path, view: "explorer" });
  },

  openDiff: (path, original, modified) => {
    const tab: DiffTab = { kind: "diff", path, original, modified };
    set({ tabs: [...get().tabs, tab], activePath: `diff:${path}`, view: "explorer" });
  },

  closeTab: (path) => {
    const closing = get().tabs.find((t) => t.kind === "file" && t.path === path);
    if (closing?.kind === "file" && isDirty(closing) &&
        !window.confirm(`Discard unsaved changes to ${path}?`)) return;
    const tabs = get().tabs.filter(
      (t) => (t.kind === "file" ? t.path : `diff:${t.path}`) !== path,
    );
    const last = tabs.at(-1);
    const activePath =
      get().activePath === path ? (last && last.kind === "file" ? last.path : null) : get().activePath;
    set({ tabs, activePath });
  },

  setActive: (path) => set({ activePath: path }),

  updateContent: (path, content) => {
    set({
      tabs: get().tabs.map((t) => (t.kind === "file" && t.path === path ? { ...t, content } : t)),
    });
  },

  saveActive: async () => {
    const { project, activePath, tabs } = get();
    if (!project || !activePath) return;
    const tab = tabs.find((t) => t.kind === "file" && t.path === activePath);
    if (!tab || tab.kind !== "file" || tab.isBinary) return;
    const saved = await api.writeFile(project.id, tab.path, tab.content);
    set({
      tabs: get().tabs.map((t) =>
        t.kind === "file" && t.path === tab.path ? { ...t, savedContent: saved.content } : t,
      ),
    });
  },

  runTool: async (tool, path) => {
    const { project } = get();
    if (!project) return;
    const result = await api.runTool(project.id, { tool, path });
    if (get().project?.id !== project.id) return;
    set({ output: result, panelTab: "output", panelOpen: true });
    if (tool === "format" && path && result.file_content !== null) {
      set({
        tabs: get().tabs.map((t) =>
          t.kind === "file" && t.path === path
            ? {
                ...t,
                content: result.file_content ?? "",
                savedContent: result.file_content ?? "",
              }
            : t,
        ),
      });
    }
    await get().refreshToolchains();
  },

  createTerminal: async () => {
    const project = get().project;
    if (!project) return;
    const session = await api.createTerminalSession(project.id);
    if (get().project?.id !== project.id) return;
    set({
      terminalIds: [...get().terminalIds, session.id],
      activeTerminal: session.id,
      panelOpen: true,
      panelTab: "terminal",
    });
  },

  closeTerminal: (id) => {
    const remaining = get().terminalIds.filter((tid) => tid !== id);
    set({
      terminalIds: remaining,
      activeTerminal:
        get().activeTerminal === id ? (remaining.at(-1) ?? null) : get().activeTerminal,
    });
  },
}));

export const isDirty = (tab: FileTab): boolean => tab.content !== tab.savedContent;
useStore.subscribe((state, prev) => {
  if (state.sidebarOpen !== prev.sidebarOpen || state.panelOpen !== prev.panelOpen ||
      state.sidebarWidth !== prev.sidebarWidth || state.panelHeight !== prev.panelHeight) {
    saveLayout({ sidebarOpen: state.sidebarOpen, sidebarWidth: state.sidebarWidth,
      panelOpen: state.panelOpen, panelHeight: state.panelHeight });
  }
});
