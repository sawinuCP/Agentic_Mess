import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../api/client";
import { useStore, type FileTab } from "./store";

vi.mock("../api/client", () => ({
  openProject: vi.fn(), getTree: vi.fn(), gitStatus: vi.fn(),
  getProjectToolchains: vi.fn(), createTerminalSession: vi.fn(),
  ApiError: class extends Error {},
}));
const tab: FileTab = { kind: "file", path: "a.ts", content: "changed", savedContent: "old",
  isBinary: false, language: "typescript" };

describe("workspace safety", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useStore.setState({ tabs: [], project: null, terminalIds: [], activeTerminal: null });
  });
  it("rejects a project switch before contacting the API if any buffer is dirty", async () => {
    useStore.setState({ tabs: [tab] });
    await expect(useStore.getState().openProject("C:/other")).rejects.toThrow("Save or close");
    expect(api.openProject).not.toHaveBeenCalled();
    expect(useStore.getState().tabs[0]).toBe(tab);
  });
  it("checks edits made while project opening was pending", async () => {
    vi.mocked(api.openProject).mockImplementation(async () => {
      useStore.setState({ tabs: [tab] });
      return { id: "other", name: "Other", root_path: "C:/other", default_branch: "main" };
    });
    await expect(useStore.getState().openProject("C:/other")).rejects.toThrow("file changed");
    expect(useStore.getState().project).toBeNull();
    expect(useStore.getState().tabs).toEqual([tab]);
  });
  it("does not let an older project-open response replace a newer selection", async () => {
    const older = { id: "older", name: "Older", root_path: "C:/older", default_branch: "main" };
    const newer = { ...older, id: "newer", name: "Newer", root_path: "C:/newer" };
    let resolveOlder!: (value: typeof older) => void;
    vi.mocked(api.openProject).mockImplementationOnce(() => new Promise((resolve) => {
      resolveOlder = resolve;
    })).mockResolvedValueOnce(newer);
    vi.mocked(api.getTree).mockResolvedValue([]);
    vi.mocked(api.createTerminalSession).mockResolvedValue({ id: "new-terminal", cwd: "C:/newer" });
    const pending = useStore.getState().openProject("C:/older");
    await useStore.getState().openProject("C:/newer");
    resolveOlder(older);
    await pending;
    expect(useStore.getState().project).toEqual(newer);
    expect(api.createTerminalSession).toHaveBeenCalledTimes(1);
  });
  it("does not attach a late terminal response to a different project", async () => {
    useStore.setState({ project: { id: "old", name: "Old", root_path: "C:/old", default_branch: "main" } });
    vi.mocked(api.createTerminalSession).mockImplementation(async () => {
      useStore.setState({ project: null });
      return { id: "stale", cwd: "C:/old" } as Awaited<ReturnType<typeof api.createTerminalSession>>;
    });
    await useStore.getState().createTerminal();
    expect(useStore.getState().terminalIds).toEqual([]);
  });
});
