// Context assembly tests: budgets, truncation labels, secret redaction.
import { describe, expect, it } from "vitest";

import { assembleContext, redactSecrets } from "./assemble";

const base = {
  actionLabel: "Explain selection",
  scopeLabel: "auth.py",
  safetyNote: null,
  entityLines: [],
  requirementLine: null,
  filePath: "auth.py",
  fileContent: Array.from({ length: 200 }, (_, i) => `line${i + 1}`).join("\n"),
  selection: null,
  symbols: [],
  relatedTests: [],
  executionLines: [],
  agentLines: [],
  dependencyLines: [],
  recentEvents: [],
  attemptLines: [],
  artifactRefs: [],
};

describe("redactSecrets", () => {
  it("redacts hardcoded secret assignments, keeps the rest", () => {
    const { text, redacted } = redactSecrets('api_key = "sk-live-123"\nport = 8080');
    expect(redacted).toBe(true);
    expect(text).toContain('api_key = "[redacted]"');
    expect(text).toContain("port = 8080");
    expect(redactSecrets("no secrets here").redacted).toBe(false);
  });
});

describe("assembleContext", () => {
  it("slices around the selection with a note", () => {
    const snap = assembleContext({
      ...base,
      selection: { startLine: 100, endLine: 104, text: "x" },
    });
    expect(snap.t2.join("\n")).toContain("slice lines");
    expect(snap.t2.join("\n")).toContain("line100");
    expect(snap.t2.join("\n")).not.toContain("line1\n");
  });

  it("caps symbols, tests, and events with labels", () => {
    const snap = assembleContext({
      ...base,
      symbols: Array.from({ length: 30 }, (_, i) => ({ name: `s${i}`, kind: "function", line: i })),
      relatedTests: Array.from({ length: 10 }, (_, i) => ({ path: `t${i}.py`, name: `test_${i}` })),
      recentEvents: Array.from({ length: 25 }, (_, i) => `event ${i}`),
    });
    expect(snap.truncated).toContain("symbols capped at 15");
    expect(snap.truncated).toContain("related tests capped at 6");
    expect(snap.truncated).toContain("events capped at 10");
  });

  it("caps oversized selections and reports budgets", () => {
    const snap = assembleContext({
      ...base,
      selection: { startLine: 1, endLine: 900, text: "x".repeat(50000) },
      budgetChars: 100,
    });
    expect(snap.truncated.some((t) => t.includes("selection capped"))).toBe(true);
    expect(snap.withinBudget).toBe(false);
  });

  it("keeps artifact refs metadata-only", () => {
    const snap = assembleContext({ ...base, artifactRefs: ["art1"] });
    expect(snap.t5).toEqual(["Artifact refs (metadata only): art1"]);
  });
});
