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

// --- office (Phase 9, FR-025) ---------------------------------------------

export interface AgentInfo {
  id: string;
  project_id: string | null;
  name: string;
  role: string;
  model: string | null;
  capabilities: string[];
  state: string;
}

export interface TaskInfo {
  id: string;
  project_id: string;
  requirement_id: string | null;
  title: string;
  request: string;
  status: string;
  priority: number;
  depends_on: string[];
  attempts: {
    attempt_number: number;
    agent_id: string | null;
    outcome: string | null;
    failure_class: string | null;
    failure_detail: string | null;
    evidence_artifact_ids: string[];
  }[];
}

export interface CriterionInfo {
  id: string;
  description: string;
  kind: string;
  mandatory: boolean;
  status: string;
}

export interface RequirementInfo {
  id: string;
  project_id: string;
  title: string;
  description: string;
  priority: string;
  status: string;
  criteria: CriterionInfo[];
}

export interface HitlRequestInfo {
  id: string;
  task_id: string | null;
  kind: string;
  question: string;
  choices: string[];
  risk: string;
  status: string;
  created_at: string;
  [key: string]: unknown;
}

export interface EventEntry {
  id: string;
  occurred_at: string;
  event_type: string;
  source: string | null;
  project_id: string | null;
  task_id: string | null;
  agent_id: string | null;
  payload: Record<string, unknown>;
  project_seq?: number | null;
  execution_id?: string | null;
}

// --- agent office (Wave 7): communication, worktrees, costs ------------------

export interface MessageInfo {
  id: string;
  conversation_id: string | null;
  sender_agent_id: string | null;
  recipient_agent_id: string | null;
  task_id: string | null;
  type: string;
  payload: Record<string, unknown>;
  payload_ref: string | null;
  priority: number;
  correlation_id: string | null;
  reply_to: string | null;
  created_at: string;
  expires_at: string | null;
  delivered_at: string | null;
  delivery_attempts: number;
}

export interface WorktreeInfo {
  id: string;
  project_id: string;
  task_id: string | null;
  branch: string;
  path: string;
  status: string;
  integration_status: string;
  integration_position: number | null;
  created_at: string;
}

export interface CostsSummary {
  invocations: number;
  total_tokens: number;
  by_model: Record<string, number>;
  by_role: Record<string, number>;
  task_id: string | null;
  budget_tokens_per_task: number;
  extra?: Record<string, unknown>;
}

export interface SymbolInfo {
  id: string;
  path: string;
  name: string;
  kind: string;
  parent: string | null;
  start_line: number;
  end_line: number;
  signature: string | null;
  doc: string | null;
  language: string;
}

export interface SessionInfo {
  id: string;
  agent_id: string;
  runtime: string;
  status: string;
  started_at: string;
  heartbeat_at: string | null;
  finished_at: string | null;
}

// --- realtime (Wave 3) -------------------------------------------------------

/** Canonical wire envelope v1 — mirrors app/realtime/envelope.py. */
export interface EventEnvelope {
  schema_version: number;
  event_id: string;
  event_type: string;
  timestamp: string;
  project_id: string | null;
  execution_id: string | null;
  task_id: string | null;
  agent_id: string | null;
  correlation_id: string | null;
  source: string | null;
  sequence: number | null;
  payload: Record<string, unknown>;
  payload_ref: string | null;
}

/** Server → client control frames (never domain events). */
export interface ControlFrame {
  kind: "GATEWAY_STATUS" | "RESYNC_REQUIRED" | "DISCONNECT";
  detail?: string;
  state?: "live" | "degraded";
}

/** Connection state machine visible in the office UI (§26). */
export type ConnectionState =
  | "connecting"
  | "live"
  | "reconnecting"
  | "offline"
  | "degraded"
  | "resyncing";

export interface TraceabilityCriterion {
  id: string;
  description: string;
  kind: string;
  mandatory: boolean;
  state: string;
}

export interface TraceabilityRequirement {
  id: string;
  title: string;
  priority: string;
  status: string;
  implemented: boolean;
  task_ids: string[];
  criteria: TraceabilityCriterion[];
  evidence_artifact_ids: string[];
  validation_evidence_artifact_ids: string[];
}

export interface TraceabilityReport {
  project_id: string;
  generated_at: string;
  requirements: TraceabilityRequirement[];
  coverage: { total: number; verified: number; failed: number; unknown: number };
  orphan_task_ids: string[];
  scope_drift: boolean;
  completion_allowed?: boolean;
  blockers?: string[];
  warnings?: string[];
  artifact_id?: string;
}

export interface ReviewEntry {
  id: string;
  role: string;
  verdict: string;
  summary: string;
  model: string;
  rounds: number;
}

export interface ReviewOutcome {
  decision_id: string;
  verdict: string;
  rationale: string;
  reviews: ReviewEntry[];
  findings: { reviewer: string; severity: string; claim: string; evidence: string }[];
}
