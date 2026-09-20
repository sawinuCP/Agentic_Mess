// Gated-action waiter (UI2): inline per-action approval for Command Center
// dispatches. The executor awaits decideGate(); entry buttons resolve it.
// Pure logic (no React/DOM) — unit-tested in node.

import type { PlanAction } from "../intent/plan";

export type GateDecision = "run" | "skip" | "cancel";

interface Waiter {
  action: PlanAction;
  resolve: (decision: GateDecision) => void;
}

const waiters = new Map<number, Waiter>();

/** Executor side: pause until the user approves, skips, or cancels. */
export function awaitGate(entryId: number, action: PlanAction): Promise<GateDecision> {
  return new Promise<GateDecision>((resolve) => {
    waiters.set(entryId, { action, resolve });
  });
}

/** Button side: resolve the pending waiter, if any. No-op when absent. */
export function decideGate(entryId: number, decision: GateDecision): boolean {
  const waiter = waiters.get(entryId);
  if (!waiter) return false;
  waiters.delete(entryId);
  waiter.resolve(decision);
  return true;
}

/** Button side: which action (if any) currently awaits a decision. */
export function pendingGate(entryId: number): PlanAction | null {
  return waiters.get(entryId)?.action ?? null;
}

/** Executor side: drop the waiter without resolving (entry reset). */
export function clearGate(entryId: number): void {
  waiters.delete(entryId);
}
