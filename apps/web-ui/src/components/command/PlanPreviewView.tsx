// Plan preview (UI2): renders the plan the backend/classifier actually
// produced — goal, steps, scope, estimates — plus sections derived ONLY from
// recorded state: Agents (owners of created tasks), Dependencies (their
// depends_on), Approvals (gated actions + reason), Expected output (finding
// refs produced so far). Anything unknown is omitted, never invented.

import { useOffice } from "../../state/officeStore";
import type { CenterEntry } from "../../command/types";

function agentsFor(entry: CenterEntry): string[] {
  const { tasks, agents } = useOffice.getState();
  const ids = new Set(entry.dispatches.map((d) => d.taskId).filter((id): id is string => !!id));
  if (ids.size === 0) return [];
  const names = new Set<string>();
  for (const task of tasks) {
    if (!ids.has(task.id)) continue;
    for (const attempt of task.attempts) {
      if (!attempt.agent_id) continue;
      const agent = agents.find((a) => a.id === attempt.agent_id);
      names.add(agent ? `${agent.name} (${agent.role})` : `agent ${attempt.agent_id.slice(0, 8)}`);
    }
  }
  return [...names];
}

function dependenciesFor(entry: CenterEntry): string[] {
  const { tasks } = useOffice.getState();
  const ids = new Set(entry.dispatches.map((d) => d.taskId).filter((id): id is string => !!id));
  if (entry.intent.scope.taskId) ids.add(entry.intent.scope.taskId);
  const byId = new Map(tasks.map((t) => [t.id, t]));
  const lines: string[] = [];
  for (const id of ids) {
    const task = byId.get(id);
    if (!task) continue;
    for (const depId of task.depends_on) {
      const dep = byId.get(depId);
      lines.push(`${dep ? dep.title : depId.slice(0, 8)} → ${task.title}`);
    }
  }
  return lines;
}

export default function PlanPreviewView({ entry }: { entry: CenterEntry }) {
  const agents = agentsFor(entry);
  const deps = dependenciesFor(entry);
  const gated = entry.plan.actions.filter((a) => a.gated);
  const open = entry.status === "preview";

  return (
    <details className="small cc-plan" open={open}>
      <summary>
        Plan: {entry.plan.goal}
        {gated.length > 0 && (
          <span className="muted"> · {gated.length} gated action{gated.length === 1 ? "" : "s"}</span>
        )}
      </summary>
      <ol className="cc-steps">
        {entry.plan.steps.map((step, i) => (
          <li key={i}>{step}</li>
        ))}
      </ol>
      {entry.plan.affected.length > 0 && (
        <p className="muted">Scope: {entry.plan.affected.join("; ")}</p>
      )}
      {agents.length > 0 && (
        <p>Agents: {agents.join(", ")} <span className="muted">(from created tasks)</span></p>
      )}
      {deps.length > 0 && (
        <p>Dependencies: {deps.join("; ")}</p>
      )}
      {entry.plan.estimates.length > 0 && (
        <p className="muted">Estimates: {entry.plan.estimates.join("; ")}</p>
      )}
      {entry.intent.confirmationRequired && (
        <p className="warn">
          Consequential: {entry.intent.confirmReason ?? "confirmation required"} —{" "}
          {gated.map((a) => a.label).join(", ") || "review before anything runs"}
        </p>
      )}
      {gated.length > 0 && (
        <div className="row wrap gap4" aria-label="Actions requiring approval">
          {gated.map((action) => (
            <span key={action.id} className="chip" title={action.detail}>{action.label}</span>
          ))}
        </div>
      )}
    </details>
  );
}
