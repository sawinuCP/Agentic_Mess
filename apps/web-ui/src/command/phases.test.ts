// Unit tests for entry-phase derivation (pure logic, node environment).
import { describe, expect, it } from "vitest";

import { entryPhase } from "./phases";
import type { CenterEntry } from "./types";
import type { TaskInfo } from "../types";

const base: CenterEntry = {
  id: 1,
  request: "x",
  intent: {
    intentType: "implement_feature",
    request: "x",
    scope: {
      projectId: null,
      requirementId: null,
      taskId: null,
      agentId: null,
      filePath: null,
      selectionLines: 0,
      hasSelection: false,
      hasFailedTask: false,
      hasFailureOutput: false,
    },
    confirmationRequired: false,
    confirmReason: null,
    confidence: "high",
    clarifyPrompt: null,
  },
  plan: { goal: "g", steps: [], affected: [], estimates: [], actions: [] },
  status: "preview",
  statusText: "",
  findings: [],
  dispatches: [],
  error: null,
  createdAt: new Date().toISOString(),
  branchedFrom: null,
  awaiting: null,
};

const task = (id: string, status: string): TaskInfo => ({
  id,
  project_id: "p",
  requirement_id: null,
  title: id,
  request: "",
  status,
  priority: 1,
  depends_on: [],
  attempts: [],
});

describe("entryPhase", () => {
  it("maps preview intent to discussing/planning", () => {
    expect(entryPhase(base, [])).toBe("planning");
    expect(entryPhase({
      ...base,
      intent: { ...base.intent, intentType: "unknown" },
    }, [])).toBe("discussing");
  });

  it("maps running to executing/awaiting/verifying/blocked", () => {
    expect(entryPhase({ ...base, status: "running" }, [])).toBe("executing");
    expect(entryPhase({
      ...base,
      status: "running",
      awaiting: { actionId: "a", label: "a", detail: "" },
    }, [])).toBe("awaiting");
    const withTask = {
      ...base,
      status: "running" as const,
      dispatches: [{ label: "d", ok: true, detail: "", taskId: "t" }],
    };
    expect(entryPhase(withTask, [task("t", "verifying")])).toBe("verifying");
    expect(entryPhase(withTask, [task("t", "failed")])).toBe("blocked");
    expect(entryPhase(withTask, [task("t", "running")])).toBe("executing");
  });

  it("maps done/error to completed/blocked/failed", () => {
    expect(entryPhase({ ...base, status: "done" }, [])).toBe("completed");
    const withTask = {
      ...base,
      status: "done" as const,
      dispatches: [{ label: "d", ok: true, detail: "", taskId: "t" }],
    };
    expect(entryPhase(withTask, [task("t", "blocked")])).toBe("blocked");
    expect(entryPhase(withTask, [task("t", "completed")])).toBe("completed");
    expect(entryPhase({ ...base, status: "error", error: "boom" }, [])).toBe("failed");
    expect(entryPhase({
      ...base,
      status: "done",
      dispatches: [{ label: "r", ok: true, detail: "", reviewVerdict: "request-changes" }],
    }, [])).toBe("blocked");
  });
});
