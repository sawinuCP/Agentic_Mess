// Plan preview builder (Wave 10): declarative, reviewable plans over the
// classified intent. Plans name real steps, real scopes, and real action
// ids the view executes — estimates derive from recorded state at run time,
// never invented here.

import type { EngineeringIntent } from "./classify";

export interface PlanAction {
  id:
    | "navigate"
    | "fetch_context"
    | "query_symbols"
    | "query_retrieve"
    | "query_search_files"
    | "read_file"
    | "create_task"
    | "dispatch_execute"
    | "dispatch_control"
    | "dispatch_tool"
    | "dispatch_review"
    | "dispatch_research_search"
    | "show_costs"
    | "show_health"
    | "show_traceability";
  label: string;
  detail: string;
  gated: boolean;
}

export interface PlanPreview {
  goal: string;
  steps: string[];
  affected: string[];
  estimates: string[];
  actions: PlanAction[];
}

function scopeLabel(intent: EngineeringIntent): string {
  const s = intent.scope;
  if (s.requirementId) return "selected requirement";
  if (s.taskId) return "selected task";
  if (s.agentId) return "selected agent";
  if (s.filePath) return s.hasSelection ? `selection in ${s.filePath}` : s.filePath;
  return "project";
}

export function planFor(intent: EngineeringIntent): PlanPreview {
  const where = scopeLabel(intent);
  switch (intent.intentType) {
    case "implement_feature":
      return {
        goal: `Implement: ${intent.request}`,
        steps: [
          "Assemble scoped context (selection, symbols, related tests)",
          "Draft implementation tasks linked to the requirement where present",
          "Start execution only after confirmation",
        ],
        affected: [where],
        estimates: ["1 task per unit of work", "execution is a separate confirmed step"],
        actions: [
          { id: "fetch_context", label: "Assemble context", detail: where, gated: false },
          { id: "create_task", label: "Create implementation task", detail: where, gated: true },
        ],
      };
    case "fix_failure":
      return {
        goal: `Investigate and fix: ${intent.request}`,
        steps: [
          "Collect failure evidence (output, events, attempts)",
          "Retrieve related code and tests",
          "Propose a debugger task; start only after confirmation",
        ],
        affected: [where],
        estimates: ["1 debugger task", "1 validation run"],
        actions: [
          { id: "fetch_context", label: "Collect failure evidence", detail: where, gated: false },
          { id: "query_retrieve", label: "Find related code and tests", detail: where, gated: false },
          { id: "create_task", label: "Create debugger task", detail: where, gated: true },
        ],
      };
    case "explain_code":
    case "explain_failure":
      return {
        goal: `Explain: ${intent.request}`,
        steps: [
          "Read the scoped file slice",
          "List document symbols and dependents",
          "Summarize structure, dependents, tests, and recent changes",
        ],
        affected: [where],
        estimates: ["read-only; no execution"],
        actions: [
          { id: "read_file", label: "Read scoped code", detail: where, gated: false },
          { id: "query_symbols", label: "List symbols and usages", detail: where, gated: false },
        ],
      };
    case "find_usages":
      return {
        goal: `Find usages in scope: ${where}`,
        steps: ["Workspace symbol lookup", "Text search for references", "Group by file"],
        affected: [where],
        estimates: ["read-only; no execution"],
        actions: [
          { id: "query_symbols", label: "Search symbols", detail: where, gated: false },
          { id: "query_search_files", label: "Search references", detail: where, gated: false },
        ],
      };
    case "find_affected_code":
      return {
        goal: `Assess impact in scope: ${where}`,
        steps: ["Hybrid retrieval over the index", "Dependency and test mapping", "Summarize blast radius"],
        affected: [where],
        estimates: ["read-only; no execution"],
        actions: [
          { id: "query_retrieve", label: "Retrieve related code", detail: where, gated: false },
        ],
      };
    case "run_tests":
      return {
        goal: "Run the project test suite",
        steps: ["Detect test runner", "Run tests", "Report results with evidence links"],
        affected: ["project toolchains", "output panel"],
        estimates: ["1 tool execution"],
        actions: [{ id: "dispatch_tool", label: "Run tests", detail: "test tool", gated: true }],
      };
    case "review_requirement":
      return {
        goal: "Review requirement coverage against evidence",
        steps: ["Load traceability", "Compare criteria against recorded evidence", "List gaps"],
        affected: [where],
        estimates: ["read-only; no execution"],
        actions: [{ id: "show_traceability", label: "Show coverage", detail: where, gated: false }],
      };
    case "review_security":
      return {
        goal: `Security review in scope: ${where}`,
        steps: ["Collect code slice and dependencies", "Check against recorded security findings", "List concerns with file references"],
        affected: [where],
        estimates: ["read-only determinism; model review only on explicit request"],
        actions: [
          { id: "fetch_context", label: "Collect code and findings", detail: where, gated: false },
        ],
      };
    case "review_implementation":
      return {
        goal: `Model review of: ${intent.request}`,
        steps: ["Assemble task proposal with evidence refs", "Run the reviewer pipeline", "Report verdict and findings"],
        affected: [where],
        estimates: ["model calls billed to the project ledger"],
        actions: [{ id: "dispatch_review", label: "Run reviewers", detail: where, gated: true }],
      };
    case "create_plan":
      return {
        goal: `Plan: ${intent.request}`,
        steps: ["List units of work as task drafts", "Link requirement and dependencies", "Create tasks on confirmation"],
        affected: [where],
        estimates: ["tasks created only after confirmation"],
        actions: [{ id: "create_task", label: "Create planned tasks", detail: where, gated: true }],
      };
    case "start_execution":
      return {
        goal: `Start execution: ${intent.request}`,
        steps: ["Verify task is startable with completed dependencies", "Dispatch to the durable workflow", "Hand off to live execution views"],
        affected: [where],
        estimates: ["1 workflow run"],
        actions: [{ id: "dispatch_execute", label: "Start execution", detail: where, gated: true }],
      };
    case "control_execution":
      return {
        goal: `${intent.control ?? "control"} execution: ${intent.request}`,
        steps: ["Resolve eligible tasks in scope", "Send the control signal", "Refresh from the authoritative snapshot"],
        affected: [where],
        estimates: ["signal acknowledgement, not instant state"],
        actions: [{ id: "dispatch_control", label: `Send ${intent.control ?? ""} signal`, detail: where, gated: true }],
      };
    case "open_surface":
      return {
        goal: `Open ${intent.surface ?? "surface"}`,
        steps: ["Navigate with scope preserved"],
        affected: [intent.surface ?? "workspace"],
        estimates: ["navigation only"],
        actions: [{ id: "navigate", label: `Open ${intent.surface ?? ""}`, detail: "", gated: false }],
      };
    case "ask_architecture":
      return {
        goal: "Project health and architecture overview",
        steps: ["Diagnostics, toolchains, git status, coverage", "Summarize structure and risks"],
        affected: ["project"],
        estimates: ["read-only; no execution"],
        actions: [{ id: "show_health", label: "Show project health", detail: "diagnostics", gated: false }],
      };
    case "research_topic":
      return {
        goal: `Research: ${intent.request}`,
        steps: ["Search external sources with provenance", "Fetch selected sources into artifacts", "Attach findings as evidence refs"],
        affected: ["external network", "artifact store"],
        estimates: ["external lookups; content stored as artifacts"],
        actions: [{ id: "dispatch_research_search", label: "Search external sources", detail: intent.request, gated: true }],
      };
    case "cost_query":
      return {
        goal: "Model usage and cost transparency",
        steps: ["Read the project cost ledger", "Compare against the per-task budget"],
        affected: ["cost ledger"],
        estimates: ["read-only; no execution"],
        actions: [{ id: "show_costs", label: "Show usage", detail: "ledger", gated: false }],
      };
    case "hitl_guidance":
      return {
        goal: "Human approval guidance",
        steps: ["Open the approval surface", "Approvals are decided on their cards, never by text"],
        affected: ["office approvals"],
        estimates: ["navigation only"],
        actions: [{ id: "navigate", label: "Open approvals", detail: "", gated: false }],
      };
    case "unsupported":
      return {
        goal: "Unsupported action",
        steps: ["No dispatch available by design"],
        affected: [],
        estimates: [],
        actions: [],
      };
    case "unknown":
    default:
      return {
        goal: "Needs scope",
        steps: ["Select a requirement, file, failure, task, or agent — or name one"],
        affected: [],
        estimates: [],
        actions: [{ id: "fetch_context", label: "Review current context", detail: "workspace", gated: false }],
      };
  }
}
