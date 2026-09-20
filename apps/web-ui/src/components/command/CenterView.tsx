// AI Command Center (Wave 10): deterministic engineering command surface.
//
// No chat endpoint exists, so there is no generative chat here: requests are
// classified into structured intents over existing capabilities, context is
// assembled within budgets and previewed, plans are reviewed before anything
// consequential runs, and execution hands off to live surfaces. Zero model
// calls originate from this view (model-backed reviews are explicit,
// confirmed, and cost-labeled).

import { useEffect, useMemo, useRef, useState } from "react";

import {
  cancelTask,
  controlTask,
  createTask,
  fileSymbols,
  getCosts,
  getDiagnostics,
  researchFetch,
  researchSearch,
  retrieveRelated,
  runReview,
  searchFiles,
  searchSymbols,
  type RetrievalHit,
} from "../../api/client";
import { errorMessage } from "../../api/errors";
import { assembleContext } from "../../context/assemble";
import { awaitGate, clearGate } from "../../command/gate";
import { classifyIntent, type ClassifyContext, type EngineeringIntent } from "../../intent/classify";
import { planFor, type PlanAction } from "../../intent/plan";
import { extractIdentifiers } from "../../intent/queries";
import type { CenterEntry, DispatchResult, Finding } from "../../command/types";
import { runningAgents, useOffice } from "../../state/officeStore";
import { useStore } from "../../state/store";
import type { SymbolInfo } from "../../types";
import { confirmAction } from "../shell/confirm";
import { StatusLabel } from "../shell/UiState";
import ApprovalInline from "./ApprovalInline";
import ArtifactPreview from "./ArtifactPreview";
import CompletionReceipt from "./CompletionReceipt";
import { PhaseBadge } from "./EntryPhase";
import NeedsYou from "./NeedsYou";
import PlanPreviewView from "./PlanPreviewView";

let entrySeq = 0;

const DRAFT_KEY = "harness.center.draft";

function modeOf(intent: EngineeringIntent): string {
  const s = intent.scope;
  if (s.taskId && (intent.intentType === "fix_failure" || intent.intentType.startsWith("control") || intent.intentType === "start_execution")) return "Execution";
  if (s.requirementId) return "Requirement";
  if (s.filePath) return intent.intentType === "fix_failure" || s.hasFailureOutput ? "Error" : "Code";
  if (s.agentId) return "Agent";
  if (s.taskId) return "Execution";
  return "Project";
}

export default function CenterView() {
  const project = useStore((s) => s.project);
  const tabs = useStore((s) => s.tabs);
  const activePath = useStore((s) => s.activePath);
  const selection = useStore((s) => s.selection);
  const output = useStore((s) => s.output);
  const toolchains = useStore((s) => s.toolchains);
  const centerPrefill = useStore((s) => s.centerPrefill);
  const centerFocusTick = useStore((s) => s.centerFocusTick);
  const setWorkspace = useStore((s) => s.set);
  const runTool = useStore((s) => s.runTool);
  const openFile = useStore((s) => s.openFile);
  const agents = useOffice((s) => s.agents);
  const tasks = useOffice((s) => s.tasks);
  const events = useOffice((s) => s.events);
  const traceability = useOffice((s) => s.traceability);
  const officeTaskId = useOffice((s) => s.selectedTaskId);
  const officeAgentId = useOffice((s) => s.selectedAgentId);
  const officeReqId = useOffice((s) => s.selectedRequirementId);
  const pendingApprovals = useOffice((s) => s.hitl.filter((h) => h.status === "pending").length);

  const [input, setInput] = useState("");
  const entries = useStore((s) => s.centerEntries);
  const reqOverride = useStore((s) => s.centerReq);
  const taskOverride = useStore((s) => s.centerTask);
  const agentOverride = useStore((s) => s.centerAgent);
  const [costLine, setCostLine] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const pendingBranchRef = useRef<number | null>(null);
  const [, setTick] = useState(0);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);
  useEffect(() => {
    if (centerFocusTick > 0) inputRef.current?.focus();
  }, [centerFocusTick]);
  // Draft + tick clock: the draft survives unmounts; relative times refresh.
  useEffect(() => {
    try {
      const draft = localStorage.getItem(DRAFT_KEY);
      if (draft) setInput(draft);
    } catch {
      // storage unavailable — start empty
    }
    const clock = window.setInterval(() => setTick((n) => n + 1), 30000);
    return () => window.clearInterval(clock);
  }, []);
  useEffect(() => {
    try {
      if (input) localStorage.setItem(DRAFT_KEY, input);
      else localStorage.removeItem(DRAFT_KEY);
    } catch {
      // storage unavailable — draft simply isn't persisted
    }
  }, [input]);
  useEffect(() => {
    if (centerPrefill) {
      setInput(centerPrefill);
      setWorkspace({ centerPrefill: null });
      inputRef.current?.focus();
    }
  }, [centerPrefill, setWorkspace]);
  useEffect(() => {
    if (!project) return;
    let active = true;
    getCosts(project.id)
      .then((c) => {
        if (!active) return;
        const k = c.total_tokens >= 1000 ? `${(c.total_tokens / 1000).toFixed(1)}k` : `${c.total_tokens}`;
        setCostLine(`${c.invocations} model calls · ${k} tokens (budget ${c.budget_tokens_per_task}/task)`);
      })
      .catch(() => { if (active) setCostLine(null); });
    return () => { active = false; };
  }, [project]);

  const activeTab = tabs.find((t) => t.kind === "file" && t.path === activePath && !t.isBinary);
  const activeFile = activeTab && activeTab.kind === "file" ? activeTab : null;
  const git = useStore((s) => s.git);
  const failedOfficeTask = tasks.find((t) => t.status === "failed") ?? null;
  const failedOutput = output && output.exit_code !== 0 && output.exit_code !== null ? output : null;
  const changedCount = git?.entries.length ?? 0;
  const [previewArtifactId, setPreviewArtifactId] = useState<string | null>(null);

  const buildCtx = (): ClassifyContext => ({
    projectId: project?.id ?? null,
    requirementId: reqOverride || officeReqId,
    taskId: taskOverride || officeTaskId,
    agentId: agentOverride || officeAgentId,
    filePath: selection?.path ?? activeFile?.path ?? null,
    selectionChars: selection?.text.length ?? 0,
    selectionLines: selection ? selection.endLine - selection.startLine + 1 : 0,
    hasFailedTask: failedOfficeTask !== null || tasks.some((t) => t.status === "failed"),
    hasFailureOutput: failedOutput !== null,
  });

  const scopeSource = selection
    ? `selection L${selection.startLine}–L${selection.endLine} in ${selection.path.split("/").pop()} (selection wins over open file)`
    : activeFile
      ? `open file ${activeFile.path.split("/").pop()}`
      : (reqOverride || officeReqId || taskOverride || officeTaskId || agentOverride || officeAgentId)
        ? "office selection"
        : "project";

  const scopeChips = useMemo(() => {
    const chips: string[] = [];
    if (project) chips.push(`project ${project.name}`);
    if (reqOverride || officeReqId) chips.push("requirement selected");
    if (taskOverride || officeTaskId) chips.push("task selected");
    if (agentOverride || officeAgentId) chips.push("agent selected");
    if (selection) chips.push(`selection L${selection.startLine}–L${selection.endLine} in ${selection.path.split("/").pop()}`);
    else if (activeFile) chips.push(`file ${activeFile.path.split("/").pop()}`);
    if (failedOutput) chips.push(`last run: ${failedOutput.tool} exit ${failedOutput.exit_code}`);
    else if (failedOfficeTask) chips.push(`failed task: ${failedOfficeTask.title}`);
    if (pendingApprovals > 0) chips.push(`${pendingApprovals} approval(s) needed`);
    return chips;
  }, [project, reqOverride, officeReqId, taskOverride, officeTaskId, agentOverride, officeAgentId, selection, activeFile, failedOutput, failedOfficeTask, pendingApprovals]);

  const patchEntry = (id: number, patch: Partial<CenterEntry>): void => {
    const prev = useStore.getState().centerEntries;
    setWorkspace({ centerEntries: prev.map((e) => (e.id === id ? { ...e, ...patch } : e)) });
  };

  const pushEntry = (entry: CenterEntry): void => {
    const prev = useStore.getState().centerEntries;
    setWorkspace({ centerEntries: [entry, ...prev].slice(0, 20) });
  };

  const runIntelAction = async (
    entry: CenterEntry,
    action: PlanAction,
  ): Promise<Finding[]> => {
    const proj = project;
    if (!proj) throw new Error("Open a project first.");
    const scope = entry.intent.scope;
    const out: Finding[] = [];
    const openJump = (path: string, line?: number): { label: string; run: () => void } => ({
      label: `${path.split("/").pop()}${line ? `:${line}` : ""}`,
      run: () => void openFile(path, line).catch((err: unknown) => setWorkspace({ notice: errorMessage(err) })),
    });
    if (action.id === "fetch_context") {
      const fileContent = activeFile?.content ?? "";
      const symbols = scope.filePath
        ? await fileSymbols(proj.id, scope.filePath).catch((): SymbolInfo[] => [])
        : [];
      const snapshot = assembleContext({
        actionLabel: entry.plan.goal,
        scopeLabel: scope.filePath ?? scope.requirementId ?? scope.taskId ?? scope.agentId ?? "project",
        safetyNote: null,
        entityLines: [],
        requirementLine: scope.requirementId ? `requirement ${scope.requirementId}` : null,
        filePath: scope.filePath,
        fileContent,
        selection: selection && selection.path === scope.filePath
          ? { startLine: selection.startLine, endLine: selection.endLine, text: selection.text }
          : null,
        symbols: symbols.map((s) => ({ name: s.name, kind: s.kind, line: s.start_line })),
        relatedTests: [],
        executionLines: tasks.filter((t) => ["running", "blocked", "failed"].includes(t.status)).slice(0, 5).map((t) => `${t.title} (${t.status})`),
        agentLines: [`${runningAgents(agents).length} agents running`],
        dependencyLines: [],
        recentEvents: events.slice(0, 10).map((e) => `${e.event_type} ${new Date(e.occurred_at).toLocaleTimeString()}`),
        attemptLines: [],
        artifactRefs: [],
      });
      out.push({
        kind: "context",
        title: `Context assembled (${snapshot.totalChars} chars${snapshot.withinBudget ? "" : ", over budget"})`,
        detail: [...snapshot.t0, ...snapshot.t1].join(" · "),
        refs: scope.filePath ? [openJump(scope.filePath)] : [],
      });
      if (snapshot.truncated.length > 0) {
        out.push({ kind: "context", title: "Budget notes", detail: snapshot.truncated.join("; "), refs: [] });
      }
    } else if (action.id === "query_symbols") {
      const queries = extractIdentifiers(entry.request);
      const base = scope.filePath ? scope.filePath.split("/").pop()?.split(".")[0] ?? "" : "";
      const terms = [...new Set([base, ...queries])].filter(Boolean).slice(0, 3);
      const hits: SymbolInfo[] = [];
      for (const term of terms) {
        const found = await searchSymbols(proj.id, term, 10).catch((): SymbolInfo[] => []);
        for (const s of found) {
          if (hits.length < 12 && !hits.some((h) => h.id === s.id)) hits.push(s);
        }
      }
      out.push({
        kind: "symbols",
        title: hits.length > 0 ? `${hits.length} symbols` : "No symbols matched",
        detail: terms.length > 0 ? `queries: ${terms.join(", ")}` : "no searchable identifiers in scope",
        refs: hits.map((s) => ({
          label: `${s.name} (${s.kind})`,
          run: () => void openFile(s.path, s.start_line).catch((err: unknown) => setWorkspace({ notice: errorMessage(err) })),
        })),
      });
    } else if (action.id === "query_search_files") {
      const queries = extractIdentifiers(entry.request);
      const matches: { path: string; line: number }[] = [];
      for (const term of queries) {
        const found = await searchFiles(proj.id, { q: term }).catch(() => []);
        for (const m of found) {
          if (matches.length < 12 && !matches.some((x) => x.path === m.path && x.line === m.line)) {
            matches.push({ path: m.path, line: m.line });
          }
        }
      }
      out.push({
        kind: "references",
        title: matches.length > 0 ? `${matches.length} references` : "No references found",
        detail: queries.length > 0 ? `queries: ${queries.join(", ")}` : "no searchable identifiers in scope",
        refs: matches.map((m) => openJump(m.path, m.line)),
      });
    } else if (action.id === "query_retrieve") {
      const res = await retrieveRelated(proj.id, entry.request.slice(0, 200), 6).catch(() => null);
      const hits: RetrievalHit[] = res?.hits ?? [];
      out.push({
        kind: "retrieve",
        title: hits.length > 0 ? `${hits.length} related results (same ranking agents see)` : "No related code found",
        detail: hits.map((h) => `${h.name} (${h.matched} ${h.score.toFixed(2)})`).join("; "),
        refs: hits.map((h) => openJump(h.path, h.start_line)),
      });
    } else if (action.id === "read_file") {
      if (!scope.filePath) throw new Error("No file in scope.");
      if (scope.filePath === activePath) {
        out.push({ kind: "file", title: `${scope.filePath.split("/").pop()} already open`, detail: "editor preserves workspace; no navigation needed", refs: [] });
      } else {
        await openFile(scope.filePath);
        out.push({ kind: "file", title: `Opened ${scope.filePath.split("/").pop()}`, detail: "editor preserves workspace", refs: [] });
      }
    } else if (action.id === "show_traceability") {
      const covered = traceability?.coverage;
      out.push({
        kind: "coverage",
        title: covered
          ? `${covered.verified}/${covered.total} requirements verified`
          : "No traceability snapshot loaded",
        detail: "from the requirement overseer, not task completion",
        refs: [{ label: "Open oversight", run: () => { setWorkspace({ view: "office", sidebarOpen: true }); useOffice.getState().set({ tab: "oversight" }); } }],
      });
    } else if (action.id === "show_health") {
      const diag = await getDiagnostics().catch(() => null);
      const langs = toolchains?.languages.map((l) => l.name).join(", ") ?? "none detected";
      out.push({
        kind: "health",
        title: diag ? `API v${diag.app.version} · ${diag.app.environment}` : "Diagnostics unavailable",
        detail: `languages: ${langs} · git: ${useStore.getState().tabs.length} tabs open`,
        refs: [{ label: "Open diagnostics", run: () => setWorkspace({ diagnosticsOpen: true }) }],
      });
    } else if (action.id === "show_costs") {
      const costs = await getCosts(proj.id).catch(() => null);
      out.push({
        kind: "costs",
        title: costs ? `${costs.invocations} calls · ${costs.total_tokens} tokens` : "Ledger unavailable",
        detail: costs ? `budget ${costs.budget_tokens_per_task} tokens/task` : "",
        refs: [],
      });
    } else if (action.id === "navigate") {
      const surface = entry.intent.surface ?? "";
      if (surface === "office") {
        if (entry.intent.request.includes("approv") || scope.requirementId) {
          setWorkspace({ view: "office", sidebarOpen: true });
          useOffice.getState().set({ tab: "oversight" });
        } else {
          setWorkspace({ view: "office", sidebarOpen: true });
        }
      } else if (surface === "graph" || surface === "timeline" || surface === "requirements" || surface === "terminal") {
        if (surface === "graph") setWorkspace({ view: "graph", sidebarOpen: true });
        else if (surface === "timeline") { setWorkspace({ view: "office", sidebarOpen: true }); useOffice.getState().set({ tab: "timeline" }); }
        else if (surface === "requirements") { setWorkspace({ view: "office", sidebarOpen: true }); useOffice.getState().set({ tab: "oversight" }); }
        else setWorkspace({ panelOpen: true, panelTab: "terminal" });
      }
      out.push({ kind: "navigate", title: `Opened ${surface || "workspace"}`, detail: "scope preserved", refs: [] });
    }
    return out;
  };

  const runDispatchAction = async (
    entry: CenterEntry,
    action: PlanAction,
  ): Promise<DispatchResult[]> => {
    const proj = project;
    if (!proj) throw new Error("Open a project first.");
    const scope = entry.intent.scope;
    if (action.id === "create_task") {
      const created = await createTask(proj.id, {
        title: entry.request.slice(0, 280) || "Untitled task",
        request: entry.request,
        requirement_id: scope.requirementId,
      });
      await useOffice.getState().resync().catch(() => undefined);
      return [{ label: `Task created: ${created.title}`, ok: true, detail: `status ${created.status} · watch it live in the Office`, taskId: created.id }];
    }
    if (action.id === "dispatch_execute" || action.id === "dispatch_control") {
      const taskId = scope.taskId;
      if (!taskId) throw new Error("No task in scope.");
      const kind = action.id === "dispatch_execute" ? "execute" : entry.intent.control;
      if (!kind) throw new Error("No control signal resolved.");
      if (kind === "stop") {
        await cancelTask(taskId);
      } else if (kind === "retry" || kind === "start") {
        await controlTask(taskId, "execute");
      } else {
        await controlTask(taskId, kind);
      }
      await useOffice.getState().resync().catch(() => undefined);
      return [{ label: `Signal acknowledged for task`, ok: true, detail: "applied at a safe checkpoint; recorded status is authoritative", taskId }];
    }
    if (action.id === "dispatch_tool") {
      await runTool("test");
      const result = useStore.getState().output;
      return [{
        label: result && result.exit_code === 0 ? "Tests passed" : `Tests finished (exit ${result?.exit_code ?? "?"})`,
        ok: result?.exit_code === 0,
        detail: result ? `${result.duration_ms}ms · see output panel` : "no result recorded",
      }];
    }
    if (action.id === "dispatch_review") {
      const taskId = scope.taskId;
      if (!taskId) throw new Error("No task in scope to review.");
      const outcome = await runReview(taskId, {
        title: entry.request.slice(0, 200),
        proposal: entry.request,
      });
      return [{
        label: `Reviewers: ${outcome.verdict}`,
        ok: outcome.verdict === "approve" || outcome.verdict === "approved",
        detail: `${outcome.rationale} · model calls billed to the project ledger`,
        reviewVerdict: outcome.verdict,
      }];
    }
    return [];
  };

  const executeEntry = async (entry: CenterEntry): Promise<void> => {
    patchEntry(entry.id, { status: "running", statusText: "Working…", error: null, awaiting: null });
    try {
      const findings: Finding[] = [];
      for (const action of entry.plan.actions) {
        if (action.gated) continue;
        const produced = await runIntelAction(entry, action);
        findings.push(...produced);
        patchEntry(entry.id, { findings: [...findings] });
      }
      const gated = entry.plan.actions.filter((a) => a.gated);
      const dispatches: DispatchResult[] = [];
      for (const action of gated) {
        if (entry.intent.confirmationRequired) {
          patchEntry(entry.id, {
            awaiting: { actionId: action.id, label: action.label, detail: action.detail },
            statusText: `Awaiting approval: ${action.label}`,
          });
          const decision = await awaitGate(entry.id, action);
          patchEntry(entry.id, { awaiting: null });
          if (decision === "skip") {
            dispatches.push({ label: action.label, ok: false, detail: "Skipped: not approved." });
            patchEntry(entry.id, { dispatches: [...dispatches] });
            continue;
          }
          if (decision === "cancel") {
            dispatches.push({ label: action.label, ok: false, detail: "Cancelled: remaining steps not run." });
            patchEntry(entry.id, { dispatches: [...dispatches] });
            break;
          }
        }
        if (action.id === "dispatch_research_search") {
          if (!project) throw new Error("Open a project first.");
          const res = await researchSearch(project.id, entry.request.slice(0, 300), 5).catch((err: unknown) => {
            throw new Error(`Research search unavailable: ${errorMessage(err)}`);
          });
          const entryId = entry.id;
          const projectId = project.id;
          findings.push({
            kind: "research",
            title: res.results.length > 0 ? `${res.results.length} sources (provenance preserved)` : "No sources found",
            detail: "search only — fetching a source into the artifact store is a separate confirmed step",
            refs: res.results.slice(0, 5).map((r) => ({
              label: `Fetch: ${r.title.slice(0, 40)}`,
              run: () => {
                void confirmAction({
                  title: "Fetch this source into the project artifact store?",
                  body: r.url,
                  confirmLabel: "Fetch",
                }).then((ok) => {
                  if (!ok) return;
                  void researchFetch(projectId, r.url)
                  .then((fetched) => {
                    const prev = useStore.getState().centerEntries;
                    setWorkspace({ centerEntries: prev.map((e) => (e.id === entryId
                      ? {
                        ...e,
                        findings: [...e.findings, {
                          kind: "research-evidence",
                          title: `Fetched: ${fetched.title}`,
                          detail: `${fetched.excerpt} · artifact ${fetched.artifact_id.slice(0, 8)} · confidence ${fetched.confidence}`,
                          refs: [],
                          artifactId: fetched.artifact_id,
                        }],
                      }
                      : e)) });
                  })
                  .catch((err: unknown) => {
                    const prev = useStore.getState().centerEntries;
                    setWorkspace({ centerEntries: prev.map((e) => (e.id === entryId
                      ? { ...e, error: errorMessage(err) }
                      : e)) });
                  });
                });
              },
            })),
          });
          patchEntry(entry.id, { findings: [...findings] });
          continue;
        }
        const produced = await runDispatchAction(entry, action);
        dispatches.push(...produced);
        patchEntry(entry.id, { dispatches: [...dispatches] });
      }
      patchEntry(entry.id, {
        status: "done",
        statusText: dispatches.some((d) => !d.ok) ? "Completed with skipped steps." : "Completed.",
      });
    } catch (err) {
      clearGate(entry.id);
      patchEntry(entry.id, {
        status: "error",
        statusText: "Stopped on error.",
        error: err instanceof Error ? err.message : String(err),
        awaiting: null,
      });
    }
  };

  const submit = (text: string): void => {
    const request = text.trim();
    if (!request || !project) return;
    const normalized = request.toLowerCase().replace(/\s+/g, " ");
    const existing = useStore.getState().centerEntries.find(
      (e) => e.request.trim().toLowerCase().replace(/\s+/g, " ") === normalized,
    );
    const branchedFrom = pendingBranchRef.current;
    pendingBranchRef.current = null;
    if (existing && branchedFrom === null) {
      setWorkspace({ notice: `Already asked — see entry #${existing.id} above.` });
      return;
    }
    const ctx = buildCtx();
    const intent = classifyIntent(request, ctx);
    const plan = planFor(intent);
    const entry: CenterEntry = {
      id: ++entrySeq,
      request,
      intent,
      plan,
      status: "preview",
      statusText: intent.intentType === "unknown" || intent.intentType === "unsupported"
        ? "Needs input."
        : "Plan ready for review.",
      findings: [],
      dispatches: [],
      error: null,
      createdAt: new Date().toISOString(),
      branchedFrom,
      awaiting: null,
    };
    pushEntry(entry);
    setInput("");
    try {
      localStorage.removeItem(DRAFT_KEY);
    } catch {
      // storage unavailable — draft simply isn't persisted
    }
  };

  const branchEntry = (entry: CenterEntry): void => {
    const scope = entry.intent.scope;
    setWorkspace({
      centerReq: scope.requirementId ?? "",
      centerTask: scope.taskId ?? "",
      centerAgent: scope.agentId ?? "",
    });
    setInput(entry.request);
    pendingBranchRef.current = entry.id;
    setWorkspace({ notice: `Branched from #${entry.id} — scope restored, nothing re-executed.` });
    inputRef.current?.focus();
  };

  const modeOfEntry = (entry: CenterEntry): string => modeOf(entry.intent);

  return (
    <div className="command-center">
      <div className="graph-header">
        <span className="strong">Command Center</span>
        <span className="small muted">deterministic routing over existing capabilities · zero model calls from this view</span>
        <div className="status-spacer" />
        {costLine && <span className="small muted" title="Project model ledger">{costLine}</span>}
      </div>

      <div className="cc-context" aria-label="Current context">
        {scopeChips.length === 0 && <span className="small muted">No project open.</span>}
        {scopeChips.map((chip) => (
          <span key={chip} className="chip active">{chip}</span>
        ))}
        {changedCount > 0 && (
          <button
            className="chip"
            title="Open changed files"
            onClick={() => setWorkspace({ view: "git", sidebarOpen: true })}
          >
            {changedCount} file{changedCount === 1 ? "" : "s"} changed
          </button>
        )}
        <div className="row wrap gap4">
          <label className="small muted row gap4">
            Requirement
            <select className="text-input small" aria-label="Command scope: requirement" value={reqOverride} onChange={(e) => setWorkspace({ centerReq: e.target.value })}>
              <option value="">auto</option>
              {(traceability?.requirements ?? []).map((r) => (
                <option key={r.id} value={r.id}>{r.title}</option>
              ))}
            </select>
          </label>
          <label className="small muted row gap4">
            Task
            <select className="text-input small" aria-label="Command scope: task" value={taskOverride} onChange={(e) => setWorkspace({ centerTask: e.target.value })}>
              <option value="">auto</option>
              {tasks.map((t) => (
                <option key={t.id} value={t.id}>{t.title}</option>
              ))}
            </select>
          </label>
          <label className="small muted row gap4">
            Agent
            <select className="text-input small" aria-label="Command scope: agent" value={agentOverride} onChange={(e) => setWorkspace({ centerAgent: e.target.value })}>
              <option value="">auto</option>
              {agents.map((a) => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </select>
          </label>
        </div>
      </div>

      <form
        className="cc-input-row"
        onSubmit={(e) => { e.preventDefault(); submit(input); }}
      >
        <input
          ref={inputRef}
          className="text-input"
          aria-label="Engineering request"
          placeholder="Describe what to build — e.g. Implement OAuth, Fix this failure, Where is this used?"
          value={input}
          onChange={(e) => setInput(e.target.value)}
        />
        <button className="button" type="submit" disabled={!input.trim() || !project}>
          Ask
        </button>
      </form>
      {project && <p className="small muted pad">Scope: {scopeSource}.</p>}

      <NeedsYou />

      <div className="cc-entries" aria-label="Requests and results">
        {entries.length === 0 && (
          <div className="pad stack">
            <p className="muted small">
              Start from any context above. Requests are classified into structured intents;
              consequential actions always show a plan preview with approval first.
            </p>
            <div className="row wrap gap4" aria-label="Example requests">
              {[
                "Implement OAuth login with tests",
                "Fix the failing migration",
                "Explain the payment module",
                "Where is retry logic used?",
              ].map((example) => (
                <button key={example} className="btn btn-small" onClick={() => submit(example)}>
                  {example}
                </button>
              ))}
            </div>
          </div>
        )}
        {entries.map((entry) => (
          <article key={entry.id} className="cc-entry">
            <div className="row spread">
              <span className="strong">#{entry.id} {entry.request}</span>
              <span className="row gap4">
                <PhaseBadge entry={entry} tasks={tasks} />
                <span className="small muted" title={new Date(entry.createdAt).toLocaleString()}>
                  {modeOfEntry(entry)} · {relativeTime(entry.createdAt)}
                </span>
              </span>
            </div>
            {entry.branchedFrom !== null && (
              <div className="small muted">↳ branched from #{entry.branchedFrom} — scope restored, nothing re-executed.</div>
            )}
            <div className="small muted">
              Intent: <span className="mono">{entry.intent.intentType}</span> · confidence {entry.intent.confidence}
            </div>
            {entry.intent.clarifyPrompt && (
              <p className="small warn" role="note">{entry.intent.clarifyPrompt}</p>
            )}
            <PlanPreviewView entry={entry} />
            <ApprovalInline entry={entry} />
            <p className="small" role="status">{entry.statusText}</p>
            {entry.error && <p className="error-text small" role="alert">{entry.error}</p>}
            {entry.findings.map((finding, i) => (
              <div key={i} className="cc-finding">
                <div className="strong small">{finding.title}</div>
                {finding.detail && <div className="small muted">{finding.detail}</div>}
                {(finding.refs.length > 0 || finding.artifactId) && (
                  <div className="row wrap gap4">
                    {finding.refs.map((ref, j) => (
                      <button key={j} className="btn btn-small" onClick={ref.run}>
                        {ref.label}
                      </button>
                    ))}
                    {finding.artifactId && (
                      <button className="btn btn-small" onClick={() => finding.artifactId && setPreviewArtifactId(finding.artifactId)}>
                        View evidence
                      </button>
                    )}
                  </div>
                )}
              </div>
            ))}
            {entry.dispatches.map((dispatch, i) => (
              <div key={i} className={`cc-dispatch ${dispatch.ok ? "" : "warn"}`}>
                <span className="small">
                  {dispatch.ok ? "✓" : "•"} {dispatch.label}
                </span>
                {dispatch.detail && <div className="small muted">{dispatch.detail}</div>}
                {dispatch.taskId && (
                  <LiveTaskStatus
                    taskId={dispatch.taskId}
                    reviewVerdict={dispatch.reviewVerdict}
                  />
                )}
              </div>
            ))}
            {entry.status === "done" && <CompletionReceipt entry={entry} />}
            <div className="row wrap gap4">
              {entry.status === "preview" && entry.plan.actions.length > 0 && (
                <button
                  className="btn btn-small btn-primary"
                  disabled={!project}
                  onClick={() => void executeEntry({ ...entry, findings: [], dispatches: [] })}
                >
                  {entry.intent.confirmationRequired ? "Review & start" : "Run"}
                </button>
              )}
              {(entry.status === "done" || entry.status === "error") && (
                <>
                  <button
                    className="btn btn-small"
                    onClick={() => {
                      setInput(entry.request);
                      inputRef.current?.focus();
                    }}
                  >
                    Edit request
                  </button>
                  <button
                    className="btn btn-small"
                    title="Continue this thread: restores its scope and request as a new draft"
                    onClick={() => branchEntry(entry)}
                  >
                    Branch
                  </button>
                </>
              )}
            </div>
          </article>
        ))}
      </div>
      {entries.length > 0 && (
        <div className="pad">
          <button
            className="btn btn-small"
            onClick={() => {
              void confirmAction({
                title: "Clear the Command Center conversation?",
                body: "Dispatched work is unaffected.",
                confirmLabel: "Clear",
              }).then((ok) => {
                if (ok) setWorkspace({ centerEntries: [] });
              });
            }}
          >
            Clear conversation
          </button>
        </div>
      )}
      {previewArtifactId && (
        <ArtifactPreview artifactId={previewArtifactId} onClose={() => setPreviewArtifactId(null)} />
      )}
    </div>
  );
}

function relativeTime(iso: string): string {
  const seconds = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 1000));
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  return `${Math.floor(seconds / 3600)}h ago`;
}

function LiveTaskStatus({ taskId, reviewVerdict }: { taskId: string; reviewVerdict?: string }) {
  const tasks = useOffice((s) => s.tasks);
  const setWorkspace = useStore((s) => s.set);
  const task = tasks.find((t) => t.id === taskId);
  const openAgents = (): void => {
    setWorkspace({ view: "office", sidebarOpen: true });
    useOffice.getState().set({ tab: "team", selectedTaskId: taskId, selectedAgentId: null });
  };
  return (
    <div className="small row wrap gap4">
      <span className="muted">Live status:</span>
      {task ? (
        <>
          <StatusLabel state={task.status} />
          <span className="muted">{task.attempts.length} attempt(s)</span>
          {(task.status === "failed" || task.status === "blocked") && (
            <span className="warn">
              {task.status === "failed"
                ? "Inspect attempts and evidence, then retry from Agents or the palette."
                : "Waiting on dependencies or input — inspect in Agents."}
            </span>
          )}
        </>
      ) : (
        <span className="muted">task not in snapshot — resyncing…</span>
      )}
      {reviewVerdict && <span className="muted">reviewers: {reviewVerdict}</span>}
      <button className="link" onClick={openAgents}>
        Open in Agents
      </button>
      <button
        className="link"
        onClick={() => {
          setWorkspace({ view: "graph", sidebarOpen: true });
          useOffice.getState().set({ selectedTaskId: taskId });
        }}
      >
        Open in graph
      </button>
    </div>
  );
}
