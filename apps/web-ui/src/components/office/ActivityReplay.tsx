// Event replay (Wave 8 completion): step through the LOADED event window
// oldest-first with play/step controls. The snapshot freezes on entry;
// panels always show current state, never reconstructed history — the UI
// says so. Inspect buttons reuse the existing office navigation; replay
// never auto-navigates (that would unmount itself and destroy context).

import { useEffect, useRef, useState } from "react";

import type { ReplayStep } from "../../office/selectors";
import { useOffice } from "../../state/officeStore";

const SPEEDS = [
  { label: "1×", ms: 1600 },
  { label: "2×", ms: 800 },
  { label: "4×", ms: 400 },
];

export default function ActivityReplay({ steps, liveTotal, onExit }: {
  steps: ReplayStep[];
  liveTotal: number;
  onExit: () => void;
}) {
  const agents = useOffice((s) => s.agents);
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
  const currentRef = useRef<HTMLLIElement>(null);
  const step = steps[index] ?? null;

  useEffect(() => {
    if (!playing || steps.length === 0) return;
    const ms = SPEEDS[speed]?.ms ?? SPEEDS[0].ms;
    const timer = window.setInterval(() => {
      setIndex((i) => {
        if (i + 1 >= steps.length) {
          setPlaying(false);
          return i;
        }
        return i + 1;
      });
    }, ms);
    return () => window.clearInterval(timer);
  }, [playing, speed, steps.length]);

  useEffect(() => {
    currentRef.current?.scrollIntoView({ block: "nearest" });
  }, [index]);

  const agentName = (id: string | null): string =>
    id ? (agents.find((a) => a.id === id)?.name ?? id.slice(0, 8)) : "?";
  const newArrivals = Math.max(0, liveTotal - steps.length);

  return (
    <section aria-label="Event replay" className="stack">
      <div className="row spread">
        <strong className="small">
          Replay — step {steps.length === 0 ? 0 : index + 1} of {steps.length}
        </strong>
        <button className="btn btn-small" onClick={onExit}>
          Exit replay
        </button>
      </div>
      <p className="small muted">
        Replaying the loaded event window oldest-first. Panels show current
        state, not historical snapshots — the feed is bounded, not full history.
        {newArrivals > 0 && ` ${newArrivals} new event${newArrivals === 1 ? "" : "s"} arrived; exit and re-enter to include ${newArrivals === 1 ? "it" : "them"}.`}
      </p>
      {step && (
        <div className="replay-current">
          <div className="small muted mono">
            {new Date(step.event.occurred_at).toLocaleString()} · {step.event.event_type}
          </div>
          <div>{step.label}</div>
          <div className="row wrap gap4 small">
            {step.agentId && (
              <button
                className="link mono"
                title="Inspect this agent"
                onClick={() => setOffice({ selectedAgentId: step.agentId, selectedTaskId: null })}
              >
                {agentName(step.agentId)}
              </button>
            )}
            {step.taskId && (
              <button
                className="link mono"
                title="Inspect this task"
                onClick={() => setOffice({ selectedAgentId: null, selectedTaskId: step.taskId, tab: "team" })}
              >
                task
              </button>
            )}
          </div>
        </div>
      )}
      <div className="row wrap gap4" role="group" aria-label="Replay controls">
        <button
          className="btn btn-small"
          aria-label="Previous event"
          disabled={index === 0}
          onClick={() => { setPlaying(false); setIndex((i) => Math.max(0, i - 1)); }}
        >
          ◀
        </button>
        {!reducedMotion && (
          <button
            className="btn btn-small"
            aria-label={playing ? "Pause replay" : "Play replay"}
            onClick={() => setPlaying((v) => !v)}
          >
            {playing ? "Pause" : "Play"}
          </button>
        )}
        <button
          className="btn btn-small"
          aria-label="Next event"
          disabled={steps.length === 0 || index >= steps.length - 1}
          onClick={() => { setPlaying(false); setIndex((i) => Math.min(steps.length - 1, i + 1)); }}
        >
          ▶
        </button>
        {!reducedMotion && (
          <label className="small muted row gap4">
            Speed
            <select
              className="text-input small"
              aria-label="Replay speed"
              value={speed}
              onChange={(e) => setSpeed(Number(e.target.value))}
            >
              {SPEEDS.map((s, i) => (
                <option key={s.label} value={i}>{s.label}</option>
              ))}
            </select>
          </label>
        )}
      </div>
      <ol className="replay-list small">
        {steps.map((s, i) => (
          <li
            key={s.id}
            ref={i === index ? currentRef : undefined}
            className={i === index ? "selected" : ""}
            aria-current={i === index ? "true" : undefined}
          >
            <button
              className="link mono"
              aria-label={`Go to step ${i + 1}: ${s.label}`}
              onClick={() => { setPlaying(false); setIndex(i); }}
            >
              {new Date(s.event.occurred_at).toLocaleTimeString()} — {s.label}
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
}
