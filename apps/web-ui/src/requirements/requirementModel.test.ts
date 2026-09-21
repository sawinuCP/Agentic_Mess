// Unit tests for requirement trust derivations (pure logic, node).
import { describe, expect, it } from "vitest";

import {
  attemptSummary,
  evidenceCandidates,
  involvedAgents,
  missingForVerification,
  normalizeStatus,
  touchedFiles,
  workState,
} from "./requirementModel";
import type { TaskInfo, TraceabilityRequirement } from "../types";

const req = (over: Partial<TraceabilityRequirement> = {}): TraceabilityRequirement => ({
  id: "r", title: "Payroll endpoint", priority: "must", status: "UNKNOWN",
  implemented: true, task_ids: ["t1"], criteria: [], evidence_artifact_ids: [],
  validation_evidence_artifact_ids: [],
  ...over,
});

const task = (id: string, status: string, evidence: string[] = [], agent: string | null = null): TaskInfo => ({
  id, project_id: "p", requirement_id: "r", title: id, request: "", status,
  priority: 1, depends_on: [],
  attempts: evidence.length > 0 || agent
    ? [{ attempt_number: 1, agent_id: agent, outcome: evidence.length > 0 ? "success" : null, failure_class: null, failure_detail: null, evidence_artifact_ids: evidence }]
    : [],
});

describe("normalizeStatus", () => {
  it("passes backend states through, casing-insensitive", () => {
    expect(normalizeStatus("VERIFIED")).toBe("VERIFIED");
    expect(normalizeStatus("verified")).toBe("VERIFIED");
    expect(normalizeStatus("FAILED")).toBe("FAILED");
    expect(normalizeStatus("UNKNOWN")).toBe("UNKNOWN");
    expect(normalizeStatus("open")).toBe("UNKNOWN");
    expect(normalizeStatus("")).toBe("UNKNOWN");
  });
});

describe("workState", () => {
  it("derives progress without inventing verification", () => {
    expect(workState([]).label).toBe("No tasks linked");
    const state = workState([task("a", "completed"), task("b", "running"), task("c", "blocked")]);
    expect(state).toMatchObject({ total: 3, done: 1, blocked: 1, running: true });
    expect(state.label).toContain("1/3 tasks complete");
  });
});

describe("evidenceCandidates", () => {
  it("collects recorded artifacts, deduped, task-scoped", () => {
    const out = evidenceCandidates(
      req({ task_ids: ["t1", "t2"], validation_evidence_artifact_ids: ["v1"] }),
      [task("t1", "completed", ["a1"], "ag1"), task("t2", "running", ["a1"], "ag1"), task("t9", "completed", ["zz"], "ag1")],
    );
    expect(out.map((c) => c.artifactId).sort()).toEqual(["a1", "v1"]);
    expect(out.find((c) => c.artifactId === "a1")?.taskTitle).toBe("t1");
  });
});

describe("missingForVerification", () => {
  it("names unimplemented, unverified, and evidence-less states", () => {
    expect(missingForVerification(req({ implemented: false, task_ids: [] }), [])[0]).toContain("No linked tasks");
    const missing = missingForVerification(
      req({ criteria: [{ id: "c", description: "auth required", kind: "automated_test", mandatory: true, state: "unknown" }] }),
      [task("t1", "completed")],
    );
    expect(missing.join(" ")).toContain("auth required");
    expect(missing.join(" ")).toContain("No recorded evidence");
  });
});

describe("involvedAgents + touchedFiles + attemptSummary", () => {
  it("resolves agents, files, and outcomes from recorded state", () => {
    const agents = [{ id: "ag1", project_id: "p", name: "Backend", role: "worker", model: null, capabilities: [], state: "running" }];
    expect(involvedAgents(req(), [task("t1", "completed", [], "ag1")], agents)).toEqual([
      { id: "ag1", name: "Backend", state: "running" },
    ]);
    expect(touchedFiles(req(), [
      { id: "e", occurred_at: "", event_type: "TOOL_RUN_COMPLETED", source: null, project_id: "p", task_id: "t1", agent_id: "ag1", payload: { path: "a.py" } },
    ])).toEqual(["a.py"]);
    expect(attemptSummary([task("t1", "completed", ["a"], "ag1")])).toMatchObject({ success: 1, total: 1 });
  });
});
