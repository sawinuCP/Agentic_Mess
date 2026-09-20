// Unit tests for the gated-action waiter (pure logic, node environment).
import { describe, expect, it } from "vitest";

import { awaitGate, clearGate, decideGate, pendingGate } from "./gate";
import type { PlanAction } from "../intent/plan";

const action = (id: string): PlanAction => ({ id: id as PlanAction["id"], label: id, detail: "", gated: true });

describe("gate", () => {
  it("resolves run/skip/cancel from entry buttons", async () => {
    const pending = awaitGate(1, action("create_task"));
    expect(pendingGate(1)).toMatchObject({ id: "create_task" });
    expect(decideGate(1, "run")).toBe(true);
    await expect(pending).resolves.toBe("run");
    expect(pendingGate(1)).toBeNull();
  });

  it("replaces the waiter when a new action gates", async () => {
    let first = "unresolved";
    void awaitGate(2, action("a")).then((d) => { first = d; });
    const second = awaitGate(2, action("b"));
    expect(pendingGate(2)).toMatchObject({ id: "b" });
    decideGate(2, "skip");
    await expect(second).resolves.toBe("skip");
    expect(first).toBe("unresolved");
    clearGate(2);
  });

  it("no-ops when nothing awaits", () => {
    expect(decideGate(99, "run")).toBe(false);
    expect(pendingGate(99)).toBeNull();
    clearGate(99);
  });
});
