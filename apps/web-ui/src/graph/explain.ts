// Investigation explanations (UI-5 §8): deterministic "why" chains from
// recorded data only. No AI generation, no invented authority — every line
// names the record it came from. Verification language is historical
// ("recorded verification point"), never current-validity (§16).

import { missingForVerification } from "../requirements/requirementModel";
import type {
  AgentInfo,
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
