import { describe, expect, it } from "vitest";

import type { EventEnvelope } from "../types";
import { applyEnvelope, MAX_TIMELINE_EVENTS, projectionFromLists, sequenceCheck } from "./eventReducer";

function event(sequence: number, overrides: Partial<EventEnvelope> = {}): EventEnvelope {
  return {
    schema_version: 1,
    event_id: `event-${sequence}`,
    event_type: "AGENT_CREATED",
    timestamp: "2026-09-17T12:00:00Z",
    project_id: "project-a",
    execution_id: null,
    task_id: null,
    agent_id: "agent-a",
    correlation_id: null,
    source: "test",
    sequence,
    payload: { name: "Worker", role: "worker" },
    payload_ref: null,
    ...overrides,
  };
}

const empty = () => projectionFromLists([], [], [], []);

describe("event reducer", () => {
  it("projects lifecycle updates without mutating previous state or unrelated agents", () => {
    const initial = empty();
    const created = applyEnvelope(initial, event(1)).projection;
    const parallel = applyEnvelope(created, event(2, { agent_id: "agent-b" })).projection;
    const running = applyEnvelope(parallel, event(3, {
      event_type: "AGENT_STATUS_CHANGED", payload: { to: "running" },
    })).projection;
    const completed = applyEnvelope(running, event(4, {
      event_type: "AGENT_STATUS_CHANGED", payload: { to: "completed" },
    })).projection;
    expect(initial.agents).toEqual([]);
    expect(created.agents[0].state).toBe("created");
    expect(running.agents[0].state).toBe("running");
    expect(completed.agents[0].state).toBe("completed");
    expect(completed.agents[1]).toBe(parallel.agents[1]);
    expect(completed.tasks).toBe(initial.tasks);
  });

  it("deduplicates by event ID and sequence and detects 100, 101, 103", () => {
    const first = applyEnvelope(empty(), event(100)).projection;
    expect(sequenceCheck(first, event(100))).toBe("duplicate");
    expect(sequenceCheck(first, event(100, { event_id: "another-id" }))).toBe("duplicate");
    expect(sequenceCheck(first, event(101))).toBe("apply");
    const second = applyEnvelope(first, event(101)).projection;
    expect(sequenceCheck(second, event(103))).toBe("gap");
    expect(second.lastSequence).toBe(101);
  });

  it("preserves domain references for timeline-only events and bounds history", () => {
    let state = empty();
    const agents = state.agents;
    for (let sequence = 1; sequence <= MAX_TIMELINE_EVENTS + 20; sequence++) {
      state = applyEnvelope(state, event(sequence, { event_type: "TOOL_COMPLETED" })).projection;
    }
    expect(state.agents).toBe(agents);
    expect(state.events).toHaveLength(MAX_TIMELINE_EVENTS);
    expect(state.lastSequence).toBe(MAX_TIMELINE_EVENTS + 20);
    const restored = projectionFromLists(state.agents, state.tasks, state.hitl, state.events);
    expect(restored.lastSequence).toBe(state.lastSequence);
  });
});
