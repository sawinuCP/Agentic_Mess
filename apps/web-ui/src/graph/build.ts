// Execution Graph data layer (Wave 8): pure projection over durable state.
//
// Builds nodes/edges ONLY from persisted or event-recorded relationships
// (see docs/execution-graph-architecture.md §2). Derived edges are flagged
// `derived: true` and never guessed: unparseable merge messages simply yield
// no edge. No React, no fetch — unit-testable in node Vitest.

import type {
  AgentInfo,
  EventEntry,
  RequirementInfo,
  TaskInfo,
  TraceabilityRequirement,
  WorktreeInfo,
} from "../types";

export type GraphNodeType =
  | "requirement"
  | "task"
  | "agent"
  | "file"
  | "commit"
  | "test"
  | "evidence";

export type GraphTone = "ok" | "warn" | "down" | "muted";

export interface GraphNode {
  id: string;
  type: GraphNodeType;
  label: string;
  status: string;
  tone: GraphTone;
  requirementId: string | null;
  taskId: string | null;
  agentId: string | null;
  metadata: Record<string, unknown>;
  x?: number;
  y?: number;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  type: string;
  derived?: boolean;
}

export interface BuiltGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
  hiddenFiles: number;
  hiddenEvidence: number;
}

export interface GraphInputs {
  report: {
    requirements: TraceabilityRequirement[];
    coverage: { total: number; verified: number; failed: number; unknown: number };
    generatedAt: string;
  } | null;
  rawRequirements: RequirementInfo[];
  tasks: TaskInfo[];
  agents: AgentInfo[];
  events: EventEntry[];
  worktrees: WorktreeInfo[];
}

export const MAX_FILE_NODES = 150;
export const MAX_EVIDENCE_NODES = 200;

const TASK_TONE: Record<string, GraphTone> = {
  running: "ok",
  completed: "ok",
  verified: "ok",
  waiting: "warn",
  blocked: "warn",
  paused: "warn",
  pending: "warn",
  recovering: "warn",
  resuming: "warn",
  verifying: "warn",
  failed: "down",
  cancelled: "muted",
};

const REQ_TONE: Record<string, GraphTone> = {
  VERIFIED: "ok",
  FAILED: "down",
  UNKNOWN: "warn",
};

function shortId(id: string): string {
  return id.length > 8 ? id.slice(0, 8) : id;
}

function asStrings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
}

/** Parse deterministic integration merge messages: "Integrate {branch} (worktree {id})". */
export function parseMergeCommit(message: unknown): { branch: string; worktreeId: string } | null {
  if (typeof message !== "string") return null;
  const match = /^Integrate (\S+) \(worktree ([0-9a-f-]{8,})\)\s*$/.exec(message.trim());
  if (!match) return null;
  return { branch: match[1], worktreeId: match[2] };
}

export function buildGraph(inputs: GraphInputs): BuiltGraph {
  const { report, rawRequirements, tasks, agents, events, worktrees } = inputs;
  const nodes: GraphNode[] = [];
  const edges: GraphEdge[] = [];
  // Duplicate deliveries must never duplicate nodes: fold on event id first.
  const seenEventIds = new Set<string>();
  const uniqueEvents = events.filter((e) => {
    if (seenEventIds.has(e.id)) return false;
    seenEventIds.add(e.id);
    return true;
  });
  const rawById = new Map(rawRequirements.map((r) => [r.id, r]));
  const reqIds = new Set((report?.requirements ?? []).map((r) => r.id));
  const worktreeByTask = new Map<string, WorktreeInfo>();
  for (const w of worktrees) {
    if (w.task_id && !worktreeByTask.has(w.task_id)) worktreeByTask.set(w.task_id, w);
  }

  for (const req of report?.requirements ?? []) {
    const raw = rawById.get(req.id);
    const criteria = req.criteria ?? [];
    nodes.push({
      id: `req:${req.id}`,
      type: "requirement",
      label: req.title,
      status: req.status,
      tone: REQ_TONE[req.status] ?? "muted",
      requirementId: req.id,
      taskId: null,
      agentId: null,
      metadata: {
        priority: req.priority,
        description: raw?.description ?? null,
        desiredOutcome: raw?.desired_outcome ?? null,
        taskIds: req.task_ids,
        criteria: criteria.map((c) => ({
          id: c.id,
          description: c.description,
          kind: c.kind,
          mandatory: c.mandatory,
          state: c.state,
        })),
        criteriaTotal: criteria.length,
        criteriaVerified: criteria.filter((c) => c.state === "verified").length,
        criteriaFailed: criteria.filter((c) => c.state === "failed").length,
        criteriaUnknown: criteria.filter((c) => c.state !== "verified" && c.state !== "failed").length,
        implemented: req.implemented,
      },
    });
  }

  const taskById = new Map(tasks.map((t) => [t.id, t]));
  for (const task of tasks) {
    const evidence = [...new Set(task.attempts.flatMap((a) => a.evidence_artifact_ids))];
    const failures = task.attempts
      .filter((a) => a.outcome !== null && a.outcome !== "success")
      .map((a) => a.failure_class ?? a.outcome ?? "failed");
    const worktree = worktreeByTask.get(task.id);
    nodes.push({
      id: `task:${task.id}`,
      type: "task",
      label: task.title,
      status: task.status,
      tone: TASK_TONE[task.status] ?? "muted",
      requirementId: task.requirement_id,
      taskId: task.id,
      agentId: null,
      metadata: {
        priority: task.priority,
        requirementLinked: task.requirement_id !== null && reqIds.has(task.requirement_id ?? ""),
        dependsOn: task.depends_on.filter((d) => taskById.has(d)),
        failureClasses: [...new Set(failures)],
        evidenceCount: evidence.length,
        attemptCount: task.attempts.length,
        worktreeBranch: worktree?.branch ?? null,
        worktreeStatus: worktree?.integration_status ?? null,
      },
    });
    if (task.requirement_id && reqIds.has(task.requirement_id)) {
      edges.push({
        id: `edge:req-task:${task.id}`,
        source: `req:${task.requirement_id}`,
        target: `task:${task.id}`,
        type: "planned for",
      });
    }
    for (const dep of task.depends_on) {
      if (taskById.has(dep)) {
        edges.push({
          id: `edge:dep:${dep}->${task.id}`,
          source: `task:${dep}`,
          target: `task:${task.id}`,
          type: "depends on",
        });
      }
    }
  }

  const agentById = new Map(agents.map((a) => [a.id, a]));
  for (const agent of agents) {
    nodes.push({
      id: `agent:${agent.id}`,
      type: "agent",
      label: agent.name,
      status: agent.state,
      tone: TASK_TONE[agent.state] ?? "muted",
      requirementId: null,
      taskId: null,
      agentId: agent.id,
      metadata: { role: agent.role, model: agent.model },
    });
  }
  for (const task of tasks) {
    const owners = [...new Set(task.attempts.map((a) => a.agent_id).filter(Boolean))] as string[];
    for (const owner of owners) {
      if (agentById.has(owner)) {
        edges.push({
          id: `edge:exec:${task.id}:${owner}`,
          source: `task:${task.id}`,
          target: `agent:${owner}`,
          type: "executed by",
        });
      }
    }
  }

  // Evidence: union of attempt evidence (task-linked), report lists
  // (requirement-linked), and tool-run outputs (test-linked).
  const evidenceLinks = new Map<string, { tasks: Set<string>; requirements: Set<string>; tests: Set<string> }>();
  const linkEvidence = (id: string, kind: "tasks" | "requirements" | "tests", ref: string): void => {
    let entry = evidenceLinks.get(id);
    if (!entry) {
      entry = { tasks: new Set(), requirements: new Set(), tests: new Set() };
      evidenceLinks.set(id, entry);
    }
    entry[kind].add(ref);
  };
  for (const task of tasks) {
    for (const id of new Set(task.attempts.flatMap((a) => a.evidence_artifact_ids))) {
      linkEvidence(id, "tasks", task.id);
    }
  }
  for (const req of report?.requirements ?? []) {
    for (const id of [...(req.evidence_artifact_ids ?? []), ...(req.validation_evidence_artifact_ids ?? [])]) {
      linkEvidence(id, "requirements", req.id);
    }
  }

  // Tests + files + commits from the bounded event feed.
  const files = new Map<string, { tests: Set<string>; commits: Set<string> }>();
  const linkFile = (path: string, kind: "tests" | "commits", ref: string): void => {
    let entry = files.get(path);
    if (!entry) {
      entry = { tests: new Set(), commits: new Set() };
      files.set(path, entry);
    }
    entry[kind].add(ref);
  };
  const TEST_TOOLS = new Set(["test", "lint", "build"]);
  for (const event of uniqueEvents) {
    if (event.event_type === "TOOL_RUN_COMPLETED" && typeof event.payload.tool === "string" && TEST_TOOLS.has(event.payload.tool)) {
      const exit = event.payload.exit_code;
      const nodeId = `test:${event.id}`;
      const toolPath = typeof event.payload.path === "string" ? event.payload.path : null;
      nodes.push({
        id: nodeId,
        type: "test",
        label: `${String(event.payload.tool)}${typeof event.payload.path === "string" ? ` ${event.payload.path.split("/").pop()}` : ""}`,
        status: exit === 0 ? "passed" : exit === null || exit === undefined ? "unknown" : "failed",
        tone: exit === 0 ? "ok" : exit === null || exit === undefined ? "muted" : "down",
        requirementId: null,
        taskId: typeof event.task_id === "string" ? event.task_id : null,
        agentId: typeof event.agent_id === "string" ? event.agent_id : null,
        metadata: {
          tool: event.payload.tool,
          exitCode: exit ?? null,
          durationMs: event.payload.duration_ms ?? null,
          path: toolPath,
          occurredAt: event.occurred_at,
        },
      });
      if (toolPath) linkFile(toolPath, "tests", nodeId);
      for (const id of asStrings(event.payload.artifact_ids)) linkEvidence(id, "tests", nodeId);
    }
    if (event.event_type === "GIT_COMMIT") {
      const message = typeof event.payload.message === "string" ? event.payload.message : "";
      const firstLine = message.split("\n")[0].slice(0, 80) || "commit";
      const nodeId = `commit:${event.id}`;
      const parsed = parseMergeCommit(message);
      const worktreeTask = parsed
        ? worktrees.find((w) => w.id === parsed.worktreeId || w.id.startsWith(parsed.worktreeId))?.task_id ?? null
        : null;
      nodes.push({
        id: nodeId,
        type: "commit",
        label: firstLine,
        status: parsed ? "integration" : "commit",
        tone: "muted",
        requirementId: null,
        taskId: worktreeTask,
        agentId: typeof event.agent_id === "string" ? event.agent_id : null,
        metadata: {
          message,
          paths: asStrings(event.payload.paths),
          occurredAt: event.occurred_at,
          mergeBranch: parsed?.branch ?? null,
          derivedTaskLink: worktreeTask !== null,
        },
      });
      for (const path of asStrings(event.payload.paths)) linkFile(path, "commits", nodeId);
      if (worktreeTask && taskById.has(worktreeTask)) {
        edges.push({
          id: `edge:commit-task:${event.id}`,
          source: `task:${worktreeTask}`,
          target: nodeId,
          type: "integrated as",
          derived: true,
        });
      }
    }
  }

  let hiddenFiles = 0;
  for (const [path, entry] of files) {
    if (nodes.filter((n) => n.type === "file").length >= MAX_FILE_NODES) {
      hiddenFiles += 1;
      continue;
    }
    const nodeId = `file:${path}`;
    nodes.push({
      id: nodeId,
      type: "file",
      label: path.split("/").pop() ?? path,
      status: "recorded",
      tone: "muted",
      requirementId: null,
      taskId: null,
      agentId: null,
      metadata: { path },
    });
    for (const test of entry.tests) {
      edges.push({ id: `edge:test-file:${test}:${path}`, source: test, target: nodeId, type: "targeted" });
    }
    for (const commit of entry.commits) {
      edges.push({ id: `edge:commit-file:${commit}:${path}`, source: commit, target: nodeId, type: "changed" });
    }
  }

  let hiddenEvidence = 0;
  for (const [id, entry] of evidenceLinks) {
    if (nodes.filter((n) => n.type === "evidence").length >= MAX_EVIDENCE_NODES) {
      hiddenEvidence += 1;
      continue;
    }
    const nodeId = `ev:${id}`;
    nodes.push({
      id: nodeId,
      type: "evidence",
      label: shortId(id),
      status: "recorded",
      tone: "muted",
      requirementId: null,
      taskId: null,
      agentId: null,
      metadata: { artifactId: id },
    });
    for (const taskId of entry.tasks) {
      if (taskById.has(taskId)) {
        edges.push({ id: `edge:task-ev:${taskId}:${id}`, source: `task:${taskId}`, target: nodeId, type: "evidence recorded" });
      }
    }
    for (const reqId of entry.requirements) {
      if (reqIds.has(reqId)) {
        edges.push({ id: `edge:req-ev:${reqId}:${id}`, source: nodeId, target: `req:${reqId}`, type: "verifies" });
      }
    }
    for (const test of entry.tests) {
      edges.push({ id: `edge:test-ev:${test}:${id}`, source: test, target: nodeId, type: "produced" });
    }
  }

  const seenEdgeIds = new Set<string>();
  const uniqueEdges = edges.filter((e) => {
    if (seenEdgeIds.has(e.id)) return false;
    seenEdgeIds.add(e.id);
    return true;
  });
  return { nodes, edges: uniqueEdges, hiddenFiles, hiddenEvidence };
}

// --- filtering ---------------------------------------------------------------

export interface GraphFilter {
  types: Set<GraphNodeType> | null;
  statuses: Set<string> | null;
  focusRequirementId: string | null;
  focusTaskId: string | null;
  focusAgentId: string | null;
  failuresOnly: boolean;
  query: string;
}

export const emptyFilter = (): GraphFilter => ({
  types: null,
  statuses: null,
  focusRequirementId: null,
  focusTaskId: null,
  focusAgentId: null,
  failuresOnly: false,
  query: "",
});

function neighborsOf(id: string, edges: GraphEdge[]): Set<string> {
  const out = new Set<string>();
  for (const e of edges) {
    if (e.source === id) out.add(e.target);
    if (e.target === id) out.add(e.source);
  }
  return out;
}

/**
 * Filter nodes; edges survive only with both endpoints visible. A 1-hop
 * neighbor closure around matches preserves context so filtering cannot
 * manufacture disconnected edges. Returns the hidden count for disclosure.
 */
export function filterGraph(graph: BuiltGraph, filter: GraphFilter): {
  nodes: GraphNode[];
  edges: GraphEdge[];
  hidden: number;
} {
  const q = filter.query.trim().toLowerCase();
  // Hard filters (type/status) hide nodes outright. Scope, failures, and
  // search are focus lenses: matches keep their 1-hop neighborhood so
  // filtering cannot manufacture disconnected edges.
  const hardMatch = (n: GraphNode): boolean => {
    if (filter.types && !filter.types.has(n.type)) return false;
    if (filter.statuses && !filter.statuses.has(n.status)) return false;
    return true;
  };
  const match = (n: GraphNode): boolean => {
    if (!hardMatch(n)) return false;
    if (filter.failuresOnly && n.tone !== "down" && n.type !== "requirement" && n.type !== "evidence") return false;
    if (filter.focusRequirementId && n.requirementId !== filter.focusRequirementId && n.id !== `req:${filter.focusRequirementId}`) {
      // Tasks/agents without the requirement link stay only via neighbor closure below.
      if (!(n.type === "agent" || (n.type === "task" && n.requirementId === null))) return false;
    }
    if (filter.focusTaskId && n.taskId !== filter.focusTaskId && n.id !== `task:${filter.focusTaskId}`) {
      if (n.type !== "agent") return false;
    }
    if (filter.focusAgentId && n.agentId !== filter.focusAgentId && n.id !== `agent:${filter.focusAgentId}`) {
      if (n.type !== "task") return false;
    }
    if (q && ![n.label, n.type, n.status].join(" ").toLowerCase().includes(q)) return false;
    return true;
  };
  const matched = new Set(graph.nodes.filter(match).map((n) => n.id));
  // 1-hop closure over hard-passing neighbors: matched nodes plus their
  // direct neighbors that survive the type/status filters.
  const visible = new Set(matched);
  for (const id of matched) {
    for (const neighbor of neighborsOf(id, graph.edges)) {
      const node = graph.nodes.find((n) => n.id === neighbor);
      if (node && hardMatch(node)) visible.add(neighbor);
    }
  }
  const nodes = graph.nodes.filter((n) => visible.has(n.id));
  const ids = new Set(nodes.map((n) => n.id));
  const edges = graph.edges.filter((e) => ids.has(e.source) && ids.has(e.target));
  return { nodes, edges, hidden: graph.nodes.length - nodes.length };
}

// --- coverage -----------------------------------------------------------------

export interface CoverageCounts {
  requirements: { total: number; verified: number; failed: number; unknown: number };
  criteria: { total: number; verified: number; failed: number; unknown: number };
  tasks: { total: number; completed: number; failed: number; blocked: number; running: number };
}

export function coverageCounts(
  requirements: TraceabilityRequirement[],
  tasks: TaskInfo[],
): CoverageCounts {
  const criteria = requirements.flatMap((r) => r.criteria ?? []);
  const stateOf = (s: string): "verified" | "failed" | "unknown" =>
    s === "verified" ? "verified" : s === "failed" ? "failed" : "unknown";
  return {
    requirements: {
      total: requirements.length,
      verified: requirements.filter((r) => r.status === "VERIFIED").length,
      failed: requirements.filter((r) => r.status === "FAILED").length,
      unknown: requirements.filter((r) => r.status !== "VERIFIED" && r.status !== "FAILED").length,
    },
    criteria: {
      total: criteria.length,
      verified: criteria.filter((c) => stateOf(c.state) === "verified").length,
      failed: criteria.filter((c) => stateOf(c.state) === "failed").length,
      unknown: criteria.filter((c) => stateOf(c.state) === "unknown").length,
    },
    tasks: {
      total: tasks.length,
      completed: tasks.filter((t) => t.status === "completed").length,
      failed: tasks.filter((t) => t.status === "failed").length,
      blocked: tasks.filter((t) => t.status === "blocked" || t.status === "waiting").length,
      running: tasks.filter((t) => t.status === "running").length,
    },
  };
}

// --- failure trace ------------------------------------------------------------

export interface FailureStep {
  nodeId: string;
  label: string;
  detail: string | null;
}

/**
 * The failure investigation path for one failed task, answering what failed,
 * what it affects, who hit it, what recovery ran, and whether the
 * requirement is still blocked — all from recorded state.
 */
export function failureTrace(
  task: TaskInfo,
  agents: AgentInfo[],
  events: EventEntry[],
  requirements: TraceabilityRequirement[],
): { steps: FailureStep[]; requirementBlocked: boolean; requirementId: string | null } {
  const steps: FailureStep[] = [];
  const nameOf = (id: string | null): string =>
    (id && agents.find((a) => a.id === id)?.name) ?? (id ? shortId(id) : "unassigned");
  const req = requirements.find((r) => r.id === task.requirement_id) ?? null;

  if (req) {
    steps.push({
      nodeId: `req:${req.id}`,
      label: `Requirement: ${req.title}`,
      detail: `status ${req.status} — task completion alone never verifies`,
    });
  }
  const failedAttempts = task.attempts.filter((a) => a.outcome !== null && a.outcome !== "success");
  steps.push({
    nodeId: `task:${task.id}`,
    label: `Task failed: ${task.title}`,
    detail: failedAttempts.length > 0
      ? failedAttempts.map((a) => `#${a.attempt_number} ${a.failure_class ?? a.outcome}`).join("; ")
      : task.status,
  });
  const owners = [...new Set(task.attempts.map((a) => a.agent_id).filter(Boolean))] as string[];
  for (const owner of owners) {
    steps.push({ nodeId: `agent:${owner}`, label: `Agent: ${nameOf(owner)}`, detail: "recorded on the failed attempts" });
  }
  const related = events
    .filter((e) => e.task_id === task.id)
    .sort((a, b) => Date.parse(a.occurred_at) - Date.parse(b.occurred_at));
  const recoveryKinds: Record<string, string> = {
    RECOVERY_SELECTED: "Recovery decision",
    RETRY_STARTED: "Retry started",
    AGENT_REPLACED: "Agent replaced",
    MODEL_SWITCHED: "Model switched",
    CONTEXT_COMPACTED: "Context compacted",
    DEBUGGER_SPAWNED: "Debugger spawned",
    DEPENDENCY_WAIT_STARTED: "Waited on dependency",
    DEPENDENCY_RESUMED: "Dependency resolved",
    TASK_TERMINALLY_FAILED: "Terminally failed",
  };
  for (const event of related) {
    const label = recoveryKinds[event.event_type];
    if (!label) continue;
    const action = typeof event.payload.action === "string" ? `: ${event.payload.action}` : "";
    steps.push({ nodeId: `task:${task.id}`, label: `${label}${action}`, detail: new Date(event.occurred_at).toLocaleString() });
  }
  const retried = failedAttempts.length > 0
    ? task.attempts.filter((a) => a.attempt_number > Math.min(...failedAttempts.map((f) => f.attempt_number)))
    : [];
  if (retried.length > 0) {
    steps.push({
      nodeId: `task:${task.id}`,
      label: `Retried with ${retried.length} further attempt${retried.length === 1 ? "" : "s"}`,
      detail: retried.map((a) => `#${a.attempt_number} ${a.outcome ?? "in progress"}`).join("; "),
    });
  }
  const laterSuccess = task.attempts.some((a) => a.outcome === "success");
  steps.push({
    nodeId: `task:${task.id}`,
    label: laterSuccess ? "Verified by a later successful attempt" : "No successful attempt recorded",
    detail: laterSuccess ? "see attempt outcomes" : "requirement stays blocked until recovery succeeds",
  });
  const requirementBlocked = req ? req.status !== "VERIFIED" : true;
  return { steps, requirementBlocked, requirementId: req?.id ?? null };
}

// --- accessible text tree ------------------------------------------------------

export interface TextNode {
  label: string;
  detail: string | null;
  nodeId: string | null;
  children: TextNode[];
}

/** Screen-reader-first rendering of one requirement's chain (no geometry). */
export function textTree(
  requirementId: string,
  graph: BuiltGraph,
  tasks: TaskInfo[],
): TextNode | null {
  const req = graph.nodes.find((n) => n.id === `req:${requirementId}`);
  if (!req) return null;
  const byId = new Map(graph.nodes.map((n) => [n.id, n]));
  const childrenOf = (id: string, type: string): GraphNode[] =>
    graph.edges.filter((e) => e.source === id && e.type === type).map((e) => byId.get(e.target)).filter((n): n is GraphNode => !!n);
  const taskNodes = childrenOf(req.id, "planned for");
  return {
    label: `Requirement: ${req.label}`,
    detail: `status ${req.status}`,
    nodeId: req.id,
    children: taskNodes.map((t) => {
      const task = tasks.find((x) => x.id === t.taskId);
      const agents = childrenOf(t.id, "executed by");
      const evidence = childrenOf(t.id, "evidence recorded");
      return {
        label: `Task: ${t.label}`,
        detail: `status ${t.status}`,
        nodeId: t.id,
        children: [
          ...agents.map((a) => ({ label: `Agent: ${a.label}`, detail: `state ${a.status}`, nodeId: a.id, children: [] })),
          ...evidence.map((e) => ({ label: `Evidence: ${e.label}`, detail: null, nodeId: e.id, children: [] })),
          ...(!task || task.depends_on.length === 0 ? [] : [{
            label: `Depends on: ${task.depends_on.map((d) => tasks.find((x) => x.id === d)?.title ?? shortId(d)).join(", ")}`,
            detail: null as string | null,
            nodeId: null as string | null,
            children: [] as TextNode[],
          }]),
        ],
      };
    }),
  };
}

// --- layout --------------------------------------------------------------------

export const GRAPH_NODE_W = 168;
export const GRAPH_NODE_H = 46;
export const GRAPH_GAP_X = 72;
const GRAPH_GAP_Y = 16;

/**
 * Column layout: requirements at x=0, tasks in dependency-depth columns,
 * agents after the deepest task, leaves (file/commit/test/evidence) in typed
 * lanes after agents. Deterministic; no force simulation, no library.
 */
export function layoutGraph(nodes: GraphNode[]): Map<string, { x: number; y: number }> {
  const positions = new Map<string, { x: number; y: number }>();
  const byType = new Map<GraphNodeType, GraphNode[]>();
  for (const n of nodes) {
    byType.set(n.type, [...(byType.get(n.type) ?? []), n]);
  }
  const ids = new Set(nodes.map((n) => n.id));
  const taskDeps = new Map<string, string[]>();
  for (const t of byType.get("task") ?? []) {
    const deps = asStrings(t.metadata.dependsOn).filter((d) => ids.has(`task:${d}`));
    taskDeps.set(t.id, deps);
  }
  const depthOf = (id: string, trail: string[]): number => {
    if (trail.includes(id)) return trail.indexOf(id);
    const deps = taskDeps.get(id) ?? [];
    if (deps.length === 0) return 0;
    return 1 + Math.max(...deps.map((d) => depthOf(`task:${d}`, [...trail, id])));
  };
  const place = (list: GraphNode[], x: number): void => {
    list.forEach((n, i) => {
      positions.set(n.id, { x, y: i * (GRAPH_NODE_H + GRAPH_GAP_Y) });
    });
  };
  place(byType.get("requirement") ?? [], 0);
  const tasksByDepth = new Map<number, GraphNode[]>();
  let maxDepth = 0;
  for (const t of byType.get("task") ?? []) {
    const depth = depthOf(t.id, []);
    maxDepth = Math.max(maxDepth, depth);
    tasksByDepth.set(depth, [...(tasksByDepth.get(depth) ?? []), t]);
  }
  // Re-stack each depth column compactly from the top.
  for (const [depth, members] of [...tasksByDepth.entries()].sort((a, b) => a[0] - b[0])) {
    place(members, 1 + depth);
  }
  const agentX = 2 + maxDepth;
  place(byType.get("agent") ?? [], agentX);
  let leafX = agentX + 1;
  for (const lane of ["file", "commit", "test", "evidence"] as GraphNodeType[]) {
    const list = byType.get(lane) ?? [];
    if (list.length === 0) continue;
    place(list, leafX);
    leafX += 1;
  }
  return positions;
}

export function graphDimensions(positions: Map<string, { x: number; y: number }>): {
  width: number;
  height: number;
} {
  // x is a column index; y is already pixels. Dimensions are pixels.
  let width = GRAPH_NODE_W;
  let height = GRAPH_NODE_H;
  for (const { x, y } of positions.values()) {
    width = Math.max(width, x * (GRAPH_NODE_W + GRAPH_GAP_X) + GRAPH_NODE_W);
    height = Math.max(height, y + GRAPH_NODE_H);
  }
  return { width, height };
}
