// Command Center scale measurements (Wave 10 §31): intent classification
// over 1k diverse requests, plan builds, and identifier extraction. No
// model calls; node-side derivation only (conversation history is bounded
// at 20 refs-only entries, so DOM cost stays flat by construction).
import { describe, expect, it } from "vitest";

import { assembleContext } from "../context/assemble";
import { classifyIntent, type ClassifyContext } from "./classify";
import { planFor } from "./plan";
import { extractIdentifiers } from "./queries";

const REQUESTS = [
  "Implement OAuth login with tests",
  "Fix this failing test",
  "Explain this function",
  "Where is validate_token used?",
  "Run the tests",
  "Review requirement coverage",
  "Pause it",
  "What is the current best practice for caching?",
  "How many tokens have we spent?",
  "Open the execution graph",
];

const CTX: ClassifyContext = {
  projectId: "p",
  requirementId: "r1",
  taskId: "t1",
  agentId: "a1",
  filePath: "auth.py",
  selectionChars: 400,
  selectionLines: 12,
  hasFailedTask: true,
  hasFailureOutput: true,
};

describe("command center at scale", () => {
  it("classifies, plans, and assembles 1k requests within budget", () => {
    const started = Date.now();
    let gated = 0;
    for (let i = 0; i < 100; i++) {
      for (const text of REQUESTS) {
        const intent = classifyIntent(`${text} ${i}`, CTX);
        planFor(intent);
        if (intent.confirmationRequired) gated += 1;
        extractIdentifiers(text);
        assembleContext({
          actionLabel: "benchmark",
          scopeLabel: "auth.py",
          safetyNote: null,
          entityLines: [],
          requirementLine: null,
          filePath: "auth.py",
          fileContent: "x = 1\n".repeat(500),
          selection: { startLine: 1, endLine: 12, text: "x".repeat(400) },
          symbols: [{ name: "authenticate", kind: "function", line: 1 }],
          relatedTests: [],
          executionLines: [],
          agentLines: [],
          dependencyLines: [],
          recentEvents: [],
          attemptLines: [],
          artifactRefs: [],
        });
      }
    }
    const elapsedMs = Date.now() - started;
    console.log(JSON.stringify({
      benchmark: "wave10-command-center",
      requests: 1000,
      gated,
      elapsedMs,
    }));
    expect(gated).toBeGreaterThan(0);
    expect(elapsedMs).toBeLessThan(5000);
  });
});
