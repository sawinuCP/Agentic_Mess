// Shared bulk execution fan-out (Wave 7 completion): one confirmation over
// the existing per-task endpoints, sequential calls, per-task reporting,
// single resync. Used by the Office header (whole project) and the agent
// detail panel (that agent's owned tasks). Eligibility always re-derives
// from the same per-task availability builder.

import { useState } from "react";

import { cancelTask, controlTask } from "../api/client";
import { errorMessage } from "../api/errors";
import { confirmAction } from "../components/shell/confirm";
import { BULK_LABEL, bulkConfirm, bulkEligible } from "./selectors";
import type { TaskInfo } from "../types";
import { useOffice } from "../state/officeStore";

export type BulkAction = "pause" | "resume" | "cancel";

export function useBulkAction() {
  const [bulkBusy, setBulkBusy] = useState(false);
  const refresh = useOffice((s) => s.refresh);
  const setOffice = useOffice((s) => s.set);

  const runBulk = async (
    action: BulkAction,
    candidates: TaskInfo[],
    context?: string,
  ): Promise<void> => {
    if (bulkBusy) return;
    const targets = bulkEligible(candidates, action);
    if (targets.length === 0) return;
    const question = context
      ? `${context}: ${bulkConfirm(action, targets.length)}`
      : bulkConfirm(action, targets.length);
    const confirmed = await confirmAction({
      title: `${BULK_LABEL[action]} ${targets.length} task${targets.length === 1 ? "" : "s"}?`,
      body: question,
      confirmLabel: BULK_LABEL[action],
      danger: action === "cancel",
    });
    if (!confirmed) return;
    setBulkBusy(true);
    let ok = 0;
    const failed: string[] = [];
    try {
      for (const target of targets) {
        try {
          if (action === "cancel") await cancelTask(target.id);
          else await controlTask(target.id, action);
          ok += 1;
        } catch (err) {
          failed.push(`${target.title}: ${errorMessage(err)}`);
        }
      }
      await refresh().catch(() => undefined);
      const done =
        action === "cancel"
          ? `Cancelled ${ok} of ${targets.length} tasks.`
          : `${BULK_LABEL[action]} signal sent to ${ok} of ${targets.length} tasks. Workflows apply it at safe checkpoints.`;
      setOffice({
        notice: failed.length === 0 ? `${done} Refreshing state.` : `${done} Failed: ${failed.join("; ")}`,
      });
    } finally {
      setBulkBusy(false);
    }
  };

  return { bulkBusy, runBulk };
}
