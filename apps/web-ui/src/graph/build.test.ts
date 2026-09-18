// Unit tests for the Execution Graph data layer (pure logic, node env).
import { describe, expect, it } from "vitest";

import type {
  AgentInfo,
  EventEntry,
  TaskInfo,
  TraceabilityRequirement,
  WorktreeInfo,
} from "../types";
import {
  buildGraph,
  coverageCounts,
  emptyFilter,
  failureTrace,
  filterGraph,
  layoutGraph,
  parseMergeCommit,
  textTree,
  type GraphInputs,
} from "./build";

function task(overrides: Partial<TaskInfo> = {}): TaskInfo {
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

function requirement(overrides: Partial<TraceabilityRequirement> = {}): TraceabilityRequirement {
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

function agent(overrides: Partial<AgentInfo> = {}): AgentInfo {
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

function event(overrides: Partial<EventEntry> = {}): EventEntry {
  return {
    id: "e1",
    occurred_at: "2026-09-18T10:00:00.000Z",
    event_type: "TOOL_RUN_COMPLETED",
    source: null,
    project_id: "p",
    task_id: null,
    agent_id: null,
    payload: {},
    ...overrides,
  };
}

function inputs(overrides: Partial<GraphInputs> = {}): GraphInputs {
  return {
    report: {
      requirements: [requirement()],
      coverage: { total: 1, verified: 0, failed: 0, unknown: 1 },
      generatedAt: "2026-09-18T10:00:00Z",
    },
    rawRequirements: [],
    tasks: [task()],
    agents: [agent()],
    events: [],
    worktrees: [] as WorktreeInfo[],
    ...overrides,
  };
}

describe("parseMergeCommit", () => {
  it("parses deterministic integration messages only", () => {
    expect(parseMergeCommit("Integrate agent/task-1 (worktree abc12345)")).toEqual({
      branch: "agent/task-1",
      worktreeId: "abc12345",
    });
    expect(parseMergeCommit("Fix a bug")).toBeNull();
    expect(parseMergeCommit("Integrate branch without id")).toBeNull();
    expect(parseMergeCommit(null)).toBeNull();
  });
});

describe("buildGraph", () => {
  it("builds requirement→task→agent edges from persisted links", () => {
    const g = buildGraph(inputs({
      tasks: [task({ attempts: [{ attempt_number: 1, agent_id: "a1", outcome: null, evidence_artifact_ids: [], failure_class: null, failure_detail: null }] })],
    }));
    const ids = new Set(g.nodes.map((n) => n.id));
    expect(ids.has("req:r1")).toBe(true);
    expect(ids.has("task:t1")).toBe(true);
    expect(ids.has("agent:a1")).toBe(true);
    const edgeKinds = new Set(g.edges.map((e) => `${e.source}|${e.target}|${e.type}`));
    expect(edgeKinds.has("req:r1|task:t1|planned for")).toBe(true);
    expect(edgeKinds.has("task:t1|agent:a1|executed by")).toBe(true);
  });

  it("uses overseer status, never task completion, for requirements", () => {
    const g = buildGraph(inputs({
      report: {
        requirements: [requirement({ status: "UNKNOWN" })],
        coverage: { total: 1, verified: 0, failed: 0, unknown: 1 },
        generatedAt: "",
      },
      tasks: [task({ status: "completed" })],
    }));
    const req = g.nodes.find((n) => n.type === "requirement");
    expect(req?.status).toBe("UNKNOWN");
    expect(req?.tone).toBe("warn");
  });

  it("links commits to tasks only on deterministic merge messages", () => {
    const worktrees: WorktreeInfo[] = [{
      id: "abcdef12", project_id: "p", task_id: "t1", branch: "agent/task-1",
      path: "/tmp", status: "merged", integration_status: "merged",
      integration_position: null, created_at: "",
    }];
    const g = buildGraph(inputs({
      worktrees,
      events: [
        event({ id: "c1", event_type: "GIT_COMMIT", payload: { message: "Integrate agent/task-1 (worktree abcdef12)", paths: ["a.py"] } }),
        event({ id: "c2", event_type: "GIT_COMMIT", payload: { message: "WIP stuff", paths: ["b.py"] } }),
      ],
    }));
    const derived = g.edges.filter((e) => e.type === "integrated as");
    expect(derived).toHaveLength(1);
    expect(derived[0].derived).toBe(true);
    expect(derived[0].source).toBe("task:t1");
    // Both commits still attach their files honestly.
    expect(g.edges.filter((e) => e.type === "changed")).toHaveLength(2);
  });

  it("creates test nodes with evidence and file edges from tool runs", () => {
    const g = buildGraph(inputs({
      events: [event({
        id: "t9", payload: { tool: "test", exit_code: 1, duration_ms: 40, path: "tests/a.py", artifact_ids: ["art1"] },
      })],
    }));
    const test = g.nodes.find((n) => n.type === "test");
    expect(test?.status).toBe("failed");
    expect(test?.tone).toBe("down");
    expect(g.edges.some((e) => e.type === "produced" && e.source === test?.id)).toBe(true);
    expect(g.edges.some((e) => e.type === "targeted" && e.source === test?.id)).toBe(true);
    // Non-test tools never become test nodes.
    const g2 = buildGraph(inputs({
      events: [event({ id: "x", payload: { tool: "run", exit_code: 0, path: "a.py" } })],
    }));
    expect(g2.nodes.some((n) => n.type === "test")).toBe(false);
  });

  it("bounds files and evidence with honest counts", () => {
    const paths = Array.from({ length: 200 }, (_, i) => `f${i}.py`);
    const g = buildGraph(inputs({
      events: paths.map((p, i) => event({ id: `c${i}`, event_type: "GIT_COMMIT", payload: { message: "x", paths: [p] } })),
    }));
    expect(g.nodes.filter((n) => n.type === "file")).toHaveLength(150);
    expect(g.hiddenFiles).toBe(50);
  });

  it("is idempotent under duplicate events", () => {
    const ev = event({ id: "c1", event_type: "GIT_COMMIT", payload: { message: "x", paths: ["a.py"] } });
    const once = buildGraph(inputs({ events: [ev] }));
    const twice = buildGraph(inputs({ events: [ev, { ...ev }] }));
    expect(twice.nodes).toHaveLength(once.nodes.length);
    expect(twice.edges).toHaveLength(once.edges.length);
  });
});

describe("filterGraph", () => {
  const g = buildGraph(inputs({
    tasks: [
      task({ id: "t1", title: "One", status: "running" }),
      task({ id: "t2", title: "Two", status: "failed", attempts: [{ attempt_number: 1, agent_id: "a1", outcome: "failed", evidence_artifact_ids: [], failure_class: "TOOL_FAILURE", failure_detail: null }] }),
    ],
    events: [event({ id: "f1", event_type: "GIT_COMMIT", payload: { message: "x", paths: ["unrelated.py"] } })],
  }));

  it("filters by type with neighbor closure", () => {
    const out = filterGraph(g, { ...emptyFilter(), types: new Set(["task"]) });
    expect(out.nodes.every((n) => n.type === "task" || n.type === "requirement" || n.type === "agent")).toBe(true);
    // The unrelated file lane is hidden with disclosure.
    expect(out.hidden).toBeGreaterThan(0);
  });

  it("failures mode keeps failures plus judging requirements", () => {
    const out = filterGraph(g, { ...emptyFilter(), failuresOnly: true });
    const ids = new Set(out.nodes.map((n) => n.id));
    expect(ids.has("task:t2")).toBe(true);
    expect(ids.has("req:r1")).toBe(true);
    expect(ids.has("task:t1")).toBe(true); // neighbor closure: requirement context stays intact
    expect(out.nodes.some((n) => n.type === "file")).toBe(false);
  });

  it("search matches labels with context", () => {
    const out = filterGraph(g, { ...emptyFilter(), query: "backend" });
    expect(out.nodes.some((n) => n.id === "agent:a1")).toBe(true);
  });
});

describe("coverageCounts", () => {
  it("counts requirements, criteria, and tasks from real state", () => {
    const counts = coverageCounts(
      [requirement({ status: "VERIFIED", criteria: [{ id: "c", description: "x", kind: "manual", mandatory: true, state: "verified" }] }), requirement({ id: "r2", status: "UNKNOWN" })],
      [task({ status: "completed" }), task({ id: "t2", status: "failed" })],
    );
    expect(counts.requirements).toEqual({ total: 2, verified: 1, failed: 0, unknown: 1 });
    expect(counts.criteria).toEqual({ total: 1, verified: 1, failed: 0, unknown: 0 });
    expect(counts.tasks.completed).toBe(1);
    expect(counts.tasks.failed).toBe(1);
  });
});

describe("failureTrace", () => {
  it("answers the failure questions from recorded state", () => {
    const failed = task({
      status: "failed",
      attempts: [
        { attempt_number: 1, agent_id: "a1", outcome: "failed", evidence_artifact_ids: [], failure_class: "TOOL_FAILURE", failure_detail: "exit 1" },
        { attempt_number: 2, agent_id: "a1", outcome: "failed", evidence_artifact_ids: [], failure_class: "TOOL_FAILURE", failure_detail: null },
      ],
    });
    const { steps, requirementBlocked, requirementId } = failureTrace(
      failed, [agent()],
      [event({ id: "r", event_type: "RECOVERY_SELECTED", task_id: "t1", payload: { action: "retry_if_safe" } })],
      [requirement({ status: "UNKNOWN" })],
    );
    const labels = steps.map((s) => s.label);
    const text = steps.map((s) => `${s.label} ${s.detail ?? ""}`);
    expect(labels[0]).toContain("Requirement");
    expect(text.some((l) => l.includes("TOOL_FAILURE"))).toBe(true);
    expect(labels.some((l) => l.includes("Agent: Backend"))).toBe(true);
    expect(labels.some((l) => l.includes("Recovery decision: retry_if_safe"))).toBe(true);
    expect(labels.some((l) => l.includes("Retried with 1 further attempt"))).toBe(true);
    expect(requirementBlocked).toBe(true);
    expect(requirementId).toBe("r1");
  });
});

describe("textTree", () => {
  it("renders the requirement chain without geometry", () => {
    const g = buildGraph(inputs({
      tasks: [task({ attempts: [{ attempt_number: 1, agent_id: "a1", outcome: null, evidence_artifact_ids: ["art1"], failure_class: null, failure_detail: null }] })],
    }));
    const tree = textTree("r1", g, g.nodes.length ? [task({ attempts: [{ attempt_number: 1, agent_id: "a1", outcome: null, evidence_artifact_ids: ["art1"], failure_class: null, failure_detail: null }] })] : []);
    expect(tree?.label).toBe("Requirement: Auth");
    expect(tree?.children[0].label).toBe("Task: Build auth");
    expect(tree?.children[0].children.some((c) => c.label === "Agent: Backend")).toBe(true);
    expect(tree?.children[0].children.some((c) => c.label === "Evidence: art1")).toBe(true);
  });

  it("returns null for unknown requirements", () => {
    expect(textTree("nope", buildGraph(inputs()), [])).toBeNull();
  });
});

describe("layoutGraph", () => {
  it("columns requirements, task depths, agents, and lanes deterministically", () => {
    const g = buildGraph(inputs({
      tasks: [
        task({ id: "t1", title: "One", status: "running", attempts: [{ attempt_number: 1, agent_id: "a1", outcome: null, evidence_artifact_ids: [], failure_class: null, failure_detail: null }] }),
        task({ id: "t2", title: "Two", status: "blocked", depends_on: ["t1"] }),
      ],
    }));
    const pos = layoutGraph(g.nodes);
    expect(pos.get("req:r1")?.x).toBe(0);
    expect(pos.get("task:t1")?.x).toBe(1);
    expect(pos.get("task:t2")?.x).toBe(2);
    expect(pos.get("agent:a1")?.x).toBe(3);
    // Deterministic across runs.
    expect(layoutGraph(g.nodes).get("task:t2")).toEqual(pos.get("task:t2"));
  });

  it("reports pixel dimensions covering every column", async () => {    const { graphDimensions: dims } = await import("./build");
    const g = buildGraph(inputs({
      tasks: [
        task({ id: "t1", title: "One", status: "running" }),
        task({ id: "t2", title: "Two", status: "blocked", depends_on: ["t1"] }),
      ],
    }));
    const pos = layoutGraph(g.nodes);
    const { width } = dims(pos);
    // 4 columns (req/task/task/agent) must fit: width is pixels, not indices.
    expect(width).toBeGreaterThan(3 * 168);
  });
});

describe("graph build at scale", () => {
  it("builds, filters, and lays out 500 tasks within budget", () => {
    const bigTasks = Array.from({ length: 500 }, (_, i) =>
      task({
        id: `t${i}`,
        title: `Task ${i}`,
        status: ["pending", "running", "completed", "failed"][i % 4],
        requirement_id: i % 10 === 0 ? null : "r1",
        depends_on: i > 0 ? [`t${i - 1}`] : [],
        attempts: i % 3 === 0
          ? [{ attempt_number: 1, agent_id: "a1", outcome: "success", evidence_artifact_ids: [`art${i}`], failure_class: null, failure_detail: null }]
          : [],
      }),
    );
    const bigEvents = Array.from({ length: 120 }, (_, i) =>
      event({
        id: `ge${i}`,
        event_type: i % 2 === 0 ? "TOOL_RUN_COMPLETED" : "GIT_COMMIT",
        payload: i % 2 === 0
          ? { tool: "test", exit_code: 0, duration_ms: 10, path: `f${i}.py`, artifact_ids: [] }
          : { message: `commit ${i}`, paths: [`f${i}.py`] },
      }),
    );
    const started = Date.now();
    const g = buildGraph(inputs({ tasks: bigTasks, events: bigEvents }));
    const filtered = filterGraph(g, { ...emptyFilter(), failuresOnly: true });
    const pos = layoutGraph(filtered.nodes);
    const elapsedMs = Date.now() - started;
    console.log(JSON.stringify({
      benchmark: "wave8-graph",
      tasks: bigTasks.length,
      events: bigEvents.length,
      nodes: g.nodes.length,
      edges: g.edges.length,
      filteredNodes: filtered.nodes.length,
      elapsedMs,
    }));
    expect(g.nodes.length).toBeGreaterThan(500);
    expect(filtered.nodes.length).toBeLessThan(g.nodes.length);
    expect(pos.size).toBe(filtered.nodes.length);
    expect(elapsedMs).toBeLessThan(5000);
  });
});
