// Typed HTTP client for the control-plane API. All calls go through the
// /api proxy (see vite.config.ts).

import type {
  AgentInfo,
  CostsSummary,
  EventEntry,
  FileContent,
  GitCommit,
  GitStatus,
  HitlRequestInfo,
  MessageInfo,
  ProjectInfo,
  ProjectToolchains,
  RequirementInfo,
  ReviewOutcome,
  SearchMatch,
  SessionInfo,
  SymbolInfo,
  TaskInfo,
  ToolRunResult,
  TraceabilityReport,
  TreeNode,
  WorktreeInfo,
} from "../types";

export class ApiError extends Error {
  constructor(
    public status: number,
    detail: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

// --- API token (Wave 1 security) ---------------------------------------------
// The bearer token is OPTIONAL: unset on the API means auth is disabled
// (loopback-only local mode). The browser keeps it in localStorage — never in
// source or the repo. WebSockets cannot carry headers from browsers, so the
// token travels as a `bearer.<token>` subprotocol (see app/api/security.py).
const TOKEN_STORAGE_KEY = "harness.api_token";

export function getApiToken(): string {
  try {
    return localStorage.getItem(TOKEN_STORAGE_KEY) ?? "";
  } catch {
    return ""; // storage unavailable (e.g. privacy mode) — anonymous local mode
  }
}

export function setApiToken(token: string): void {
  try {
    if (token) localStorage.setItem(TOKEN_STORAGE_KEY, token);
    else localStorage.removeItem(TOKEN_STORAGE_KEY);
  } catch {
    // storage unavailable — auth simply stays off
  }
}

export function webSocketProtocols(): string[] {
  const token = getApiToken();
  return token ? [`bearer.${token}`] : [];
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getApiToken();
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(path, {
    ...init,
    headers: { ...headers, ...(init?.headers as Record<string, string> | undefined) },
  });
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) {
        detail = body.detail;
      }
    } catch {
      // keep default detail
    }
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

const enc = encodeURIComponent;

// --- projects ---------------------------------------------------------------

export const listProjects = () => request<ProjectInfo[]>("/api/projects");

export const openProject = (root_path: string) =>
  request<ProjectInfo>("/api/projects/open", {
    method: "POST",
    body: JSON.stringify({ root_path }),
  });

// --- filesystem ---------------------------------------------------------------

export const getTree = (projectId: string, path = "") =>
  request<TreeNode[]>(`/api/projects/${projectId}/tree?path=${enc(path)}`);

export const readFile = (projectId: string, path: string) =>
  request<FileContent>(`/api/projects/${projectId}/file?path=${enc(path)}`);

export const writeFile = (projectId: string, path: string, content: string) =>
  request<FileContent>(`/api/projects/${projectId}/file`, {
    method: "PUT",
    body: JSON.stringify({ path, content }),
  });

export const createEntry = (projectId: string, path: string, kind: "file" | "directory") =>
  request<TreeNode>(`/api/projects/${projectId}/entries`, {
    method: "POST",
    body: JSON.stringify({ path, kind }),
  });

export const renameEntry = (projectId: string, path: string, new_path: string) =>
  request<TreeNode>(`/api/projects/${projectId}/rename`, {
    method: "POST",
    body: JSON.stringify({ path, new_path }),
  });

export const deleteEntry = (projectId: string, path: string) =>
  request<void>(`/api/projects/${projectId}/entries?path=${enc(path)}`, { method: "DELETE" });

export const searchFiles = (
  projectId: string,
  params: { q: string; path?: string; regex?: boolean; case_sensitive?: boolean; glob?: string },
) => {
  const query = new URLSearchParams({ q: params.q });
  if (params.path) query.set("path", params.path);
  if (params.regex) query.set("regex", "true");
  if (params.case_sensitive) query.set("case_sensitive", "true");
  if (params.glob) query.set("glob", params.glob);
  return request<SearchMatch[]>(`/api/projects/${projectId}/search?${query.toString()}`);
};

export const listFilePaths = (projectId: string, q = "") =>
  request<string[]>(`/api/projects/${projectId}/files?q=${enc(q)}`);

// --- toolchains ---------------------------------------------------------------

export const getProjectToolchains = (projectId: string) =>
  request<ProjectToolchains>(`/api/projects/${projectId}/toolchains`);

export const runTool = (
  projectId: string,
  body: { tool: string; path?: string; language?: string },
) =>
  request<ToolRunResult>(`/api/projects/${projectId}/toolchains/run`, {
    method: "POST",
    body: JSON.stringify(body),
  });

// --- git ---------------------------------------------------------------

export const gitStatus = (projectId: string) =>
  request<GitStatus>(`/api/projects/${projectId}/git/status`);

export const gitDiff = (projectId: string, path?: string, staged = false) => {
  const query = new URLSearchParams();
  if (path) query.set("path", path);
  if (staged) query.set("staged", "true");
  return request<{ diff: string }>(`/api/projects/${projectId}/git/diff?${query.toString()}`);
};

export const gitFileAt = (projectId: string, path: string, ref = "HEAD") =>
  request<{ content: string }>(
    `/api/projects/${projectId}/git/file?path=${enc(path)}&ref=${enc(ref)}`,
  );

export const gitLog = (projectId: string, limit = 30) =>
  request<GitCommit[]>(`/api/projects/${projectId}/git/log?limit=${limit}`);

export const gitInit = (projectId: string) =>
  request<void>(`/api/projects/${projectId}/git/init`, { method: "POST" });

export const gitStage = (projectId: string, paths: string[]) =>
  request<void>(`/api/projects/${projectId}/git/stage`, {
    method: "POST",
    body: JSON.stringify({ paths }),
  });

export const gitUnstage = (projectId: string, paths: string[]) =>
  request<void>(`/api/projects/${projectId}/git/unstage`, {
    method: "POST",
    body: JSON.stringify({ paths }),
  });

export const gitCommit = (projectId: string, message: string, paths?: string[]) =>
  request<{ output: string }>(`/api/projects/${projectId}/git/commit`, {
    method: "POST",
    body: JSON.stringify({ message, paths: paths ?? null }),
  });

export const gitCheckout = (projectId: string, branch: string, create = false) =>
  request<void>(`/api/projects/${projectId}/git/checkout`, {
    method: "POST",
    body: JSON.stringify({ branch, create }),
  });

// --- terminals ---------------------------------------------------------------

export const createTerminalSession = (projectId: string) =>
  request<{ id: string; cwd: string }>(
    `/api/projects/${projectId}/terminal/sessions`,
    { method: "POST" },
  );

export function terminalWebSocketUrl(sessionId: string): string {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${location.host}/api/ws/terminal/${sessionId}`;
}

// --- office (Phase 9, FR-025) ---------------------------------------------

export const listAgents = (projectId: string) =>
  request<AgentInfo[]>(`/api/projects/${projectId}/agents`);

export const createAgent = (
  projectId: string,
  body: { name: string; role: string; model?: string | null; capabilities?: string[] },
) =>
  request<AgentInfo>(`/api/projects/${projectId}/agents`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const listAgentSessions = (agentId: string, limit = 100) =>
  request<SessionInfo[]>(`/api/agents/${enc(agentId)}/sessions?limit=${limit}`);

export const listTasks = (projectId: string) =>
  request<TaskInfo[]>(`/api/projects/${projectId}/tasks`);

export const createTask = (
  projectId: string,
  body: {
    title: string;
    request?: string;
    requirement_id?: string | null;
    priority?: number;
    depends_on?: string[];
  },
) =>
  request<TaskInfo>(`/api/projects/${projectId}/tasks`, {
    method: "POST",
    body: JSON.stringify(body),
  });

// Existing durable task endpoints. Signal acknowledgement is NOT a state change.
// Cancellation (FR-014) is a direct human intervention: it marks the task
// cancelled without destroying its history and returns the updated task.
export const controlTask = (taskId: string, action: "execute" | "pause" | "resume") =>
  request<{ started: boolean; workflow_id: string } | void>(
    `/api/tasks/${enc(taskId)}/${action}`, { method: "POST" },
  );

export const cancelTask = (taskId: string) =>
  request<TaskInfo>(`/api/tasks/${enc(taskId)}/cancel`, { method: "POST" });

export const listRequirements = (projectId: string) =>
  request<RequirementInfo[]>(`/api/projects/${projectId}/requirements`);

export const listEvents = (projectId: string, limit = 120) =>
  request<EventEntry[]>(`/api/events?project_id=${enc(projectId)}&limit=${limit}`);

export interface HistoryQuery {
  limit?: number;
  order?: "asc" | "desc";
  sinceSeq?: number;
  beforeSeq?: number;
  eventType?: string;
  taskId?: string;
}

/** Durable history reads with cursor paging (Wave 9): newest page first,
// then repeat with beforeSeq = min seq for older pages until short. */
export const listHistory = (projectId: string, query: HistoryQuery = {}) => {
  const params = new URLSearchParams({ project_id: projectId });
  params.set("limit", String(query.limit ?? 500));
  params.set("order", query.order ?? "desc");
  if (query.sinceSeq !== undefined) params.set("since_seq", String(query.sinceSeq));
  if (query.beforeSeq !== undefined) params.set("before_seq", String(query.beforeSeq));
  if (query.eventType) params.set("event_type", query.eventType);
  if (query.taskId) params.set("task_id", query.taskId);
  return request<EventEntry[]>(`/api/events?${params.toString()}`);
};

export const listHitl = (projectId: string, status?: string) => {
  const query = new URLSearchParams({ project_id: projectId });
  if (status) query.set("status", status);
  return request<HitlRequestInfo[]>(`/api/hitl?${query.toString()}`);
};

export const decideHitl = (
  projectId: string,
  requestId: string,
  body: { decision: "approved" | "rejected"; decided_by: string; note?: string },
) =>
  request<HitlRequestInfo>(
    `/api/projects/${projectId}/hitl/${requestId}/decide`,
    { method: "POST", body: JSON.stringify(body) },
  );

export const getTraceability = (projectId: string) =>
  request<TraceabilityReport>(`/api/projects/${projectId}/oversight/traceability`);

export const requestCompletion = async (projectId: string) => {
  // 409 means "blocked" — the body still carries the freshest report with
  // blockers, which is exactly what the oversight UI wants to show.
  const response = await fetch(`/api/projects/${projectId}/oversight/completion`, {
    method: "POST",
  });
  const body = (await response.json()) as
    | TraceabilityReport
    | { detail: string; report: TraceabilityReport };
  if (response.status === 409 && "report" in body) {
    return body.report;
  }
  if (!response.ok) {
    const detail = "detail" in body ? body.detail : `HTTP ${response.status}`;
    throw new ApiError(response.status, detail);
  }
  return body as TraceabilityReport;
};

export const runReview = (
  taskId: string,
  body: { title: string; proposal: string; evidence?: string[] },
) =>
  request<ReviewOutcome>(`/api/tasks/${taskId}/reviews`, {
    method: "POST",
    body: JSON.stringify(body),
  });

// --- evidence metadata (Wave 8): existing artifact endpoints, thin client --

export interface ArtifactMeta {
  id: string;
  project_id: string | null;
  name: string;
  kind: string;
  mime: string;
  size: number;
  sha256: string;
}

export const getArtifact = (artifactId: string) =>
  request<ArtifactMeta>(`/api/artifacts/${enc(artifactId)}`);

// --- agent office (Wave 7): communication, worktrees, costs -----------------
// Read-only projections over existing endpoints. No new backend concepts.

export const listAgentMessages = (agentId: string, limit = 100) =>
  request<MessageInfo[]>(`/api/agents/${enc(agentId)}/messages?limit=${limit}`);

export const sendOperatorMessage = (
  recipientAgentId: string | null,
  body: { task_id?: string | null; type: "request" | "question"; summary: string },
) =>
  request<MessageInfo>("/api/messages", {
    method: "POST",
    body: JSON.stringify({
      sender_agent_id: null,
      recipient_agent_id: recipientAgentId,
      task_id: body.task_id ?? null,
      type: body.type,
      payload: { summary: body.summary, from: "operator" },
    }),
  });

export const listWorktrees = (projectId: string, limit = 100) =>
  request<WorktreeInfo[]>(`/api/projects/${projectId}/worktrees?limit=${limit}`);

export const getCosts = (projectId: string, taskId?: string) => {
  const query = taskId ? `?task_id=${enc(taskId)}` : "";
  return request<CostsSummary>(`/api/projects/${projectId}/intelligence/costs${query}`);
};

// --- workspace symbols (code-intel index; empty until the index runs) --------

export const searchSymbols = (projectId: string, q: string, limit = 50) =>
  request<SymbolInfo[]>(
    `/api/projects/${projectId}/symbols?q=${enc(q)}&limit=${limit}`,
  );

export const fileSymbols = (projectId: string, path: string) =>
  request<SymbolInfo[]>(`/api/projects/${projectId}/symbols/file?path=${enc(path)}`);

export interface RetrievalHit {
  path: string;
  name: string;
  kind: string;
  start_line: number;
  end_line: number;
  signature: string | null;
  score: number;
  matched: string;
}

export const retrieveRelated = (projectId: string, q: string, k = 6) =>
  request<{ query: string; hits: RetrievalHit[] }>(
    `/api/projects/${projectId}/intelligence/retrieve?q=${enc(q)}&k=${k}`,
  );

export interface ResearchResult {
  title: string;
  url: string;
  source: string;
}

export const researchSearch = (projectId: string, query: string, maxResults = 5) =>
  request<{ query: string; results: ResearchResult[] }>(
    `/api/projects/${projectId}/research/search`,
    { method: "POST", body: JSON.stringify({ query, max_results: maxResults }) },
  );

export interface ResearchFetch {
  url: string;
  final_url: string;
  title: string;
  fetched_at: string;
  sha256: string;
  excerpt: string;
  artifact_id: string;
  context_item_id: string;
  confidence: number;
}

export const researchFetch = (projectId: string, url: string, note?: string) =>
  request<ResearchFetch>(`/api/projects/${projectId}/research/fetch`, {
    method: "POST",
    body: JSON.stringify({ url, note }),
  });

// --- MCP gateway (existing routes; thin client, Wave 10 completion) --------

export interface McpStatus {
  enabled: boolean;
  config_path: string;
  timeout_seconds: number;
}

export interface McpToolDef {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
  allowed: boolean;
}

export interface McpServerDef {
  server: string;
  tools: McpToolDef[];
  error?: string;
}

export interface McpCallResult {
  server: string;
  tool: string;
  content: unknown;
  is_error: boolean;
  artifact_id: string | null;
}

export const mcpStatus = () => request<McpStatus>("/api/mcp/status");

export const mcpDiscover = () =>
  request<{ servers: McpServerDef[] }>("/api/mcp/discover", { method: "POST" });

export const mcpCall = (server: string, tool: string, args: Record<string, unknown>) =>
  request<McpCallResult>("/api/mcp/call", {
    method: "POST",
    body: JSON.stringify({ server, tool, arguments: args }),
  });

/** Validate raw args text: must parse to a JSON object (never eval'd). */
export function parseMcpArgs(text: string): { ok: true; value: Record<string, unknown> } | { ok: false; error: string } {
  const trimmed = text.trim();
  if (!trimmed) return { ok: true, value: {} };
  try {
    const parsed: unknown = JSON.parse(trimmed);
    if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
      return { ok: false, error: "Arguments must be a JSON object." };
    }
    return { ok: true, value: parsed as Record<string, unknown> };
  } catch {
    return { ok: false, error: "Arguments are not valid JSON." };
  }
}

// --- diagnostics (Phase 10) -----------------------------------------------

export interface DiagnosticsReport {
  app: {
    version: string;
    environment: string;
    python: string;
    platform: string;
    pid: number;
    uptime_seconds: number;
  };
  database: { status: string; alembic_head: string };
  counts: Record<string, number>;
  artifact_store: { status: string; detail: string };
  temp_dir: { status: string; detail: string };
  redis: { status: string; detail: string };
  nats: { status: string; detail: string };
  config: Record<string, string | boolean>;
}

export const getDiagnostics = () => request<DiagnosticsReport>("/api/diagnostics");
