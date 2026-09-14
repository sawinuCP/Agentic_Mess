// Shared DTO types mirroring the control-plane API (services/api).

export interface ProjectInfo {
  id: string;
  name: string;
  root_path: string;
  default_branch: string;
}

export interface TreeNode {
  name: string;
  path: string;
  kind: "file" | "directory";
  size: number;
  has_children: boolean;
}

export interface FileContent {
  path: string;
  content: string;
  is_binary: boolean;
  size: number;
  mtime_ms: number;
}

export interface SearchMatch {
  path: string;
  line: number;
  column: number;
  text: string;
}

export interface ToolAvailability {
  executable: string;
  available: boolean;
  argv: string[];
  in_place: boolean;
}

export interface DetectedLanguage {
  id: string;
  name: string;
  monaco_language: string;
  manifests: string[];
  file_count: number;
  tools: string[];
  availability: Record<string, ToolAvailability>;
}

export interface ProjectToolchains {
  languages: DetectedLanguage[];
  diagnostics: string[];
  override_file: boolean;
}

export interface ToolRunResult {
  language: string;
  tool: string;
  command: string[];
  exit_code: number | null;
  timed_out: boolean;
  truncated: boolean;
  duration_ms: number;
  stdout: string;
  stderr: string;
  diagnostics: string[];
  file_content: string | null;
}

export interface GitStatusEntry {
  index_status: string;
  worktree_status: string;
  path: string;
}

export interface GitStatus {
  branch: string | null;
  upstream: string | null;
  ahead: number;
  behind: number;
  entries: GitStatusEntry[];
}

export interface GitCommit {
  hash: string;
  author: string;
  date_iso: string;
  message: string;
}
