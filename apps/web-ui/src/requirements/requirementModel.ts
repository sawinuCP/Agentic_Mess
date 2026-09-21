// Requirement trust derivations (UI4, pure logic): everything the
// Requirements surface shows beyond raw backend rows is derived here from
// recorded state — work progress, evidence candidates, missing-evidence
// lists, involved agents. No invented states: backend VERIFIED/FAILED/
// UNKNOWN pass through; IN PROGRESS/BLOCKED surface only as derived
// work-state lines, never as verification states.

import type {
  AgentInfo,
  EventEntry,
  TaskInfo,
  TraceabilityCriterion,
  TraceabilityRequirement,
} from "../types";

export type RequirementStatus = "VERIFIED" | "FAILED" | "UNKNOWN";

export function normalizeStatus(status: string): RequirementStatus {
  const upper = status.toUpperCase();
  if (upper === "VERIFIED" || upper === "FAILED") return upper;
  return "UNKNOWN";
}

export interface WorkState {
  total: number;
  done: number;
  blocked: number;
  running: boolean;
  label: string;
}

/** Derived work progress for linked tasks (labelled as work state, never as
 * verification). Terminal = completed/cancelled/failed. */
export function workState(tasks: TaskInfo[]): WorkState {
  const total = tasks.length;
  const done = tasks.filter((t) => ["completed", "cancelled"].includes(t.status)).length;
  const blocked = tasks.filter((t) => t.status === "blocked" || t.status === "failed").length;
  const running = tasks.some((t) => !["completed", "cancelled", "failed"].includes(t.status));
  const label = total === 0
    ? "No tasks linked"
    : `${done}/${total} tasks complete${blocked > 0 ? ` · ${blocked} blocked/failed` : ""}`;
  return { total, done, blocked, running, label };
}

export interface EvidenceCandidate {
  artifactId: string;
  taskId: string;
  taskTitle: string;
}

/** Recorded evidence that can back a verification: successful-attempt
 * artifacts and validation-linked artifacts on the requirement's tasks. */
export function evidenceCandidates(
  requirement: TraceabilityRequirement,
  tasks: TaskInfo[],
): EvidenceCandidate[] {
  const linked = new Set(requirement.task_ids);
  const seen = new Set<string>();
  const out: EvidenceCandidate[] = [];
  const validationIds = new Set(requirement.validation_evidence_artifact_ids);
  for (const task of tasks) {
    if (!linked.has(task.id)) continue;
    const ids = new Set<string>();
    for (const attempt of task.attempts) {
      for (const id of attempt.evidence_artifact_ids) ids.add(id);
    }
    for (const id of [...ids, ...validationIds]) {
      if (seen.has(id)) continue;
      seen.add(id);
      out.push({ artifactId: id, taskId: task.id, taskTitle: task.title });
    }
  }
  return out;
}

/** What's missing for verification, in plain words (UNKNOWN drill-down). */
export function missingForVerification(
  requirement: TraceabilityRequirement,
  tasks: TaskInfo[],
): string[] {
  const missing: string[] = [];
  if (!requirement.implemented || tasks.length === 0) {
    missing.push("No linked tasks — nothing implements this requirement yet");
    return missing;
  }
  for (const criterion of requirement.criteria) {
    if (!criterion.mandatory) continue;
    if (criterion.state !== "verified") {
      missing.push(`Criterion "${criterion.description.slice(0, 80)}" is ${criterion.state}`);
    }
  }
  if (evidenceCandidates(requirement, tasks).length === 0) {
    missing.push("No recorded evidence artifacts on linked tasks");
  }
  return missing;
}

/** Agents involved via attempts on linked tasks (names resolved by caller
 * data, never invented). */
export function involvedAgents(
  requirement: TraceabilityRequirement,
  tasks: TaskInfo[],
  agents: AgentInfo[],
): { id: string; name: string; state: string }[] {
  const linked = new Set(requirement.task_ids);
  const ids = new Set<string>();
  for (const task of tasks) {
    if (!linked.has(task.id)) continue;
    for (const attempt of task.attempts) {
      if (attempt.agent_id) ids.add(attempt.agent_id);
    }
  }
  return [...ids].map((id) => {
    const agent = agents.find((a) => a.id === id);
    return { id, name: agent?.name ?? id.slice(0, 8), state: agent?.state ?? "unknown" };
  });
}

/** Recorded touched files for linked tasks (tool-run payload paths). */
export function touchedFiles(
  requirement: TraceabilityRequirement,
  events: EventEntry[],
): string[] {
  const linked = new Set(requirement.task_ids);
  const files = new Set<string>();
  for (const e of events) {
    if (e.event_type !== "TOOL_RUN_COMPLETED") continue;
    if (e.task_id === null || !linked.has(e.task_id)) continue;
    if (typeof e.payload.path === "string" && e.payload.path.length > 0) {
      files.add(e.payload.path);
    }
  }
  return [...files].slice(0, 20);
}

/** Attempt outcomes across linked tasks (honest test signal, labelled). */
export function attemptSummary(tasks: TaskInfo[]): { success: number; failed: number; total: number } {
  let success = 0;
  let failed = 0;
  let total = 0;
  for (const task of tasks) {
    for (const attempt of task.attempts) {
      total += 1;
      if (attempt.outcome === "success") success += 1;
      else if (attempt.outcome === "failed" || attempt.failure_class) failed += 1;
    }
  }
  return { success, failed, total };
}

export type { TraceabilityCriterion };
