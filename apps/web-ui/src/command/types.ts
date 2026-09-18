// Command Center shared types: conversation entries hold the intent, the
// plan, references, and labels only — never tool outputs, payload values,
// or secrets. Bounded to 20 entries in the workspace store so context
// survives view switches (functions are in-memory only, never persisted).

import type { EngineeringIntent } from "../intent/classify";
import type { PlanAction, PlanPreview } from "../intent/plan";

export interface FindingRef {
  label: string;
  run: () => void;
}

export interface Finding {
  kind: string;
  title: string;
  detail: string;
  refs: FindingRef[];
}

export interface DispatchResult {
  label: string;
  ok: boolean;
  detail: string;
  taskId?: string;
  reviewVerdict?: string;
}

export interface CenterEntry {
  id: number;
  request: string;
  intent: EngineeringIntent;
  plan: PlanPreview;
  status: "preview" | "running" | "done" | "error";
  statusText: string;
  findings: Finding[];
  dispatches: DispatchResult[];
  error: string | null;
}

export type { PlanAction };
