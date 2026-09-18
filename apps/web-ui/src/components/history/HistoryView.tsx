// Execution history view (Wave 9): durable timeline over cursor-paginated
// events with live/history modes, search, filters, event detail with real
// correlation, and true state-reconstruction replay. The office 120-row feed
// is untouched; this view owns its bounded pages (500/page, chunked DOM).
// The server (PostgreSQL events table) stays authoritative throughout.

import { useEffect, useMemo, useRef, useState } from "react";

import { listHistory } from "../../api/client";
import { errorMessage } from "../../api/errors";
import {
  CATEGORIES,
  eventCategory,
  isFailureEvent,
  mergeHistoryPages,
  normalizeEvent,
  rosterMaps,
  searchTimeline,
  type TimelineCategory,
  type TimelineEvent,
} from "../../timeline/model";
import type { EventEntry } from "../../types";
import { useOffice } from "../../state/officeStore";
import { useStore } from "../../state/store";
import { UiState } from "../shell/UiState";
import EventDetail from "./EventDetail";
import ReplayPanel from "./ReplayPanel";

const PAGE_SIZE = 500;
const RENDER_CHUNK = 200;
const SERVER_TYPES = [
  "TASK_CREATED",
  "TASK_COMPLETED",
  "TASK_FAILED",
  "TASK_CANCELLED",
  "AGENT_STATUS_CHANGED",
  "RECOVERY_SELECTED",
  "TOOL_RUN_COMPLETED",
  "GIT_COMMIT",
  "HITL_REQUESTED",
  "HITL_RESPONDED",
];

function minSeq(entries: EventEntry[]): number | null {
  let min: number | null = null;
  for (const e of entries) {
    if (typeof e.project_seq === "number" && (min === null || e.project_seq < min)) min = e.project_seq;
  }
  return min;
}

function dayKey(iso: string): string {
  return new Date(iso).toLocaleDateString();
}

export default function HistoryView() {
  const project = useStore((s) => s.project);
  const agents = useOffice((s) => s.agents);
  const tasks = useOffice((s) => s.tasks);
  const traceability = useOffice((s) => s.traceability);
  const storeEvents = useOffice((s) => s.events);

  const [entries, setEntries] = useState<EventEntry[]>([]);
  const [paged, setPaged] = useState(false);
  const [exhausted, setExhausted] = useState(false);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [serverType, setServerType] = useState("all");
  const [category, setCategory] = useState("all");
  const [agentFilter, setAgentFilter] = useState("all");
  const [taskFilter, setTaskFilter] = useState("all");
  const [reqFilter, setReqFilter] = useState("all");
  const [failuresOnly, setFailuresOnly] = useState(false);
  const [query, setQuery] = useState("");
  const [timeScope, setTimeScope] = useState<"all" | "day" | "custom">("all");
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");
  const [showCount, setShowCount] = useState(RENDER_CHUNK);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [replaying, setReplaying] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);

  const loadHead = async (type: string): Promise<void> => {
    if (!project) return;
    setLoading(true);
    setLoadError(null);
    try {
      const page = await listHistory(project.id, {
        limit: PAGE_SIZE,
        order: "desc",
        eventType: type === "all" ? undefined : type,
      });
      setEntries(page);
      setPaged(false);
      setExhausted(page.length < PAGE_SIZE);
      setShowCount(RENDER_CHUNK);
      setSelectedId(null);
    } catch (err) {
      setLoadError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setEntries([]);
    setExhausted(false);
    void loadHead(serverType);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project?.id, serverType]);

  const loadOlder = async (): Promise<void> => {
    if (!project || loading) return;
    const before = minSeq(entries);
    if (before === null) {
      setExhausted(true);
      return;
    }
    setLoading(true);
    setLoadError(null);
    try {
      const page = await listHistory(project.id, {
        limit: PAGE_SIZE,
        order: "desc",
        beforeSeq: before,
        eventType: serverType === "all" ? undefined : serverType,
      });
      setEntries((prev) => mergeHistoryPages(prev, page));
      setPaged(true);
      if (page.length < PAGE_SIZE) setExhausted(true);
    } catch (err) {
      setLoadError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  const roster = useMemo(
    () => rosterMaps(agents, tasks, (traceability?.requirements ?? []).map((r) => ({ id: r.id, title: r.title }))),
    [agents, tasks, traceability],
  );
  const normalized: TimelineEvent[] = useMemo(
    () => entries.map((e) => normalizeEvent(e, roster)),
    [entries, roster],
  );
  const taskReq = useMemo(() => {
    const map = new Map<string, string>();
    for (const t of tasks) {
      if (t.requirement_id) map.set(t.id, t.requirement_id);
    }
    return map;
  }, [tasks]);
  const names = useMemo(
    () => ({
      agents: new Map(agents.map((a) => [a.id, a.name] as [string, string])),
      tasks: new Map(tasks.map((t) => [t.id, t.title] as [string, string])),
    }),
    [agents, tasks],
  );

  const filtered = useMemo(() => {
    const dayAgo = Date.now() - 24 * 3600 * 1000;
    const fromMs = customFrom ? Date.parse(customFrom) : NaN;
    const toMs = customTo ? Date.parse(customTo) : NaN;
    return searchTimeline(
      normalized.filter((e) => {
        if (category !== "all" && eventCategory(e.type) !== (category as TimelineCategory)) return false;
        if (agentFilter !== "all" && e.agentId !== agentFilter) return false;
        if (taskFilter !== "all" && e.taskId !== taskFilter) return false;
        if (reqFilter !== "all") {
          const reqOf = e.taskId ? taskReq.get(e.taskId) : undefined;
          const payloadReq = typeof e.raw === "object" && e.raw !== null
            ? (e.raw as Record<string, unknown>).requirement_id
            : undefined;
          if (reqOf !== reqFilter && payloadReq !== reqFilter) return false;
        }
        if (failuresOnly && !isFailureEvent(e.type, e.raw as Record<string, unknown>)) return false;
        const ms = Date.parse(e.timestamp);
        if (timeScope === "day" && ms < dayAgo) return false;
        if (timeScope === "custom") {
          if (!Number.isNaN(fromMs) && ms < fromMs) return false;
          if (!Number.isNaN(toMs) && ms > toMs) return false;
        }
        return true;
      }),
      query,
      names,
    );
  }, [normalized, category, agentFilter, taskFilter, reqFilter, failuresOnly, timeScope, customFrom, customTo, query, names, taskReq]);

  const requirements = traceability?.requirements ?? [];
  const rows = filtered.slice(0, showCount);
  const selected = filtered.find((e) => e.id === selectedId) ?? null;

  const loadedIds = useMemo(() => new Set(entries.map((e) => e.id)), [entries]);
  const newCount = storeEvents.filter((e) => !loadedIds.has(e.id)).length;
  const atHead = !paged && !replaying;
  const replayAsc = useMemo(() => {
    const byId = new Map(entries.map((e) => [e.id, e]));
    return filtered
      .map((e) => byId.get(e.id))
      .filter((e): e is EventEntry => !!e)
      .sort((a, b) => Date.parse(a.occurred_at) - Date.parse(b.occurred_at));
  }, [filtered, entries]);

  const jumpToEvent = (id: string): void => {
    setReplaying(false);
    setSelectedId(id);
    requestAnimationFrame(() => {
      listRef.current?.querySelector(`[data-event-id="${CSS.escape(id)}"]`)?.scrollIntoView({ block: "center" });
    });
  };

  if (!project) {
    return <div className="graph-empty muted">Open a project to browse execution history.</div>;
  }

  return (
    <div className="history-view">
      <div className="graph-header">
        <span className="strong">Execution history</span>
        {atHead && newCount === 0 ? (
          <span className="state-pill ok" title="Showing the newest durable events">● live</span>
        ) : (
          <span className="state-pill warn" title="Browsing loaded history; the live stream continues underneath">
            Viewing history
          </span>
        )}
        <span className="small muted">
          {filtered.length} of {entries.length} loaded events
          {exhausted ? " · history begins here" : ""}
        </span>
        <div className="status-spacer" />
        {(!atHead || newCount > 0) && !replaying && (
          <button
            className="btn btn-small"
            onClick={() => { setReplaying(false); void loadHead(serverType); }}
          >
            {newCount > 0 ? `Return to live (${newCount} new)` : "Return to live"}
          </button>
        )}
        {!replaying && (
          <button
            className="btn btn-small"
            disabled={filtered.length === 0}
            title={filtered.length === 0 ? "Nothing loaded to replay" : `Replay ${filtered.length} loaded events with state reconstruction`}
            onClick={() => setReplaying(true)}
          >
            Replay
          </button>
        )}
      </div>

      {replaying ? (
        <ReplayPanel
          ascending={replayAsc}
          agents={agents}
          tasks={tasks}
          requirements={requirements}
          onExit={() => setReplaying(false)}
          onJumpEvent={jumpToEvent}
        />
      ) : (
        <>
          <div className="graph-toolbar" role="toolbar" aria-label="History controls">
            <div className="row wrap" role="group" aria-label="Filter by category">
              <button className={`chip ${category === "all" ? "active" : ""}`} aria-pressed={category === "all"} onClick={() => setCategory("all")}>
                all
              </button>
              {CATEGORIES.map(({ category: value, label }) => (
                <button
                  key={value}
                  className={`chip ${category === value ? "active" : ""}`}
                  aria-pressed={category === value}
                  onClick={() => setCategory(value)}
                >
                  {label.toLowerCase()}
                </button>
              ))}
              <button className={`chip ${failuresOnly ? "active" : ""}`} aria-pressed={failuresOnly} onClick={() => setFailuresOnly((v) => !v)}>
                failures
              </button>
            </div>
            <div className="row wrap gap4">
              <label className="small muted row gap4">
                Server type
                <select className="text-input small" aria-label="Server-side event type filter" value={serverType} onChange={(e) => setServerType(e.target.value)}>
                  <option value="all">all (loaded)</option>
                  {SERVER_TYPES.map((t) => (
                    <option key={t} value={t}>{t}</option>
                  ))}
                </select>
              </label>
              {agents.length > 0 && (
                <label className="small muted row gap4">
                  Agent
                  <select className="text-input small" aria-label="Filter history by agent" value={agentFilter} onChange={(e) => setAgentFilter(e.target.value)}>
                    <option value="all">all agents</option>
                    {agents.map((a) => (
                      <option key={a.id} value={a.id}>{a.name}</option>
                    ))}
                  </select>
                </label>
              )}
              {tasks.length > 0 && (
                <label className="small muted row gap4">
                  Task
                  <select className="text-input small" aria-label="Filter history by task" value={taskFilter} onChange={(e) => setTaskFilter(e.target.value)}>
                    <option value="all">all tasks</option>
                    {tasks.map((t) => (
                      <option key={t.id} value={t.id}>{t.title}</option>
                    ))}
                  </select>
                </label>
              )}
              {requirements.length > 0 && (
                <label className="small muted row gap4">
                  Requirement
                  <select className="text-input small" aria-label="Filter history by requirement" value={reqFilter} onChange={(e) => setReqFilter(e.target.value)}>
                    <option value="all">all requirements</option>
                    {requirements.map((r) => (
                      <option key={r.id} value={r.id}>{r.title}</option>
                    ))}
                  </select>
                </label>
              )}
              <label className="small muted row gap4">
                Time
                <select className="text-input small" aria-label="Time scope" value={timeScope} onChange={(e) => setTimeScope(e.target.value as "all" | "day" | "custom")}>
                  <option value="all">entire loaded window</option>
                  <option value="day">recent 24h</option>
                  <option value="custom">custom range</option>
                </select>
              </label>
              {timeScope === "custom" && (
                <>
                  <input type="datetime-local" className="text-input small" aria-label="Range start" value={customFrom} onChange={(e) => setCustomFrom(e.target.value)} />
                  <input type="datetime-local" className="text-input small" aria-label="Range end" value={customTo} onChange={(e) => setCustomTo(e.target.value)} />
                </>
              )}
              <input
                className="text-input small"
                aria-label="Search loaded history"
                placeholder="Search summaries, names, paths…"
                value={query}
                onChange={(e) => { setQuery(e.target.value); setShowCount(RENDER_CHUNK); }}
              />
            </div>
          </div>

          {loadError && (
            <UiState title="History unavailable" error retry={() => void loadHead(serverType)}>
              {loadError}
            </UiState>
          )}

          <div className="history-body">
            <div ref={listRef} className="history-list" role="list" aria-label="Durable event history">
              {rows.length === 0 && !loading && (
                <div className="muted small pad-h">
                  {entries.length === 0
                    ? "No events recorded for this project yet."
                    : "No loaded events match these filters."}
                </div>
              )}
              {rows.map((e, i) => {
                const prevDay = i > 0 ? dayKey(rows[i - 1].timestamp) : null;
                const day = dayKey(e.timestamp);
                return (
                  <div key={e.id}>
                    {day !== prevDay && <div className="history-day">{day}</div>}
                    <button
                      className={`event-row detailed ${selectedId === e.id ? "selected" : ""}`}
                      data-event-id={e.id}
                      aria-label={`${e.type}: ${e.summary}`}
                      onClick={() => setSelectedId(selectedId === e.id ? null : e.id)}
                    >
                      <span className={`event-dot tone-${e.tone}`} aria-hidden="true" />
                      <span className="event-time muted small mono">
                        {new Date(e.timestamp).toLocaleTimeString()}
                      </span>
                      <span className="event-type mono">{e.type}</span>
                      <span className="event-detail" title={e.summary}>{e.summary}</span>
                    </button>
                  </div>
                );
              })}
              {loading && <p role="status" className="small muted pad-h">Loading history…</p>}
              {!loading && !exhausted && entries.length > 0 && (
                <button className="btn btn-small" onClick={() => void loadOlder()}>
                  Load older events
                </button>
              )}
              {!loading && filtered.length > showCount && (
                <button className="btn btn-small" onClick={() => setShowCount((c) => c + RENDER_CHUNK)}>
                  Show more ({filtered.length - showCount} remaining)
                </button>
              )}
            </div>
            {selected ? (
              <EventDetail
                event={selected}
                all={filtered}
                tasks={tasks}
                agents={agents}
                requirements={requirements}
                onSelectEvent={jumpToEvent}
              />
            ) : (
              <aside className="history-detail muted small" aria-label="Event details">
                Select an event to inspect context, correlation, evidence, and raw payload.
              </aside>
            )}
          </div>
        </>
      )}
    </div>
  );
}
