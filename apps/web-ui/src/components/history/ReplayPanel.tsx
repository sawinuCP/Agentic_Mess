// Replay panel (Wave 9 §12–13): scrub through loaded history with true
// state reconstruction. Speeds map to intervals; stepping is exact; jumping
// selects an event. Everything here is non-destructive: the fold reads the
// loaded snapshot and never writes the live store. Graph/office jumps open
// LIVE surfaces and say so.

import { useEffect, useMemo, useState } from "react";

import { foldReplay } from "../../timeline/model";
import type { EventEntry } from "../../types";
import { rosterMaps } from "../../timeline/model";
import type { AgentInfo, TaskInfo, TraceabilityRequirement } from "../../types";
import { useOffice } from "../../state/officeStore";
import { useStore } from "../../state/store";

const SPEEDS = [
  { label: "0.5×", ms: 3200 },
  { label: "1×", ms: 1600 },
  { label: "2×", ms: 800 },
  { label: "5×", ms: 320 },
  { label: "10×", ms: 160 },
];

export default function ReplayPanel({ ascending, agents, tasks, requirements, onExit, onJumpEvent }: {
  /** Loaded events oldest-first (the replayable window). */
  ascending: EventEntry[];
  agents: AgentInfo[];
  tasks: TaskInfo[];
  requirements: TraceabilityRequirement[];
  onExit: () => void;
  onJumpEvent: (id: string) => void;
}) {
  const setWorkspace = useStore((s) => s.set);
  const setOffice = useOffice((s) => s.set);
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [reducedMotion] = useState(
    () =>
      typeof window !== "undefined" &&
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );
  const roster = useMemo(
    () => rosterMaps(agents, tasks, requirements.map((r) => ({ id: r.id, title: r.title }))),
    [agents, tasks, requirements],
  );
  const snapshot = useMemo(
    () => foldReplay(ascending, index, roster),
    [ascending, index, roster],
  );

  useEffect(() => {
    if (!playing || ascending.length === 0) return;
    const ms = SPEEDS[speed]?.ms ?? SPEEDS[1].ms;
    const timer = window.setInterval(() => {
      setIndex((i) => {
        if (i + 1 >= ascending.length) {
          setPlaying(false);
          return i;
        }
        return i + 1;
      });
    }, ms);
    return () => window.clearInterval(timer);
  }, [playing, speed, ascending.length]);

  useEffect(() => {
    setIndex(0);
    setPlaying(false);
  }, [ascending.length]);

  const openLiveGraph = (partial: { rid?: string | null; tid?: string | null; aid?: string | null }): void => {
    setOffice({
      selectedRequirementId: partial.rid ?? null,
      selectedTaskId: partial.tid ?? null,
      selectedAgentId: partial.aid ?? null,
    });
    setWorkspace({ view: "graph", sidebarOpen: true });
  };

  return (
    <section aria-label="Execution replay" className="replay-panel stack">
      <div className="row spread">
        <strong className="small">
          Replay — event {ascending.length === 0 ? 0 : index + 1} of {ascending.length}
        </strong>
        <button className="btn btn-small" onClick={() => { setPlaying(false); onExit(); }}>
          Return to live
        </button>
      </div>
      <p className="small muted">
        Viewing history{snapshot.asOf ? ` as of ${new Date(snapshot.asOf).toLocaleString()}` : ""} —
        live execution is unchanged. Requirement verification below is as-of-now
        (no verification events exist); attempts and payload values are not reconstructed.
      </p>
      <label className="small muted row gap4">
        Scrub events
        <input
          type="range"
          className="replay-scrubber"
          aria-label="Replay position"
          min={0}
          max={Math.max(0, ascending.length - 1)}
          value={Math.min(index, Math.max(0, ascending.length - 1))}
          onChange={(e) => { setPlaying(false); setIndex(Number(e.target.value)); }}
        />
      </label>
      <div className="row wrap gap4" role="group" aria-label="Replay controls">
        <button className="btn btn-small" aria-label="Step back" disabled={index === 0} onClick={() => { setPlaying(false); setIndex((i) => Math.max(0, i - 1)); }}>
          ◀
        </button>
        {!reducedMotion && (
          <button className="btn btn-small" aria-label={playing ? "Pause replay" : "Play replay"} disabled={ascending.length === 0} onClick={() => setPlaying((v) => !v)}>
            {playing ? "Pause" : "Play"}
          </button>
        )}
        <button className="btn btn-small" aria-label="Step forward" disabled={ascending.length === 0 || index >= ascending.length - 1} onClick={() => { setPlaying(false); setIndex((i) => Math.min(ascending.length - 1, i + 1)); }}>
          ▶
        </button>
        {!reducedMotion && (
          <label className="small muted row gap4">
            Speed
            <select className="text-input small" aria-label="Replay speed" value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
              {SPEEDS.map((s, i) => (
                <option key={s.label} value={i}>{s.label}</option>
              ))}
            </select>
          </label>
        )}
        <button
          className="btn btn-small"
          disabled={ascending.length === 0}
          title="Jump the event list to the replayed event"
          onClick={() => {
            const current = ascending[index];
            if (current) onJumpEvent(current.id);
          }}
        >
          Jump to event
        </button>
      </div>
      <div className="replay-state small">
        <div className="row wrap gap4">
          <span><strong>{snapshot.counts.tasksRunning}</strong> tasks running</span>
          <span><strong>{snapshot.counts.tasksFailed}</strong> failed</span>
          <span><strong>{snapshot.counts.tasksBlocked}</strong> blocked</span>
          <span><strong>{snapshot.counts.tasksCompleted}</strong> completed</span>
          <span><strong>{snapshot.counts.agentsRunning}</strong> agents running</span>
        </div>
        <div className="row wrap gap4">
          <span>Tests: <strong>{snapshot.tests.passed}</strong> passed / <strong>{snapshot.tests.failed}</strong> failed</span>
          <span>HITL: <strong>{snapshot.hitl.requested}</strong> requested / <strong>{snapshot.hitl.responded}</strong> responded</span>
          <span>Recovery milestones: <strong>{snapshot.recoveryMilestones.length}</strong></span>
        </div>
        {snapshot.agents.length > 0 && (
          <details>
            <summary>Agents at this point ({snapshot.agents.length})</summary>
            <ul className="replay-list small">
              {snapshot.agents.map((a) => (
                <li key={a.id}>
                  {a.label} — {a.state.replaceAll("_", " ")}
                  <span className="muted"> · since {new Date(a.since).toLocaleTimeString()}</span>
                </li>
              ))}
            </ul>
          </details>
        )}
        {snapshot.tasks.length > 0 && (
          <details>
            <summary>Tasks at this point ({snapshot.tasks.length})</summary>
            <ul className="replay-list small">
              {snapshot.tasks.map((t) => (
                <li key={t.id}>
                  {t.label} — {t.state.replaceAll("_", " ")}
                  <span className="muted"> · {t.lastEvent}</span>
                </li>
              ))}
            </ul>
          </details>
        )}
        {snapshot.recoveryMilestones.length > 0 && (
          <details>
            <summary>Recovery so far ({snapshot.recoveryMilestones.length})</summary>
            <ul className="replay-list small">
              {snapshot.recoveryMilestones.map((m, i) => (
                <li key={`${m.type}-${i}`}>
                  {m.type} <span className="muted">· {new Date(m.timestamp).toLocaleTimeString()}</span>
                </li>
              ))}
            </ul>
          </details>
        )}
        {snapshot.commits.length > 0 && (
          <details>
            <summary>Commits so far ({snapshot.commits.length})</summary>
            <ul className="replay-list small">
              {snapshot.commits.map((c, i) => (
                <li key={`${c.timestamp}-${i}`}>
                  {c.message}
                  <span className="muted"> · {c.paths.length} file(s)</span>
                </li>
              ))}
            </ul>
          </details>
        )}
        <div className="row wrap gap4">
          <button
            className="btn btn-small"
            title="Open the live execution graph (live data, not historical)"
            onClick={() => openLiveGraph({})}
          >
            Open live graph
          </button>
        </div>
      </div>
    </section>
  );
}
