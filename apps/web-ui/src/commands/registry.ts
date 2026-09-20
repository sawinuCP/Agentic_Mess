// Command registry for the Wave 6 command palette (Phase 4).
//
// Pure data + logic: no React, no DOM — unit-testable in the node Vitest
// suite. Every command maps to an existing real frontend action and checks
// availability with a disabled reason. Commands that would require backend
// capabilities the client does not expose (per-agent pause/resume/stop,
// dedicated problems/runtime/settings views) are deliberately absent — see
// docs/frontend-interaction-model.md. Task-level stop is covered separately
// by taskCommands ("Cancel task" via POST /api/tasks/{id}/cancel).

import type { ViewId } from "../state/store";

export type OfficeTabId = "team" | "timeline" | "comms" | "oversight";

export interface CommandActions {
  setView: (view: ViewId) => void;
  setOfficeTab: (tab: OfficeTabId) => void;
  toggleTheme: () => void;
  openQuickOpen: () => void;
  openSymbolSearch: () => void;
  openSpawnDialog: () => void;
  openTaskDialog: () => void;
  openCommandCenter: (prefill?: string) => void;
  openMcpDialog: () => void;
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
  hasSelection: boolean;
  hasFailure: boolean;
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
      id: "workspace.search-symbols",
      label: "Search symbols…",
      category: "Workspace",
      keywords: ["symbols", "definition", "function", "class", "workspace symbol", "scip"],
      disabledReason: ctx.hasProject ? undefined : NO_PROJECT,
      run: () => a.openSymbolSearch(),
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
      label: "Workspace",
      category: "Navigation",
      keywords: ["files", "tree", "sidebar", "explorer", "show explorer"],
      run: () => a.setView("explorer"),
    },
    {
      id: "nav.run",
      label: "Tools",
      category: "Navigation",
      keywords: ["tools", "languages", "format", "test", "run", "toolchains"],
      run: () => a.setView("run"),
    },
    {
      id: "nav.office",
      label: "Agents",
      category: "Navigation",
      keywords: ["agents", "tasks", "ai", "activity", "office", "engineering office"],
      run: () => a.setView("office"),
    },
    {
      id: "nav.graph",
      label: "Execution",
      category: "Navigation",
      keywords: ["graph", "traceability", "requirements", "dependencies", "lineage", "execution graph"],
      disabledReason: ctx.hasProject ? undefined : NO_PROJECT,
      run: () => a.setView("graph"),
    },
    {
      id: "nav.history",
      label: "History",
      category: "Navigation",
      keywords: ["history", "timeline", "replay", "events", "audit", "debug", "execution history"],
      disabledReason: ctx.hasProject ? undefined : NO_PROJECT,
      run: () => a.setView("history"),
    },
    {
      id: "nav.problems",
      label: "Problems",
      category: "Navigation",
      keywords: ["problems", "failures", "errors", "blocked", "approvals", "triage"],
      disabledReason: ctx.hasProject ? undefined : NO_PROJECT,
      run: () => a.setView("problems"),
    },
    {
      id: "nav.runtime",
      label: "Runtime",
      category: "Navigation",
      keywords: ["runtime", "ports", "leases", "resources", "allocations"],
      disabledReason: ctx.hasProject ? undefined : NO_PROJECT,
      run: () => a.setView("runtime"),
    },
    {
      id: "nav.theme",
      label: "Toggle color theme",
      category: "Navigation",
      keywords: ["theme", "dark", "light", "appearance", "colors"],
      run: () => a.toggleTheme(),
    },
    {
      id: "nav.settings",
      label: "Settings",
      category: "Navigation",
      keywords: ["settings", "token", "layout", "configuration", "preferences"],
      run: () => a.setView("settings"),
    },
    {
      id: "nav.command",
      label: "Command Center…",
      category: "Navigation",
      keywords: ["ai", "assistant", "ask", "command center", "help", "howto"],
      disabledReason: ctx.hasProject ? undefined : NO_PROJECT,
      run: () => a.openCommandCenter(),
    },
    {
      id: "ai.explain-selection",
      label: "Explain selection",
      category: "Agents",
      keywords: ["explain", "selection", "code", "what does"],
      disabledReason: !ctx.hasProject
        ? NO_PROJECT
        : !ctx.hasSelection
          ? "Select code in the editor first"
          : undefined,
      run: () => a.openCommandCenter("Explain this"),
    },
    {
      id: "ai.investigate-failure",
      label: "Investigate failure",
      category: "Agents",
      keywords: ["investigate", "failure", "debug", "broken", "error", "flaky"],
      disabledReason: !ctx.hasProject
        ? NO_PROJECT
        : !ctx.hasFailure
          ? "No failed task or tool run recorded"
          : undefined,
      run: () => a.openCommandCenter("Investigate this failure"),
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
      label: "Activity",
      category: "Agents",
      keywords: ["history", "events", "activity", "log", "timeline", "event timeline"],
      run: () => {
        a.setView("office");
        a.setOfficeTab("timeline");
      },
    },
    {
      id: "agents.comms",
      label: "Agent communication",
      category: "Agents",
      keywords: ["messages", "chat", "handoff", "coordination", "comms"],
      run: () => {
        a.setView("office");
        a.setOfficeTab("comms");
      },
    },
    {
      id: "agents.spawn",
      label: "New agent…",
      category: "Agents",
      keywords: ["spawn", "create agent", "new agent", "register", "spawn agent"],
      disabledReason: ctx.hasProject ? undefined : NO_PROJECT,
      run: () => a.openSpawnDialog(),
    },
    {
      id: "task.create",
      label: "Create task…",
      category: "Execution",
      keywords: ["create task", "new task", "add task", "plan"],
      disabledReason: ctx.hasProject ? undefined : NO_PROJECT,
      run: () => a.openTaskDialog(),
    },
    {
      id: "mcp.call-tool",
      label: "Call MCP tool…",
      category: "Execution",
      keywords: ["mcp", "external tool", "model context protocol", "gateway"],
      disabledReason: ctx.hasProject ? undefined : NO_PROJECT,
      run: () => a.openMcpDialog(),
    },
    {
      id: "oversight.coverage",
      label: "Requirements",
      category: "Agents",
      keywords: ["oversight", "traceability", "criteria", "verification", "completion", "coverage", "requirements"],
      run: () => {
        a.setView("office");
        a.setOfficeTab("oversight");
      },
    },
  ];

  return commands;
}

/** Fuzzy subsequence score (lower is better) over label + category +
 * keywords. Contiguous and word-boundary matches score best; non-matches
 * return null. Substring matches always score (never worse than before). */
export function fuzzyScore(command: Command, query: string): number | null {
  const q = query.trim().toLowerCase();
  if (!q) return 0;
  const hay = [command.label, command.category, ...command.keywords].join(" ").toLowerCase();
  // Substring tier (negative scores): the classic contract, always complete.
  if (hay.includes(q)) return -1000 + hay.indexOf(q);
  // Fuzzy tier (non-negative scores): subsequence fallback for typos.
  let score = 1000;
  let hi = 0;
  let run = 0;
  for (let qi = 0; qi < q.length; qi++) {
    const ch = q[qi];
    const found = hay.indexOf(ch, hi);
    if (found < 0) return null;
    if (found === hi) {
      run += 1;
      score -= 2 + run;
    } else {
      run = 0;
      score += found - hi;
    }
    if (found === 0 || hay[found - 1] === " ") score -= 3;
    hi = found + 1;
  }
  return score;
}

/** Case-insensitive filter over label, category and keywords, best matches
 * first. Substring matches always win as a tier (preserving the classic
 * contract); fuzzy subsequence matching only widens queries that would
 * otherwise return nothing (typo tolerance). Empty query returns everything
 * in registry order. */
export function filterCommands(commands: Command[], query: string): Command[] {
  if (!query.trim()) return commands;
  const scored = commands
    .map((command, index) => ({ command, index, score: fuzzyScore(command, query) }))
    .filter((entry): entry is { command: Command; index: number; score: number } => entry.score !== null)
    .sort((a, b) => a.score - b.score || a.index - b.index);
  if (scored.some((entry) => entry.score < 0)) {
    return scored.filter((entry) => entry.score < 0).map((entry) => entry.command);
  }
  return scored.map((entry) => entry.command);
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

