// Investigation explanations (UI-5 §8): deterministic "why" chains from
// recorded data only. No AI generation, no invented authority — every line
// names the record it came from. Verification language is historical
// ("recorded verification point"), never current-validity (§16).

import { missingForVerification } from "../requirements/requirementModel";
import type {
  AgentInfo,
  EventEntry,
  TaskInfo,
  TraceabilityRequirement,
  VerificationProvenance,
} from "../types";

export interface WhyLink {
  kind: "criterion" | "task" | "agent" | "evidence" | "attempt";
  label: string;
  detail: string | null;
  /** Graph node id to select, when the target is graphed. */
  nodeId: string | null;
  taskId: string | null;
  agentId: string | null;
  artifactId: string | null;
}

export interface WhyChain {
  criterion: string;
  verifiedAt: string | null;
  links: WhyLink[];
  provenance: VerificationProvenance | null;
}

export interface WhyRequirement {
  verdict: "VERIFIED" | "FAILED" | "UNKNOWN";
  chains: WhyChain[];
  missing: string[];
  failedCriteria: string[];
}

function agentName(agents: AgentInfo[], id: string | null): string {
  if (!id) return "unassigned";
  return agents.find((a) => a.id === id)?.name ?? id.slice(0, 8);
}

function latestSuccess(
  tasks: TaskInfo[],
  taskId: string | null,
): { task: TaskInfo; attemptNumber: number; agentId: string | null } | null {
  if (!taskId) return null;
  const task = tasks.find((t) => t.id === taskId);
  if (!task) return null;
  const wins = task.attempts.filter((a) => a.outcome === "success");
  if (wins.length === 0) return null;
  const last = wins[wins.length - 1];
  return { task, attemptNumber: last.attempt_number, agentId: last.agent_id };
}

/**
 * Why does this requirement hold its status? VERIFIED chains bind each
 * verified mandatory criterion to its validation record, evidence, task,
 * and latest successful attempt. The attempt/agent line is the latest
 * recorded success on the verifying task — labelled as such, never as
 * "the verifying attempt" (the backend records no such binding).
 */
export function whyRequirement(
  req: TraceabilityRequirement,
  tasks: TaskInfo[],
  agents: AgentInfo[],
): WhyRequirement {
  const chains: WhyChain[] = [];
  const failedCriteria: string[] = [];
  for (const criterion of req.criteria ?? []) {
    if (criterion.state === "failed" && criterion.mandatory) {
      failedCriteria.push(criterion.description);
    }
    if (criterion.state !== "verified" || !criterion.mandatory) continue;
    const provenance = criterion.verification ?? null;
    const links: WhyLink[] = [];
    if (provenance?.evidence_artifact_id) {
      links.push({
        kind: "evidence",
        label: `Evidence: ${provenance.evidence_artifact_id.slice(0, 8)}…`,
        detail: "bound at verify time (validation row)",
        nodeId: `ev:${provenance.evidence_artifact_id}`,
        taskId: null,
        agentId: null,
        artifactId: provenance.evidence_artifact_id,
      });
    }
    const win = latestSuccess(tasks, provenance?.task_id ?? null);
    if (win) {
      links.push({
        kind: "task",
        label: `Task: ${win.task.title}`,
        detail: `status ${win.task.status}`,
        nodeId: `task:${win.task.id}`,
        taskId: win.task.id,
        agentId: null,
        artifactId: null,
      });
      links.push({
        kind: "attempt",
        label: `Attempt #${win.attemptNumber} (latest recorded success)`,
        detail: `agent ${agentName(agents, win.agentId)}`,
        nodeId: win.agentId ? `agent:${win.agentId}` : null,
        taskId: win.task.id,
        agentId: win.agentId,
        artifactId: null,
      });
    }
    chains.push({
      criterion: criterion.description,
      verifiedAt: provenance?.verified_at ?? null,
      links,
      provenance,
    });
  }
  const verdict = req.status === "VERIFIED" ? "VERIFIED" : req.status === "FAILED" ? "FAILED" : "UNKNOWN";
  const linked = tasks.filter((t) => req.task_ids.includes(t.id));
  return {
    verdict,
    chains,
    missing: verdict === "UNKNOWN" ? missingForVerification(req, linked) : [],
    failedCriteria,
  };
}

export interface AttemptRow {
  attemptNumber: number;
  agent: string;
  agentId: string | null;
  outcome: string;
  failure: string | null;
  evidenceCount: number;
}

/** Attempt rows for task investigation (§10): attempt ≠ execution ≠ tool call. */
export function attemptRows(task: TaskInfo, agents: AgentInfo[]): AttemptRow[] {
  return task.attempts.map((a) => ({
    attemptNumber: a.attempt_number,
    agent: agentName(agents, a.agent_id),
    agentId: a.agent_id,
    outcome: a.outcome ?? "in progress",
    failure: a.outcome !== null && a.outcome !== "success"
      ? (a.failure_class ?? a.outcome)
      : null,
    evidenceCount: a.evidence_artifact_ids.length,
  }));
}

export interface AgentAttemptRow {
  taskId: string;
  taskTitle: string;
  taskStatus: string;
  attemptNumber: number;
  outcome: string;
  failure: string | null;
}

/** Every recorded attempt by one agent, newest task order kept (§11). */
export function agentAttempts(tasks: TaskInfo[], agentId: string): AgentAttemptRow[] {
  const rows: AgentAttemptRow[] = [];
  for (const task of tasks) {
    for (const attempt of task.attempts) {
      if (attempt.agent_id !== agentId) continue;
      rows.push({
        taskId: task.id,
        taskTitle: task.title,
        taskStatus: task.status,
        attemptNumber: attempt.attempt_number,
        outcome: attempt.outcome ?? "in progress",
        failure: attempt.outcome !== null && attempt.outcome !== "success"
          ? (attempt.failure_class ?? attempt.outcome)
          : null,
      });
    }
  }
  return rows;
}

export interface AgentToolRun {
  tool: string;
  path: string | null;
  exitCode: number | null;
  occurredAt: string;
  taskId: string | null;
}

/** Recorded tool runs for one agent, newest first, bounded (§11). */
export function agentToolRuns(events: EventEntry[], agentId: string, limit = 5): AgentToolRun[] {
  return events
    .filter((e) => e.event_type === "TOOL_RUN_COMPLETED" && e.agent_id === agentId)
    .sort((a, b) => Date.parse(b.occurred_at) - Date.parse(a.occurred_at))
    .slice(0, Math.max(0, limit))
    .map((e) => ({
      tool: typeof e.payload.tool === "string" ? e.payload.tool : "tool",
      path: typeof e.payload.path === "string" ? e.payload.path : null,
      exitCode: typeof e.payload.exit_code === "number" ? e.payload.exit_code : null,
      occurredAt: e.occurred_at,
      taskId: e.task_id,
    }));
}

export interface EvidenceSource {
  taskId: string;
  taskTitle: string;
  taskStatus: string;
  attemptNumber: number;
  agentId: string | null;
}

export interface EvidenceCriterion {
  requirementId: string;
  requirementTitle: string;
  criterion: string;
  verifiedAt: string | null;
}

/**
 * Backward chain for one artifact (§15/F): which attempts recorded it
 * (PERSISTED id lists) and which verified criteria bound it at verify time
 * (PERSISTED validation rows). Anything absent stays absent — no guessing
 * the "verifying attempt".
 */
export function evidenceSources(artifactId: string, tasks: TaskInfo[]): EvidenceSource[] {
  const out: EvidenceSource[] = [];
  for (const task of tasks) {
    for (const attempt of task.attempts) {
      if (attempt.evidence_artifact_ids.includes(artifactId)) {
        out.push({
          taskId: task.id,
          taskTitle: task.title,
          taskStatus: task.status,
          attemptNumber: attempt.attempt_number,
          agentId: attempt.agent_id,
        });
      }
    }
  }
  return out;
}

export function evidenceCriteria(
  artifactId: string,
  requirements: TraceabilityRequirement[],
): EvidenceCriterion[] {
  const out: EvidenceCriterion[] = [];
  for (const req of requirements) {
    for (const criterion of req.criteria ?? []) {
      if (criterion.verification?.evidence_artifact_id === artifactId) {
        out.push({
          requirementId: req.id,
          requirementTitle: req.title,
          criterion: criterion.description,
          verifiedAt: criterion.verification.verified_at,
        });
      }
    }
  }
  return out;
}
