// Requirements primary surface (UI4): compact rows answering what's
// satisfied / in progress / unproven, with a detail pane carrying the full
// verification narrative. Data: traceability report (office store) joined
// with RequirementInfo descriptions. Selection syncs with the office store
// both ways (graph/detail jumps land here).

import { useEffect, useMemo, useState } from "react";

import { listRequirements } from "../../api/client";
import { errorMessage } from "../../api/errors";
import type { RequirementInfo, TaskInfo, TraceabilityRequirement } from "../../types";
import { useOffice } from "../../state/officeStore";
import { useStore } from "../../state/store";
import { UiState } from "../shell/UiState";
import { normalizeStatus, workState } from "../../requirements/requirementModel";
import NewRequirementDialog from "./NewRequirementDialog";
import RequirementDetail from "./RequirementDetail";
import { VerificationPill } from "./VerificationReceipt";

const ROW_TONE: Record<string, string> = {
  VERIFIED: "ok",
  FAILED: "down",
  UNKNOWN: "warn",
};

function RequirementRow({ requirement, tasks, selected, onSelect }: {
  requirement: TraceabilityRequirement;
  tasks: TaskInfo[];
  selected: boolean;
  onSelect: () => void;
}) {
  const normalized = normalizeStatus(requirement.status);
  const linked = tasks.filter((t) => requirement.task_ids.includes(t.id));
  const work = workState(linked);
  const mandatory = requirement.criteria.filter((c) => c.mandatory);
  const verifiedCount = requirement.criteria.filter((c) => c.state === "verified").length;
  return (
    <li className={`req-row ${selected ? "selected" : ""}`}>
      <button
        className="req-row-main"
        aria-current={selected || undefined}
        aria-label={`${requirement.title}, ${normalized}, ${work.label}`}
        onClick={onSelect}
      >
        <span className="row spread">
          <span className="strong wrap-break">{requirement.title}</span>
          <span className={`state-pill ${ROW_TONE[normalized]}`}>
            <span aria-hidden="true">{normalized === "VERIFIED" ? "✓ " : normalized === "FAILED" ? "✗ " : "! "}</span>
            {normalized}
          </span>
        </span>
        <span className="small muted">
          {work.label}
          {mandatory.length > 0 ? ` · criteria ${verifiedCount}/${requirement.criteria.length}` : ""}
          {` · ${requirement.priority}`}
        </span>
      </button>
    </li>
  );
}

export default function RequirementsView() {
  const project = useStore((s) => s.project);
  const setWorkspace = useStore((s) => s.set);
  const traceability = useOffice((s) => s.traceability);
  const tasks = useOffice((s) => s.tasks);
  const completionBusy = useOffice((s) => s.completionBusy);
  const generateCompletion = useOffice((s) => s.generateCompletion);
  const selectedRequirementId = useOffice((s) => s.selectedRequirementId);
  const setOffice = useOffice((s) => s.set);
  const [infos, setInfos] = useState<RequirementInfo[] | null>(null);
  const [infosError, setInfosError] = useState<string | null>(null);
  const [reloadTick, setReloadTick] = useState(0);
  const [creating, setCreating] = useState(false);
  const [statusFilter, setStatusFilter] = useState<"all" | "VERIFIED" | "FAILED" | "UNKNOWN">("all");

  useEffect(() => {
    if (!project) return;
    let active = true;
    setInfos(null);
    setInfosError(null);
    listRequirements(project.id)
      .then((rows) => { if (active) setInfos(rows); })
      .catch((err: unknown) => { if (active) setInfosError(errorMessage(err)); });
    return () => { active = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project?.id, reloadTick]);

  const requirements = useMemo(
    () => (traceability?.requirements ?? []).filter(
      (r) => statusFilter === "all" || normalizeStatus(r.status) === statusFilter,
    ),
    [traceability, statusFilter],
  );
  const selected = (traceability?.requirements ?? []).find((r) => r.id === selectedRequirementId)
    ?? requirements[0] ?? null;
  const infoById = useMemo(() => new Map((infos ?? []).map((i) => [i.id, i])), [infos]);
  const coverage = traceability?.coverage;
  const allowed = traceability?.completion_allowed;

  if (!project) {
    return <div className="req-empty muted">Open a project to see requirements.</div>;
  }

  return (
    <div className="req-view">
      <header className="req-header">
        <div className="row spread">
          <span className="text-heading">Requirements</span>
          <button className="btn btn-small" onClick={() => setCreating(true)}>
            New requirement
          </button>
        </div>
        <div className="small muted row wrap gap4">
          {coverage ? (
            <span>
              {coverage.verified} verified · {coverage.failed} failed · {coverage.unknown} unknown · {coverage.total} total
            </span>
          ) : (
            <span>Waiting for traceability snapshot…</span>
          )}
          {allowed !== undefined && (
            <span className={`state-pill ${allowed ? "ok" : "warn"}`}>
              gate {allowed ? "allowed" : "blocked"}
            </span>
          )}
          <button
            className="btn btn-small"
            disabled={completionBusy}
            title="Request the evidence-backed completion report"
            onClick={() => void generateCompletion()}
          >
            {completionBusy ? "Requesting…" : "Request completion report"}
          </button>
        </div>
        {(traceability?.blockers ?? []).length > 0 && (
          <div className="small stack">
            {(traceability?.blockers ?? []).map((blocker) => (
              <span key={blocker} className="gate-blocker">⛔ {blocker}</span>
            ))}
          </div>
        )}
        <div className="row wrap gap4" role="group" aria-label="Filter requirements by verification state">
          {(["all", "VERIFIED", "FAILED", "UNKNOWN"] as const).map((state) => (
            <button
              key={state}
              className={`chip ${statusFilter === state ? "active" : ""}`}
              aria-pressed={statusFilter === state}
              onClick={() => setStatusFilter(state)}
            >
              {state === "all" ? "All" : state.charAt(0) + state.slice(1).toLowerCase()}
            </button>
          ))}
        </div>
      </header>
      {infosError && (
        <UiState title="Requirement details unavailable" error retry={() => setReloadTick((n) => n + 1)}>
          {infosError} — verification states still load from traceability.
        </UiState>
      )}
      <div className="req-body">
        <ul className="plain-list req-list" aria-label={`${requirements.length} requirements`}>
          {requirements.length === 0 && (
            <li className="muted small pad">
              {traceability && (traceability.requirements ?? []).length === 0 ? (
                <span>
                  No requirements yet. Requirements are registered by planning flows,{" "}
                  or <button className="link" onClick={() => setCreating(true)}>create the first one</button>.
                </span>
              ) : (
                <span role="status">No requirements match this filter.</span>
              )}
            </li>
          )}
          {requirements.map((requirement) => (
            <RequirementRow
              key={requirement.id}
              requirement={requirement}
              tasks={tasks}
              selected={selected?.id === requirement.id}
              onSelect={() => setOffice({ selectedRequirementId: requirement.id })}
            />
          ))}
        </ul>
        <div className="req-detail">
          {!selected && <p className="muted small pad">Select a requirement to inspect its verification chain.</p>}
          {selected && (
            <div key={selected.id}>
              <div className="row spread">
                <VerificationPill status={selected.status} />
                <span className="small muted mono" title={selected.id}>REQ {selected.id.slice(0, 8)}</span>
              </div>
              <div className="row gap4">
                <button
                  className="btn btn-small"
                  title="Open the execution graph focused on this requirement's causality"
                  onClick={() => {
                    setOffice({ selectedRequirementId: selected.id, selectedTaskId: null, selectedAgentId: null });
                    setWorkspace({ view: "graph" });
                  }}
                >
                  Investigate in graph
                </button>
              </div>
              <RequirementDetail requirement={selected} info={infoById.get(selected.id)} />
            </div>
          )}
        </div>
      </div>
      {creating && <NewRequirementDialog onClose={() => setCreating(false)} />}
    </div>
  );
}
