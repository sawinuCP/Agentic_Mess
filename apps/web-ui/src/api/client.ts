// Typed HTTP client for the control-plane API. All calls go through the
// /api proxy (see vite.config.ts).

import type {
  FileContent,
  GitCommit,
  GitStatus,
  ProjectInfo,
  ProjectToolchains,
  SearchMatch,
  ToolRunResult,
  TreeNode,
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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
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
