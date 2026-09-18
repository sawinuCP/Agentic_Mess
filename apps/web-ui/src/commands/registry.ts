// Command registry for the Wave 6 command palette (Phase 4).
//
// Pure data + logic: no React, no DOM — unit-testable in the node Vitest
// suite. Every command maps to an existing real frontend action and checks
// availability with a disabled reason. Commands that would require backend
// capabilities the client does not expose (per-agent pause/resume/stop, task
// creation, workspace symbol search, settings/runtime views) are deliberately
// absent — see docs/frontend-interaction-model.md. Task-level stop is covered
// separately by taskCommands ("Cancel task" via POST /api/tasks/{id}/cancel).

import type { ViewId } from "../state/store";

export type OfficeTabId = "team" | "timeline" | "comms" | "oversight";

export interface CommandActions {
  setView: (view: ViewId) => void;
  setOfficeTab: (tab: OfficeTabId) => void;
  openQuickOpen: () => void;
  openProjectDialog: () => void;
  openTerminal: () => void | Promise<void>;
  showToolOutput: () => void;
  openSystemDiagnostics: () => void;
  runTool: (tool: string, path?: string) => void | Promise<void>;
}

export interface CommandContext {
  hasProject: boolean;
  hasTestRunner: boolean;
  hasLinter: boolean;
  hasFormatter: boolean;
  hasRunner: boolean;
  hasBuilder: boolean;
  activeFilePath: string | null;
}

export interface Command {
  id: string;
  label: string;
  category: string;
  keywords: string[];
  shortcut?: string;
  disabledReason?: string;
  run: () => void | Promise<void>;
}

const NO_PROJECT = "Open a project first";

export function buildCommands(ctx: CommandContext, a: CommandActions) {
  const fileTool = (available: boolean): string | undefined => {
    if (!ctx.hasProject) return NO_PROJECT;
    if (!ctx.activeFilePath) return "Open a file first";
    if (!available) return "Tool not detected for this project";
    return undefined;
  };

  const commands: Command[] = [
    // --- workspace ----------------------------------------------------------
    {
      id: "workspace.open-project",
      label: "Open project…",
      category: "Workspace",
      keywords: ["open", "folder", "directory", "recent"],
      run: () => a.openProjectDialog(),
    },
    {
      id: "workspace.goto-file",
      label: "Go to file…",
      category: "Workspace",
      keywords: ["search", "files", "quick open", "open"],
      shortcut: "Ctrl+P",
      disabledReason: ctx.hasProject ? undefined : NO_PROJECT,
      run: () => a.openQuickOpen(),
    },
    {
      id: "workspace.search-text",
      label: "Search in files…",
      category: "Workspace",
      keywords: ["find", "grep", "text", "project search"],
      disabledReason: ctx.hasProject ? undefined : NO_PROJECT,
      run: () => a.setView("search"),
    },
    {
      id: "workspace.changed-files",
      label: "Show changed files",
      category: "Workspace",
      keywords: ["git", "source control", "diff", "status"],
      disabledReason: ctx.hasProject ? undefined : NO_PROJECT,
      run: () => a.setView("git"),
    },
    // --- navigation ---------------------------------------------------------
    {
      id: "nav.explorer",
      label: "Show explorer",
      category: "Navigation",
      keywords: ["files", "tree", "sidebar"],
      run: () => a.setView("explorer"),
    },
    {
      id: "nav.run",
      label: "Show run and toolchains",
      category: "Navigation",
      keywords: ["tools", "languages", "format", "test"],
      run: () => a.setView("run"),
    },
    {
      id: "nav.office",
      label: "Open engineering office",
      category: "Navigation",
      keywords: ["agents", "tasks", "ai", "activity"],
      run: () => a.setView("office"),
    },
    // --- execution ----------------------------------------------------------
    {
      id: "execution.run-file",
      label: "Run active file",
      category: "Execution",
      keywords: ["execute", "run", "script"],
      disabledReason: fileTool(ctx.hasRunner),
      run: () => a.runTool("run", ctx.activeFilePath ?? undefined),
    },
    {
      id: "execution.format-file",
      label: "Format active file",
      category: "Execution",
      keywords: ["format", "prettier", "beautify", "style"],
      disabledReason: fileTool(ctx.hasFormatter),
      run: () => a.runTool("format", ctx.activeFilePath ?? undefined),
    },
    {
      id: "execution.run-tests",
      label: "Run tests",
      category: "Execution",
      keywords: ["test", "pytest", "suite", "validate"],
      disabledReason: ctx.hasProject
        ? ctx.hasTestRunner
          ? undefined
          : "No test runner detected"
        : NO_PROJECT,
      run: () => a.runTool("test"),
    },
    {
      id: "execution.build",
      label: "Run build",
      category: "Execution",
      keywords: ["build", "compile", "package"],
      disabledReason: ctx.hasProject
        ? ctx.hasBuilder
          ? undefined
          : "No build system detected"
        : NO_PROJECT,
      run: () => a.runTool("build"),
    },
    {
      id: "execution.show-output",
      label: "Show tool output",
      category: "Execution",
      keywords: ["output", "panel", "logs", "results"],
      run: () => a.showToolOutput(),
    },
    {
      id: "execution.terminal",
      label: "Open terminal",
      category: "Execution",
      keywords: ["shell", "console", "pty"],
      disabledReason: ctx.hasProject ? undefined : NO_PROJECT,
      run: () => a.openTerminal(),
    },
    // --- validation / diagnostics ---------------------------------------------
    {
      id: "validation.lint",
      label: "Run linter",
      category: "Validation",
      keywords: ["lint", "eslint", "ruff", "check"],
      disabledReason: ctx.hasProject
        ? ctx.hasLinter
          ? undefined
          : "No linter detected"
        : NO_PROJECT,
      run: () => a.runTool("lint"),
    },
    {
      id: "validation.system",
      label: "Show system diagnostics",
      category: "Validation",
      keywords: ["health", "database", "redis", "nats", "support"],
      run: () => a.openSystemDiagnostics(),
    },
    // --- agents / oversight -----------------------------------------------------
    {
      id: "agents.active",
      label: "View active agents",
      category: "Agents",
      keywords: ["agents", "team", "office", "running"],
      run: () => {
        a.setView("office");
        a.setOfficeTab("team");
      },
    },
    {
      id: "agents.timeline",
      label: "Open event timeline",
      category: "Agents",
      keywords: ["history", "events", "activity", "log"],
      run: () => {
        a.setView("office");
        a.setOfficeTab("timeline");
      },
    },
    {
      id: "agents.comms",
      label: "Open agent communication",
      category: "Agents",
      keywords: ["messages", "chat", "handoff", "coordination"],
      run: () => {
        a.setView("office");
        a.setOfficeTab("comms");
      },
    },
    {
      id: "oversight.coverage",
      label: "Open requirement coverage",
      category: "Agents",
      keywords: ["oversight", "traceability", "criteria", "verification", "completion"],
      run: () => {
        a.setView("office");
        a.setOfficeTab("oversight");
      },
    },
  ];

  return commands;
}

/** Case-insensitive substring filter over label, category and keywords. */
export function filterCommands(commands: Command[], query: string): Command[] {
  const q = query.trim().toLowerCase();
  if (!q) return commands;
  return commands.filter((command) =>
    [command.label, command.category, ...command.keywords]
      .join(" ")
      .toLowerCase()
      .includes(q),
  );
}

/** Indices of selectable (enabled) commands — selection never lands on disabled rows. */
export function selectableIndexes(commands: Command[]): number[] {
  return commands.reduce<number[]>((acc, command, index) => {
    if (!command.disabledReason) acc.push(index);
    return acc;
  }, []);
}

/** Next selectable index with wraparound; -1 when nothing is selectable. */
export function nextSelectable(
  commands: Command[],
  selectedIndex: number,
  direction: 1 | -1,
): number {
  const selectable = selectableIndexes(commands);
  if (selectable.length === 0) return -1;
  if (selectedIndex < 0) return selectable[0];
  const position = selectable.indexOf(selectedIndex);
  if (position === -1) {
    // Current selection is disabled (e.g. filter changed): pick nearest.
    return direction === 1 ? selectable[0] : selectable[selectable.length - 1];
  }
  return selectable[(position + direction + selectable.length) % selectable.length];
}

/** First selectable index, or -1. */
export function firstSelectable(commands: Command[]): number {
  const selectable = selectableIndexes(commands);
  return selectable.length > 0 ? selectable[0] : -1;
}

