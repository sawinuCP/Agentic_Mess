// Global IDE state (zustand). Slices: project, explorer, editor, git, run, panel.

import { create } from "zustand";

import * as api from "../api/client";
import type { GitStatus, ProjectInfo, ProjectToolchains, ToolRunResult, TreeNode } from "../types";
import { monacoLanguageFor } from "../util/languages";

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
  panelOpen: boolean;
  panelTab: "terminal" | "output";
  terminalIds: string[];
  activeTerminal: string | null;
  quickOpen: boolean;
  commandPalette: boolean;
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

export const useStore = create<AppState>((set, get) => ({
  project: null,
  toolchains: null,
  git: null,
  tree: {},
  expanded: { "": true },
  tabs: [],
  activePath: null,
  view: "explorer",
  panelOpen: true,
  panelTab: "terminal",
  terminalIds: [],
  activeTerminal: null,
  quickOpen: false,
  commandPalette: false,
  projectDialog: false,
  diagnosticsOpen: false,
  output: null,

  set: (partial) => set(partial),

  openProject: async (rootPath) => {
    const project = await api.openProject(rootPath);
    set({ project, tree: {}, expanded: { "": true }, tabs: [], activePath: null });
    await Promise.all([get().refreshTree(), get().refreshToolchains(), get().refreshGit()]);
    if (get().terminalIds.length === 0) {
      await get().createTerminal();
    }
  },

  refreshGit: async () => {
    const project = get().project;
    if (!project) return;
    try {
      set({ git: await api.gitStatus(project.id) });
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
    set({ toolchains: await api.getProjectToolchains(project.id) });
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
    set((state) => ({ tree: { ...state.tree, [dirPath]: children } }));
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
