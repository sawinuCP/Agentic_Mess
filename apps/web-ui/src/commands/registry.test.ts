// Unit tests for the command registry (pure logic, node environment).
import { describe, expect, it, vi } from "vitest";

import {
  buildCommands,
  filterCommands,
  firstSelectable,
  nextSelectable,
  selectableIndexes,
  type CommandActions,
} from "./registry";

const ctxFull = {
  hasProject: true,
  hasTestRunner: true,
  hasLinter: true,
  hasFormatter: true,
  hasRunner: true,
  hasBuilder: true,
  activeFilePath: "src/app.ts",
};

const ctxEmpty = {
  hasProject: false,
  hasTestRunner: false,
  hasLinter: false,
  hasFormatter: false,
  hasRunner: false,
  hasBuilder: false,
  activeFilePath: null,
};

function makeActions(): CommandActions & Record<string, ReturnType<typeof vi.fn>> {
  return {
    setView: vi.fn(),
    setOfficeTab: vi.fn(),
    openQuickOpen: vi.fn(),
    openProjectDialog: vi.fn(),
    openTerminal: vi.fn(),
    showToolOutput: vi.fn(),
    openSystemDiagnostics: vi.fn(),
    runTool: vi.fn(),
  };
}

describe("buildCommands", () => {
  it("exposes categorized commands with keywords and real actions", () => {
    const actions = makeActions();
    const commands = buildCommands(ctxFull, actions);
    expect(commands.length).toBeGreaterThanOrEqual(15);
    const categories = new Set(commands.map((c) => c.category));
    for (const expected of ["Workspace", "Navigation", "Execution", "Validation", "Agents"]) {
      expect(categories.has(expected)).toBe(true);
    }
    for (const command of commands) {
      expect(command.label.length).toBeGreaterThan(0);
      expect(command.keywords.length).toBeGreaterThan(0);
      expect(typeof command.run).toBe("function");
    }
  });

  it("marks project-dependent commands disabled without a project", () => {
    const commands = buildCommands(ctxEmpty, makeActions());
    const gotoFile = commands.find((c) => c.id === "workspace.goto-file");
    const search = commands.find((c) => c.id === "workspace.search-text");
    const terminal = commands.find((c) => c.id === "execution.terminal");
    expect(gotoFile?.disabledReason).toBe("Open a project first");
    expect(search?.disabledReason).toBe("Open a project first");
    expect(terminal?.disabledReason).toBe("Open a project first");
    // Global navigation stays available.
    expect(commands.find((c) => c.id === "nav.explorer")?.disabledReason).toBeUndefined();
  });

  it("explains missing tools for file-bound commands", () => {
    const commands = buildCommands(
      { ...ctxFull, hasFormatter: false, hasTestRunner: false, hasBuilder: false },
      makeActions(),
    );
    expect(commands.find((c) => c.id === "execution.format-file")?.disabledReason).toBe(
      "Tool not detected for this project",
    );
    expect(commands.find((c) => c.id === "execution.run-tests")?.disabledReason).toBe(
      "No test runner detected",
    );
    expect(commands.find((c) => c.id === "execution.build")?.disabledReason).toBe(
      "No build system detected",
    );
  });

  it("runs the build tool when a builder is detected", () => {
    const actions = makeActions();
    const commands = buildCommands(ctxFull, actions);
    const build = commands.find((c) => c.id === "execution.build");
    expect(build?.disabledReason).toBeUndefined();
    build?.run();
    expect(actions.runTool).toHaveBeenCalledWith("build");
  });

  it("requires an active file for file-bound commands", () => {
    const commands = buildCommands({ ...ctxFull, activeFilePath: null }, makeActions());
    expect(commands.find((c) => c.id === "execution.run-file")?.disabledReason).toBe(
      "Open a file first",
    );
  });

  it("executes the real action for navigation commands", () => {
    const actions = makeActions();
    const commands = buildCommands(ctxFull, actions);
    commands.find((c) => c.id === "agents.active")?.run();
    expect(actions.setView).toHaveBeenCalledWith("office");
    expect(actions.setOfficeTab).toHaveBeenCalledWith("team");
    commands.find((c) => c.id === "agents.comms")?.run();
    expect(actions.setView).toHaveBeenCalledWith("office");
    expect(actions.setOfficeTab).toHaveBeenCalledWith("comms");
    commands.find((c) => c.id === "workspace.open-project")?.run();
    expect(actions.openProjectDialog).toHaveBeenCalledTimes(1);
  });
});

describe("filterCommands", () => {
  const commands = buildCommands(ctxFull, makeActions());

  it("returns everything for an empty query", () => {
    expect(filterCommands(commands, "")).toEqual(commands);
    expect(filterCommands(commands, "   ")).toEqual(commands);
  });

  it("matches label, category and keywords case-insensitively", () => {
    const byLabel = filterCommands(commands, "TERMINAL");
    expect(byLabel.some((c) => c.id === "execution.terminal")).toBe(true);
    const byKeyword = filterCommands(commands, "pytest");
    expect(byKeyword.some((c) => c.id === "execution.run-tests")).toBe(true);
    const byCategory = filterCommands(commands, "navigation");
    expect(byCategory.every((c) => c.category === "Navigation")).toBe(true);
  });

  it("returns nothing for garbage input", () => {
    expect(filterCommands(commands, "zzz-nonexistent")).toEqual([]);
  });
});

describe("selection helpers", () => {
  const commands = [
    { id: "a", disabledReason: undefined },
    { id: "b", disabledReason: "no" },
    { id: "c", disabledReason: undefined },
    { id: "d", disabledReason: undefined },
  ] as ReturnType<typeof buildCommands>;

  it("computes selectable indices skipping disabled rows", () => {
    expect(selectableIndexes(commands)).toEqual([0, 2, 3]);
    expect(firstSelectable(commands)).toBe(0);
  });

  it("moves forward with wraparound and never lands on disabled rows", () => {
    expect(nextSelectable(commands, 0, 1)).toBe(2);
    expect(nextSelectable(commands, 2, 1)).toBe(3);
    expect(nextSelectable(commands, 3, 1)).toBe(0);
  });

  it("moves backward with wraparound", () => {
    expect(nextSelectable(commands, 2, -1)).toBe(0);
    expect(nextSelectable(commands, 0, -1)).toBe(3);
  });

  it("recovers when the current selection is disabled", () => {
    expect(nextSelectable(commands, 1, 1)).toBe(0);
    expect(nextSelectable(commands, 1, -1)).toBe(3);
  });

  it("returns -1 when nothing is selectable", () => {
    const allDisabled = [
      { id: "x", disabledReason: "no" },
      { id: "y", disabledReason: "no" },
    ] as ReturnType<typeof buildCommands>;
    expect(firstSelectable(allDisabled)).toBe(-1);
    expect(nextSelectable(allDisabled, 0, 1)).toBe(-1);
  });
});
