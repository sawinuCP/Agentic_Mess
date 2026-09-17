import { expect, it } from "vitest";
import { useStore } from "./store";
import { applyEnvelope, projectionFromLists, sequenceCheck } from "./eventReducer";
import type { EventEnvelope } from "../types";

it("records selector invalidations for 100 edits and keeps event projections bounded", () => {
  const before = useStore.getState();
  useStore.setState({ tree: { "": [] }, tabs: [{ kind: "file", path: "local.ts", content: "",
    savedContent: "", isBinary: false, language: "typescript" }] });
  let broad = 0;
  let treeSelections = 0;
  const unsubscribe = useStore.subscribe((state, previous) => {
    broad++;
    if (state.tree[""] !== previous.tree[""]) treeSelections++;
  });
  const start = performance.now();
  try {
    for (let i = 0; i < 100; i++) useStore.getState().updateContent("local.ts", String(i));
    expect(broad).toBe(100);
    expect(treeSelections).toBe(0);
    let projection = projectionFromLists([], [], [], []);
    for (let i = 1; i <= 10000; i++) {
      const event: EventEnvelope = { schema_version: 1, event_id: `event-${i}`, sequence: i,
        timestamp: "2026-09-17T00:00:00Z", project_id: "p", execution_id: null,
        task_id: null, agent_id: null, correlation_id: null, payload_ref: null,
        event_type: "TOOL_FINISHED", source: "fixture", payload: {} };
      expect(sequenceCheck(projection, event)).toBe("apply");
      projection = applyEnvelope(projection, event).projection;
    }
    expect(projection.events).toHaveLength(120);
    expect(projection.seenEventIds).toHaveLength(512);
    console.info(JSON.stringify({ benchmark: "wave6-local", editUpdates: broad,
      treeSelectorInvalidations: treeSelections, events: 10000,
      retainedEvents: projection.events.length, elapsedMs: Math.round(performance.now() - start) }));
  } finally {
    unsubscribe();
    useStore.setState(before);
  }
});
