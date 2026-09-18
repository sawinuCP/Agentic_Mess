// Communication tab: agent-to-agent messages as a real, structured
// coordination view, plus operator notes. The operator composes as sender
// `system` (labeled "You (operator)") — never as an agent — so authorship
// stays honest. No MESSAGE_* realtime events exist, so the list loads on
// open with an explicit refresh (documented in
// agent-office-architecture.md §8).

import { useEffect, useMemo, useState } from "react";
import { glue } from "@typehug/en";

import { sendOperatorMessage } from "../../api/client";
import { errorMessage } from "../../api/errors";
import { messageEndpoints, messageSummary } from "../../office/selectors";
import { useOffice } from "../../state/officeStore";
import { UiState } from "../shell/UiState";

export default function CommsTab() {
  const agents = useOffice((s) => s.agents);
  const tasks = useOffice((s) => s.tasks);
  const messages = useOffice((s) => s.messages);
  const messagesLoading = useOffice((s) => s.messagesLoading);
  const messagesError = useOffice((s) => s.messagesError);
  const loadMessages = useOffice((s) => s.loadMessages);
  const setOffice = useOffice((s) => s.set);
  const [typeFilter, setTypeFilter] = useState("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [composeOpen, setComposeOpen] = useState(false);
  const [recipient, setRecipient] = useState("");
  const [kind, setKind] = useState<"request" | "question">("request");
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);

  useEffect(() => {
    if (messages.length === 0 && !messagesLoading) void loadMessages().catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const names = useMemo(() => {
    const map = new Map<string, string>();
    for (const a of agents) map.set(a.id, a.name);
    return (id: string | null): string => {
      if (!id) return "?";
      return map.get(id) ?? id.slice(0, 8);
    };
  }, [agents]);

  const types = useMemo(
    () => ["all", ...new Set(messages.map((m) => m.type))],
    [messages],
  );
  const filtered = useMemo(
    () => (typeFilter === "all" ? messages : messages.filter((m) => m.type === typeFilter)),
    [messages, typeFilter],
  );
  const selected = filtered.find((m) => m.id === selectedId) ?? null;
  const selectedTask = selected?.task_id ? tasks.find((t) => t.id === selected.task_id) : null;

  const send = async (): Promise<void> => {
    if (!text.trim() || sending) return;
    setSending(true);
    setSendError(null);
    try {
      // The 201 response IS the durable record: insert it directly (a
      // broadcast has no recipient inbox to reload from), then reload to
      // reconcile — dedupe by id keeps both paths consistent.
      const created = await sendOperatorMessage(recipient || null, {
        type: kind,
        summary: text.trim(),
      });
      const current = useOffice.getState().messages;
      useOffice.getState().set({
        messages: [created, ...current.filter((m) => m.id !== created.id)],
      });
      setText("");
      setComposeOpen(false);
      await loadMessages();
    } catch (err) {
      setSendError(errorMessage(err));
    } finally {
      setSending(false);
    }
  };

  if (messagesError) {
    return (
      <UiState title="Communication unavailable" error retry={() => void loadMessages()}>
        {messagesError}
      </UiState>
    );
  }

  return (
    <div className="stack">
      <div className="row spread">
        <span className="small muted">
          {messagesLoading ? glue("Loading messages…") : glue(`${filtered.length} message${filtered.length === 1 ? "" : "s"}`)}
        </span>
        <span className="row gap4">
          <button
            className="btn btn-small"
            onClick={() => setComposeOpen((v) => !v)}
            aria-expanded={composeOpen}
          >
            {composeOpen ? "Close" : "Note to agents…"}
          </button>
          <button
            className="btn btn-small"
            disabled={messagesLoading}
            onClick={() => void loadMessages()}
          >
            Refresh
          </button>
        </span>
      </div>
      {composeOpen && (
        <div className="comms-compose stack">
          <p className="small muted">
            Sent as <span className="mono">system</span> — you (the operator), never as an agent.
          </p>
          {sendError && <p role="alert" className="error-text small">{sendError}</p>}
          <label className="small row gap4">
            To
            <select
              className="text-input small"
              aria-label="Message recipient"
              value={recipient}
              onChange={(e) => setRecipient(e.target.value)}
            >
              <option value="">broadcast (all agents)</option>
              {agents.map((a) => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </select>
          </label>
          <label className="small row gap4">
            Type
            <select
              className="text-input small"
              aria-label="Message type"
              value={kind}
              onChange={(e) => setKind(e.target.value as "request" | "question")}
            >
              <option value="request">request</option>
              <option value="question">question</option>
            </select>
          </label>
          <textarea
            className="text-input small"
            aria-label="Operator note"
            rows={3}
            placeholder="What should the agent(s) know or do?"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <div>
            <button
              className="btn btn-small"
              disabled={!text.trim() || sending}
              onClick={() => void send()}
            >
              {sending ? "Sending…" : "Send operator note"}
            </button>
          </div>
        </div>
      )}
      {types.length > 2 && (
        <div className="row wrap" role="group" aria-label="Filter by message type">
          {types.map((type) => (
            <button
              key={type}
              className={`chip ${typeFilter === type ? "active" : ""}`}
              aria-pressed={typeFilter === type}
              onClick={() => { setTypeFilter(type); setSelectedId(null); }}
            >
              {type}
            </button>
          ))}
        </div>
      )}
      {filtered.length === 0 && !messagesLoading && (
        <div className="muted small pad-h">{glue("No agent messages recorded.")}</div>
      )}
      {filtered.map((message) => {
        const expanded = selectedId === message.id;
        return (
          <div key={message.id} className="comms-row">
            <button
              className="link comms-main"
              aria-expanded={expanded}
              aria-label={`Message ${message.type} ${messageEndpoints(message, names)}`}
              onClick={() => setSelectedId(expanded ? null : message.id)}
            >
              <span className="strong">{messageEndpoints(message, names)}</span>
              <span className={`state-pill tiny ${message.type === "question" ? "warn" : "muted"}`}>
                {message.type}
              </span>
            </button>
            <div className="small muted">{messageSummary(message)}</div>
            <div className="small muted mono">
              {new Date(message.created_at).toLocaleString()}
              {message.correlation_id ? ` · corr ${message.correlation_id.slice(0, 8)}` : ""}
              {message.delivered_at ? "" : " · undelivered"}
            </div>
            {expanded && (
              <dl className="comms-detail small">
                <dt>Timestamp</dt>
                <dd className="mono">{new Date(message.created_at).toLocaleString()}</dd>
                <dt>Sender</dt>
                <dd>
                  {message.sender_agent_id ? (
                    <button
                      className="link mono"
                      onClick={() => setOffice({ selectedAgentId: message.sender_agent_id, selectedTaskId: null })}
                    >
                      {names(message.sender_agent_id)}
                    </button>
                  ) : (
                    "system"
                  )}
                </dd>
                <dt>Recipient</dt>
                <dd>
                  {message.recipient_agent_id ? (
                    <button
                      className="link mono"
                      onClick={() => setOffice({ selectedAgentId: message.recipient_agent_id, selectedTaskId: null })}
                    >
                      {names(message.recipient_agent_id)}
                    </button>
                  ) : (
                    "broadcast"
                  )}
                </dd>
                <dt>Task</dt>
                <dd>
                  {selectedTask ? (
                    <button
                      className="link"
                      onClick={() => setOffice({ selectedAgentId: null, selectedTaskId: selectedTask.id, tab: "team" })}
                    >
                      {selectedTask.title}
                    </button>
                  ) : (
                    message.task_id ?? "—"
                  )}
                </dd>
                <dt>Type</dt>
                <dd className="mono">{message.type} · priority {message.priority}</dd>
                <dt>Correlation</dt>
                <dd className="mono">{message.correlation_id ?? "—"}</dd>
                {message.reply_to && (
                  <>
                    <dt>In reply to</dt>
                    <dd className="mono">{message.reply_to.slice(0, 8)}</dd>
                  </>
                )}
                {message.payload_ref && (
                  <>
                    <dt>Evidence ref</dt>
                    <dd className="mono">{message.payload_ref.slice(0, 8)}</dd>
                  </>
                )}
                <dt>Payload keys</dt>
                <dd className="mono">
                  {Object.keys(message.payload).length > 0
                    ? Object.keys(message.payload).join(", ")
                    : "empty"}
                </dd>
                <dt>Delivery</dt>
                <dd className="mono">
                  {message.delivered_at
                    ? `delivered ${new Date(message.delivered_at).toLocaleString()}`
                    : `pending (${message.delivery_attempts} attempts)`}
                </dd>
              </dl>
            )}
          </div>
        );
      })}
      <div className="small muted pad-h">
        {glue("Bounded to the 200 most recent messages across agents. No live message events exist — refresh to reload.")}
      </div>
    </div>
  );
}
