import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../api/client";
import { streamEvents } from "../api/sse";
import type { AgentInfo } from "../types";
import { useOffice } from "./officeStore";

vi.mock("../api/client", () => ({
  listAgents: vi.fn(), listTasks: vi.fn(), listHitl: vi.fn(),
  listEvents: vi.fn(), getTraceability: vi.fn(),
}));
vi.mock("../api/sse", () => ({ streamEvents: vi.fn() }));

const flush = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };
const agent = (project: string): AgentInfo => ({
  id: project + "-agent", project_id: project, name: project,
  role: "worker", model: null, capabilities: [], state: "running",
});

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal("window", globalThis);
  vi.mocked(api.listAgents).mockImplementation(async (project) => [agent(project)]);
  vi.mocked(api.listTasks).mockResolvedValue([]);
  vi.mocked(api.listHitl).mockResolvedValue([]);
  vi.mocked(api.listEvents).mockResolvedValue([]);
  vi.mocked(api.getTraceability).mockResolvedValue({
    project_id: "p", generated_at: "", requirements: [], orphan_task_ids: [],
    scope_drift: false, coverage: { total: 0, verified: 0, failed: 0, unknown: 0 },
  });
  vi.mocked(streamEvents).mockImplementation((_project, _since, _handlers, signal) => {
    let finish!: () => void;
    const done = new Promise<void>((resolve) => { finish = resolve; });
    signal.addEventListener("abort", finish, { once: true });
    return { done, abort: finish };
  });
});
afterEach(async () => {
  useOffice.getState().stop();
  await flush();
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("office connection lifecycle", () => {
  it("keeps one stream loop through disconnect and restart and ignores old callbacks", async () => {
    useOffice.getState().start("first");
    await flush();
    const old = vi.mocked(streamEvents).mock.calls[0];
    old[2].onControl({ kind: "DISCONNECT" });
    await flush();
    expect(useOffice.getState().connectionState).toBe("reconnecting");
    useOffice.getState().start("second");
    await flush();
    expect(streamEvents).toHaveBeenCalledTimes(2);
    old[2].onControl({ kind: "GATEWAY_STATUS", state: "degraded" });
    expect(useOffice.getState().gatewayMode).toBe("unknown");
    await vi.advanceTimersByTimeAsync(20_000);
    expect(streamEvents).toHaveBeenCalledTimes(2);
    const current = vi.mocked(streamEvents).mock.calls[1];
    current[2].onControl({ kind: "GATEWAY_STATUS", state: "live" });
    expect(useOffice.getState().connectionState).toBe("live");
    current[2].onControl({ kind: "DISCONNECT" });
    await flush();
    await vi.advanceTimersByTimeAsync(1000);
    expect(streamEvents).toHaveBeenCalledTimes(3);
    useOffice.getState().stop();
    await vi.advanceTimersByTimeAsync(20_000);
    expect(streamEvents).toHaveBeenCalledTimes(3);
  });

  it("captures the replay cursor before fetching authoritative entities", async () => {
    let finishEvents!: (events: []) => void;
    vi.mocked(api.listEvents).mockImplementation(() => new Promise((resolve) => { finishEvents = resolve; }));
    useOffice.getState().start("cursor-test");
    await flush();
    expect(api.listAgents).not.toHaveBeenCalled();
    finishEvents([]);
    await flush();
    expect(api.listAgents).toHaveBeenCalledOnce();
    expect(vi.mocked(streamEvents).mock.calls[0][1]).toBe(0);
  });

  it("coalesces simultaneous resync requests", async () => {
    useOffice.getState().start("coalesce");
    await flush();
    vi.mocked(api.listEvents).mockClear();
    let finishEvents!: (events: []) => void;
    vi.mocked(api.listEvents).mockImplementation(() => new Promise((resolve) => { finishEvents = resolve; }));
    const first = useOffice.getState().resync();
    const second = useOffice.getState().resync();
    expect(api.listEvents).toHaveBeenCalledOnce();
    finishEvents([]);
    await Promise.all([first, second]);
  });
  it("does not let an old project snapshot overwrite the new project", async () => {
    let finishOld!: (agents: AgentInfo[]) => void;
    vi.mocked(api.listAgents).mockImplementation((project) => project === "old"
      ? new Promise((resolve) => { finishOld = resolve; })
      : Promise.resolve([agent(project)]));
    useOffice.getState().start("old");
    await flush();
    useOffice.getState().start("new");
    await flush();
    finishOld([agent("old")]);
    await flush();
    expect(useOffice.getState().projectId).toBe("new");
    expect(useOffice.getState().agents[0].project_id).toBe("new");
    expect(streamEvents).toHaveBeenCalledTimes(1);
    expect(vi.mocked(streamEvents).mock.calls[0][0]).toBe("new");
  });
});
