// Shared graph test fixtures (typed domain rows; mirrors build.test.ts).
import type { AgentInfo, TaskInfo, TraceabilityRequirement } from "../types";

export function task(overrides: Partial<TaskInfo> = {}): TaskInfo {
  return {
    id: "t1",
    project_id: "p",
    requirement_id: "r1",
    title: "Build auth",
    request: "",
    status: "pending",
    priority: 1,
    depends_on: [],
    attempts: [],
    ...overrides,
  };
}

export function requirement(overrides: Partial<TraceabilityRequirement> = {}): TraceabilityRequirement {
  return {
    id: "r1",
    title: "Auth",
    priority: "must",
    status: "UNKNOWN",
    implemented: true,
    task_ids: ["t1"],
    criteria: [],
    evidence_artifact_ids: [],
    validation_evidence_artifact_ids: [],
    ...overrides,
  };
}

export function agent(overrides: Partial<AgentInfo> = {}): AgentInfo {
  return {
    id: "a1",
    project_id: "p",
    name: "Backend",
    role: "backend",
    model: null,
    capabilities: [],
    state: "running",
    ...overrides,
  };
}
