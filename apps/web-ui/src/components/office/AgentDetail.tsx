// Agent detail panel (Wave 7): contextual inspection without leaving the
// Office. Every section projects existing durable state; lazy sections
// (communication, worktrees, costs) fetch on first open only. Anything the
// backend does not record is labeled, never invented.

import { useEffect, useMemo, useState } from "react";
import { glue } from "@typehug/en";

import { endSession, listAgentSessions } from "../../api/client";
import { errorMessage } from "../../api/errors";
import type { SessionInfo } from "../../types";

import {
  BULK_LABEL,
  bulkEligible,
  costAttribution,
  currentTaskForAgent,
  describeEvent,
  elapsedSince,
  firstAgentEvent,
  formatTokens,
  recoveryForTask,
  tasksForAgent,
  topEntries,
  validCosts,
  waitingReason,
} from "../../office/selectors";
import { useBulkAction, type BulkAction } from "../../office/useBulkAction";
import { useOffice } from "../../state/officeStore";
import { useStore } from "../../state/store";
import { StatusLabel } from "../shell/UiState";
import { UiState } from "../shell/UiState";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h4 className="office-section-title muted">{glue(title)}</h4>
      {children}
    </section>
  );
}

export default function AgentDetail({ agentId }: { agentId: string }) {
  const agents = useOffice((s) => s.agents);
  const tasks = useOffice((s) => s.tasks);
  const events = useOffice((s) => s.events);
  const messages = useOffice((s) => s.messages);
  const messagesLoading = useOffice((s) => s.messagesLoading);
  const worktrees = useOffice((s) => s.worktrees);
  const worktreesLoading = useOffice((s) => s.worktreesLoading);
  const costs = useOffice((s) => s.costs);
  const taskCosts = useOffice((s) => s.taskCosts);
  const setOffice = useOffice((s) => s.set);
  const loadMessages = useOffice((s) => s.loadMessages);
  const loadWorktrees = useOffice((s) => s.loadWorktrees);
  const loadTaskCosts = useOffice((s) => s.loadTaskCosts);
  const openFile = useStore((s) => s.openFile);
  const { bulkBusy, runBulk } = useBulkAction();
  const [sessions, setSessions] = useState<SessionInfo[] | null>(null);
  const [sessionsError, setSessionsError] = useState<string | null>(null);

  const agent = agents.find((a) => a.id === agentId);

  const owned = useMemo(
    () => (agent ? tasksForAgent(tasks, agent.id) : []),
    [agent, tasks],
  );
  const current = agent ? currentTaskForAgent(tasks, agent.id) : null;
  const ownedIds = useMemo(() => new Set(owned.map((t) => t.id)), [owned]);

  // Lazy sections fetch once per project; the store guards duplicates.
  useEffect(() => {
    if (messages.length === 0 && !messagesLoading) void loadMessages().catch(() => undefined);
    if (worktrees.length === 0 && !worktreesLoading) void loadWorktrees().catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    for (const t of owned) void loadTaskCosts(t.id).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [owned.map((t) => t.id).join(",")]);
  useEffect(() => {
    // Sessions are runtime-owned; the detail reads them, never drives them.
    let active = true;
    setSessions(null);
    setSessionsError(null);
    listAgentSessions(agentId, 20)
      .then((rows) => { if (active) setSessions(rows); })
      .catch((err: unknown) => { if (active) setSessionsError(errorMessage(err)); });
    return () => { active = false; };
  }, [agentId]);

  if (!agent) {
    return (
      <div className="stack">
        <button className="btn btn-small" onClick={() => setOffice({ selectedAgentId: null })}>
          ← Back to team
        </button>
        <UiState title="Agent no longer recorded">
          It may have been removed from the project snapshot. Resync to refresh.
        </UiState>
      </div>
    );
  }

  const activity = events.filter((e) => e.agent_id === agent.id).slice(0, 8);
  const since = firstAgentEvent(events, agent.id);
  const activeFor = since ? elapsedSince(since.occurred_at) : null;
  const agentMessages = messages
    .filter((m) => m.sender_agent_id === agent.id || m.recipient_agent_id === agent.id)
    .slice(0, 10);
  const agentWorktrees = worktrees.filter((w) => w.task_id !== null && ownedIds.has(w.task_id));
  const toolRuns = events.filter(
    (e) =>
      e.event_type === "TOOL_RUN_COMPLETED" &&
      (e.agent_id === agent.id || (e.task_id !== null && ownedIds.has(e.task_id))),
  );
  const toolPaths = [...new Set(
    toolRuns.map((e) => e.payload.path).filter((p): p is string => typeof p === "string"),
  )].slice(0, 10);
  const evidenceIds = [...new Set(owned.flatMap((t) => t.attempts.flatMap((a) => a.evidence_artifact_ids)))];
  const validationEvents = events.filter(
    (e) =>
      (e.task_id !== null && ownedIds.has(e.task_id)) &&
      (e.event_type.startsWith("REVIEW_") ||
        e.event_type.startsWith("DECISION_") ||
        e.event_type === "SECURITY_SCAN_COMPLETED"),
  ).slice(0, 6);
  const recoveryTasks = owned.filter((t) => recoveryForTask(t, events).length > 0);
  const depLines = owned
    .filter((t) => !["completed", "cancelled", "failed"].includes(t.status))
    .map((t) => ({ task: t, reason: waitingReason(t, tasks) }))
    .filter((d) => d.reason !== null);

  const jumpToTask = (id: string): void => {
    setOffice({ selectedAgentId: null, selectedTaskId: id, tab: "team" });
  };

  return (
    <div className="stack agent-detail">
      <div className="row spread">
        <button className="btn btn-small" onClick={() => setOffice({ selectedAgentId: null })}>
          ← Back to team
        </button>
        <span className="row gap4">
          <button
            className="btn btn-small"
            title="Open the execution graph focused on this agent"
            onClick={() => {
              setOffice({ selectedAgentId: agent.id });
              useStore.getState().set({ view: "graph", sidebarOpen: true });
            }}
          >
            Graph
          </button>
          <button
            className="btn btn-small"
            title="Ask the Command Center about this agent"
            onClick={() => {
              setOffice({ selectedAgentId: agent.id, selectedTaskId: null });
              useStore.getState().set({ view: "command", sidebarOpen: true, centerPrefill: `What is blocking ${agent.name}?` });
            }}
          >
            Ask AI
          </button>
          <StatusLabel state={agent.state} />
        </span>
      </div>
      <div>
        <div className="strong">{agent.name}</div>
        <div className="small muted mono" title={agent.id}>
          {agent.role}
          {agent.model ? ` · ${agent.model}` : ""}
        </div>
      </div>

      <Section title="Overview">
        <div className="small stack">
          <span>
            Current work:{" "}
            {current ? (
              <button className="link" onClick={() => jumpToTask(current.id)}>
                {current.title} ({current.status.replaceAll("_", " ")})
              </button>
            ) : (
              <span className="muted">none recorded</span>
            )}
          </span>
          <span className="muted">
            Active since: {since ? new Date(since.occurred_at).toLocaleString() : "first recorded event not in feed"}
            {activeFor ? ` (active for ${activeFor})` : ""}
          </span>
          {agent.capabilities.length > 0 && (
            <span className="muted">Capabilities: {agent.capabilities.join(", ")}</span>
          )}
          {agentWorktrees.length > 0 && (
            <span>
              Worktree:{" "}
              <span className="mono">{agentWorktrees[0].branch}</span>{" "}
              <span className="muted">({agentWorktrees[0].integration_status})</span>
            </span>
          )}
        </div>
      </Section>

      <Section title="Sessions">
        <div className="small muted">
          Runtime-owned session history, newest first. Stale sessions are marked
          lost automatically; release a stuck <em>running</em> session here only
          if supervision has not caught up yet.
        </div>
        {sessions === null && !sessionsError && (
          <div className="muted small">Loading sessions…</div>
        )}
        {sessionsError && (
          <div className="error-text small" role="alert">{sessionsError}</div>
        )}
        {sessions !== null && sessions.length === 0 && (
          <div className="muted small">No sessions recorded for this agent.</div>
        )}
        {(sessions ?? []).slice(0, 6).map((session) => (
          <div key={session.id} className="small mono" title={`session ${session.id}`}>
            {session.runtime} · {session.status}
            {session.heartbeat_at ? ` · beat ${new Date(session.heartbeat_at).toLocaleTimeString()}` : ""}
            {session.finished_at ? ` · ended ${new Date(session.finished_at).toLocaleTimeString()}` : ""}
            {session.status === "running" && (
              <button
                className="btn btn-small"
                title="End this session now (supervision marks stale sessions lost automatically)"
                aria-label={`Release session ${session.id.slice(0, 8)}`}
                onClick={() => {
                  if (
                    !window.confirm(
                      "End this session now? The agent's recorded work is preserved; " +
                        "use this only for a session stuck running.",
                    )
                  ) {
                    return;
                  }
                  void endSession(session.id)
                    .then((ended) =>
                      setSessions((rows) =>
                        (rows ?? []).map((row) => (row.id === ended.id ? ended : row)),
                      ),
                    )
                    .catch((err: unknown) => setSessionsError(errorMessage(err)));
                }}
              >
                Release
              </button>
            )}
          </div>
        ))}
      </Section>

      <Section title="Activity">
        {activity.length === 0 && <div className="muted small">No events for this agent in the feed.</div>}
        <ul className="activity-list small">
          {activity.map((e) => (
            <li key={e.id} title={new Date(e.occurred_at).toLocaleString()}>
              <span className="mono muted">{new Date(e.occurred_at).toLocaleTimeString()}</span>{" "}
              {describeEvent(e)}
            </li>
          ))}
        </ul>
      </Section>

      <Section title={`Tasks (${owned.length})`}>
        {owned.length === 0 && <div className="muted small">No tasks reference this agent.</div>}
        {(["pause", "resume", "cancel"] as BulkAction[]).map((action) => {
          const eligible = bulkEligible(owned, action);
          if (eligible.length === 0) return null;
          return (
            <button
              key={action}
              className="btn btn-small"
              disabled={bulkBusy}
              title={`Eligible: ${eligible.slice(0, 3).map((t) => t.title).join(", ")}`}
              aria-label={`${BULK_LABEL[action]} ${agent.name}'s ${eligible.length} eligible tasks`}
              onClick={() => void runBulk(action, owned, `Agent ${agent.name}`)}
            >
              {bulkBusy ? "Sending…" : `${BULK_LABEL[action]} ${eligible.length}`}
            </button>
          );
        })}
        {owned.map((t) => (
          <div key={t.id} className="task-row">
            <div className="row spread">
              <button className="link strong" onClick={() => jumpToTask(t.id)}>
                {t.title}
              </button>
              <StatusLabel state={t.status} />
            </div>
          </div>
        ))}
      </Section>

      <Section title="Tools">
        {toolRuns.length === 0 && (
          <div className="muted small">
            No completed tool runs recorded for this agent. In-progress tool activity is not exposed by the backend.
          </div>
        )}
        {toolRuns.slice(0, 6).map((e) => (
          <div key={e.id} className="small mono" title={JSON.stringify(e.payload)}>
            {String(e.payload.tool ?? e.event_type)} · exit {String(e.payload.exit_code ?? "?")} ·{" "}
            {String(e.payload.duration_ms ?? "?")}ms
            {typeof e.payload.path === "string" ? ` · ${e.payload.path}` : ""}
          </div>
        ))}
      </Section>

      <Section title="Files">
        {toolPaths.length === 0 && (
          <div className="muted small">No touched files recorded.</div>
        )}
        {toolPaths.map((path) => (
          <div key={path} className="row spread small mono">
            <span className="file-path">{path}</span>
            <button className="btn btn-small" onClick={() => void openFile(path).catch(() => undefined)}>
              Open
            </button>
          </div>
        ))}
      </Section>

      <Section title="Evidence">
        {evidenceIds.length === 0 && validationEvents.length === 0 && (
          <div className="muted small">No tests, artifacts, or validation evidence recorded.</div>
        )}
        {evidenceIds.length > 0 && (
          <div className="small">
            {evidenceIds.length} artifact(s):{" "}
            <span className="mono muted">
              {evidenceIds.slice(0, 8).map((id) => id.slice(0, 8)).join(", ")}
              {evidenceIds.length > 8 ? "…" : ""}
            </span>
          </div>
        )}
        {validationEvents.map((e) => (
          <div key={e.id} className="small" title={new Date(e.occurred_at).toLocaleString()}>
            <span className="mono muted">{new Date(e.occurred_at).toLocaleTimeString()}</span>{" "}
            {describeEvent(e)}
          </div>
        ))}
      </Section>

      <Section title="Dependencies">
        {depLines.length === 0 && <div className="muted small">Nothing waiting on dependencies.</div>}
        {depLines.map(({ task: t, reason }) => (
          <div key={t.id} className="small">
            <button className="link" onClick={() => jumpToTask(t.id)}>{t.title}</button>
            <span className="warn"> — {reason}</span>
          </div>
        ))}
      </Section>

      <Section title="Communication">
        {messagesLoading && <div className="muted small">Loading messages…</div>}
        {!messagesLoading && agentMessages.length === 0 && (
          <div className="muted small">No messages involving this agent.</div>
        )}
        {agentMessages.map((m) => (
          <div key={m.id} className="small">
            <span className="mono muted">{new Date(m.created_at).toLocaleTimeString()}</span>{" "}
            {m.type}
            {m.task_id && ownedIds.has(m.task_id) ? " · on owned task" : ""}
          </div>
        ))}
        {agentMessages.length > 0 && (
          <button
            className="btn btn-small"
            onClick={() => setOffice({ tab: "comms" })}
          >
            Open full thread
          </button>
        )}
      </Section>

      <Section title="Recovery">
        {recoveryTasks.length === 0 && <div className="muted small">No failures or recovery on record.</div>}
        {recoveryTasks.map((t) => (
          <details key={t.id} className="small">
            <summary>{t.title}</summary>
            <ol className="recovery-chain">
              {recoveryForTask(t, events).map((step, i) => (
                <li key={i} className={`recovery-step ${step.tone}`}>
                  <span className="strong">{step.label}</span>
                  {step.detail && <span className="muted"> — {step.detail}</span>}
                </li>
              ))}
            </ol>
          </details>
        ))}
      </Section>

      <Section title="Cost">
        <div className="small muted">
          Per-agent token accounting is not exposed by the backend; recorded
          cost in USD is not exposed by the costs endpoint either.
        </div>
        {owned.map((t) => {
          const summary = validCosts(taskCosts[t.id]) ? taskCosts[t.id] : null;
          if (!summary) return null;
          const attribution = costAttribution(t, agent.id);
          return (
            <div key={t.id} className="small">
              {t.title}: {formatTokens(summary.total_tokens)} tokens · {summary.invocations} calls{" "}
              <span className="muted">
                {attribution.sole
                  ? "(sole contributor)"
                  : `(shared with ${attribution.others} other agent${attribution.others === 1 ? "" : "s"})`}
              </span>
            </div>
          );
        })}
        {validCosts(costs) && (
          <div className="small">
            Project: {formatTokens(costs.total_tokens)} tokens · {costs.invocations} calls
            {topEntries(costs.by_role).map(([role, n]) => (
              <span key={role} className="muted"> · {role} {formatTokens(n)}</span>
            ))}
          </div>
        )}
      </Section>
    </div>
  );
}
