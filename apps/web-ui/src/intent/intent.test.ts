// Intent classification + plan tests (Wave 10), including the 14 §34
// evaluation cases as a deterministic table: correct intent, correct
// capability, correct confirmation behavior — no model calls.
import { describe, expect, it } from "vitest";

import { classifyIntent, type ClassifyContext, type IntentType } from "./classify";
import { planFor } from "./plan";
import { extractIdentifiers } from "./queries";

const base: ClassifyContext = {
  projectId: "p",
  requirementId: null,
  taskId: null,
  agentId: null,
  filePath: null,
  selectionChars: 0,
  selectionLines: 0,
  hasFailedTask: false,
  hasFailureOutput: false,
};

const withFile: ClassifyContext = { ...base, filePath: "auth.py", selectionChars: 120, selectionLines: 8 };
const withFailure: ClassifyContext = { ...base, hasFailedTask: true, taskId: "t1" };
const withRequirement: ClassifyContext = { ...base, requirementId: "r1" };
const withTask: ClassifyContext = { ...base, taskId: "t1" };

interface EvalCase {
  name: string;
  text: string;
  ctx: ClassifyContext;
  intent: IntentType;
  confirm: boolean;
  capability: string;
}

function capabilityOf(intent: ReturnType<typeof classifyIntent>): string {
  switch (intent.intentType) {
    case "implement_feature":
    case "create_plan":
      return "createTask";
    case "fix_failure":
      return "createTask";
    case "explain_code":
    case "explain_failure":
    case "find_usages":
    case "find_affected_code":
      return "codeIntel";
    case "run_tests":
      return "runTool";
    case "review_requirement":
      return "traceability";
    case "review_security":
    case "review_implementation":
      return "runReview";
    case "start_execution":
    case "control_execution":
      return "controlTask";
    case "open_surface":
      return "navigate";
    case "ask_architecture":
      return "diagnostics";
    case "research_topic":
      return "research";
    case "cost_query":
      return "costs";
    case "hitl_guidance":
      return "navigate";
    default:
      return "none";
  }
}

const EVAL_CASES: EvalCase[] = [
  { name: "code explanation", text: "Explain this function", ctx: withFile, intent: "explain_code", confirm: false, capability: "codeIntel" },
  { name: "refactoring request", text: "Refactor this function and add tests", ctx: withFile, intent: "implement_feature", confirm: true, capability: "createTask" },
  { name: "test failure investigation", text: "Why is this test failing?", ctx: withFailure, intent: "fix_failure", confirm: false, capability: "createTask" },
  { name: "requirement implementation", text: "Implement this requirement", ctx: withRequirement, intent: "implement_feature", confirm: true, capability: "createTask" },
  { name: "requirement coverage", text: "Review coverage against the requirements", ctx: withRequirement, intent: "review_requirement", confirm: false, capability: "traceability" },
  { name: "repository relationship query", text: "Where is this table used?", ctx: withFile, intent: "find_usages", confirm: false, capability: "codeIntel" },
  { name: "execution control", text: "Pause it", ctx: withTask, intent: "control_execution", confirm: true, capability: "controlTask" },
  { name: "HITL request routes to guidance", text: "Approve the pending request", ctx: withTask, intent: "hitl_guidance", confirm: false, capability: "navigate" },
  { name: "permission-denied scope stays safe", text: "Delete the production database", ctx: base, intent: "unsupported", confirm: false, capability: "none" },
  { name: "context ambiguity clarifies", text: "Fix it", ctx: base, intent: "unknown", confirm: false, capability: "none" },
  { name: "large-context request still routes", text: "Explain this file", ctx: { ...withFile, selectionChars: 50000, selectionLines: 900 }, intent: "explain_code", confirm: false, capability: "codeIntel" },
  { name: "model failure maps to review gating", text: "Review this implementation", ctx: withTask, intent: "review_implementation", confirm: true, capability: "runReview" },
  { name: "realtime disconnect is navigation-safe", text: "Open the timeline", ctx: base, intent: "open_surface", confirm: false, capability: "navigate" },
  { name: "cost-budget boundary", text: "How many tokens have we spent?", ctx: base, intent: "cost_query", confirm: false, capability: "costs" },
];

describe("§34 evaluation cases (deterministic, no model calls)", () => {
  let passed = 0;
  for (const c of EVAL_CASES) {
    it(c.name, () => {
      const intent = classifyIntent(c.text, c.ctx);
      expect(intent.intentType).toBe(c.intent);
      expect(intent.confirmationRequired).toBe(c.confirm);
      expect(capabilityOf(intent)).toBe(c.capability);
      passed += 1;
    });
  }
  it("reports the suite tally", () => {
    expect(EVAL_CASES).toHaveLength(14);
    expect(passed).toBe(EVAL_CASES.length);
  });
});

describe("extractIdentifiers", () => {
  it("prefers quoted strings then code-like tokens, bounded", () => {
    expect(extractIdentifiers('Where is "auth_callback" used?')).toContain("auth_callback");
    expect(extractIdentifiers("Find usages of validate_token here")).toContain("validate_token");
    expect(extractIdentifiers("do it")).toEqual([]);
  });
});

describe("classifyIntent rules", () => {
  it("is empty-safe", () => {
    const intent = classifyIntent("   ", base);
    expect(intent.intentType).toBe("unknown");
    expect(intent.clarifyPrompt).toContain("Describe");
  });

  it("prefers failure scope for fix language", () => {
    expect(classifyIntent("Fix this", withFailure).intentType).toBe("fix_failure");
    expect(classifyIntent("Fix this", withFile).intentType).toBe("implement_feature");
  });

  it("distinguishes review kinds", () => {
    expect(classifyIntent("Review the auth flow security", withFile).intentType).toBe("review_security");
    expect(classifyIntent("Review requirement coverage", withRequirement).intentType).toBe("review_requirement");
  });

  it("maps control verbs with kinds", () => {
    expect(classifyIntent("Retry the task", withTask)).toMatchObject({ intentType: "control_execution", control: "retry", confirmationRequired: true });
    expect(classifyIntent("Start it", withTask)).toMatchObject({ intentType: "start_execution", control: "start" });
  });

  it("resolves surfaces for navigation", () => {
    expect(classifyIntent("Open the execution graph", base)).toMatchObject({ intentType: "open_surface", surface: "graph" });
    expect(classifyIntent("Show me the money", base).intentType).toBe("unknown");
  });

  it("gates research on external-network confirmation", () => {
    const intent = classifyIntent("What is the current best practice for OAuth?", base);
    expect(intent.intentType).toBe("research_topic");
    expect(intent.confirmationRequired).toBe(true);
  });
});

describe("planFor", () => {
  it("builds gated dispatch plans for consequential intents", () => {
    const plan = planFor(classifyIntent("Implement JWT auth", withRequirement));
    expect(plan.goal).toContain("Implement JWT auth");
    expect(plan.actions.some((a) => a.id === "create_task" && a.gated)).toBe(true);
  });

  it("keeps intel plans ungated with real steps", () => {
    const plan = planFor(classifyIntent("Where is this used?", withFile));
    expect(plan.actions.every((a) => !a.gated)).toBe(true);
    expect(plan.steps.length).toBeGreaterThan(0);
  });

  it("never dispatches for unsupported; unknown stays read-only", () => {
    expect(planFor(classifyIntent("Delete everything", base)).actions).toEqual([]);
    const unknownActions = planFor(classifyIntent("", base)).actions;
    expect(unknownActions).toHaveLength(1);
    expect(unknownActions.every((a) => !a.gated)).toBe(true);
  });
});
