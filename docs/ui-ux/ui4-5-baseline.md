# UI-4.5 Baseline — Causal / Traceability Model (forensic, source-backed)

Date: 2026-09-21. Every row verified against backend models, services, and
frontend projection code. Authority legend: PERSISTED (durable FK/row) ·
DERIVED (deterministic from persisted) · EVENT (reconstructed from durable
events) · INFERRED (heuristic, must not be authoritative) · ABSENT.

| Relationship | Backend? | Frontend? | Durable? | Evidence source | Current UI | Authority |
|---|---|---|---|---|---|---|
| Requirement → Criterion | yes (FK) | yes | yes | requirements.acceptance_criteria | Requirements detail, OversightTab, graph metadata | PERSISTED |
| Requirement → Task | yes (task.requirement_id FK, SET NULL) | yes | yes, nullable | tasks table | Requirements work section, task inspector link | PERSISTED |
| Criterion → Task | no direct link | via requirement scope | n/a | shared requirement_id | Verify UI binds at action time | INFERRED (action-time binding is durable: validation.task_id) |
| Task → Agent | via attempts only | yes | yes | task_attempts.agent_id (SET NULL) | owners, roster, graph "executed by" | PERSISTED (attempt-scoped) |
| Task → Attempt | yes (FK, unique task×number) | yes | yes | task_attempts | inspector, receipts | PERSISTED |
| Attempt → File | no | via tool events | events durable | TOOL_RUN_COMPLETED.payload.path + task_id | touched-files lists, graph file nodes | EVENT |
| Attempt → Test | no separate entity | via tool events | events durable | TOOL_RUN_COMPLETED tool∈{test,lint,build} | graph test nodes, attempt outcomes | EVENT |
| Attempt → Artifact | yes (JSONB id list) | yes | yes | attempt.evidence_artifact_ids | evidence lists, graph evidence nodes | PERSISTED |
| Artifact → Evidence | by reference only | yes | yes | validation.evidence_artifact_id; attempt lists | ArtifactMetaView, receipts | PERSISTED (reference, no backlink) |
| Criterion → Evidence | yes, at verify time | yes (bind UI) | yes | validation row (criterion+artifact+task) | VerifyCriterion picker, receipts | PERSISTED (validation row) |
| Evidence → Verification | yes | yes | yes | criterion.status=verified + validation status=passed | pills, receipts, gate | PERSISTED |
| Requirement → Approval | none (HITL links tasks) | via linked tasks | yes | hitl_requests.task_id | ApprovalCard(taskIds), attention | DERIVED (task join) |
| Change → Verification invalidation | NO | NO | n/a | — | — | ABSENT (critical gap §4) |
| Task → Task (depends) | yes (task_dependencies, unique) | yes | yes | task_dependencies + task.depends_on | DepMap, inspector, graph edges | PERSISTED |
| Task → Plan/Requirement creation | yes (plan_id, requirement_id) | yes | yes | tasks table | traceability, graph req-task edge | PERSISTED |
| Commit → Task | no (message parse) | yes, flagged derived | events durable | GIT_COMMIT + worktree message regex | graph "integrated as" edge (derived:true) | EVENT+INFERRED |
| Attempt → Agent session | no link | none | n/a | — | — | ABSENT (sessions runtime-owned) |
| Verification → timestamp/history | NO | NO | n/a | validations.created_at exists but unexposed | — | ABSENT (gap) |
| Requirement identity | UUID PK + title + project + created_at | id mono secondary | yes | requirements table | REQ 8ch + title | PERSISTED |

Key structural facts:
* There is NO Run/Execution/ToolCall table. "Run" = UI word for an execution
  interaction; Execution = Temporal workflow run (execution_id string on
  events); Attempt = the durable unit; Tool call = TOOL_RUN_COMPLETED event
  + artifacts. Terminology must reflect this.
* Artifact rows carry NO task/agent/criterion FK — linkage flows exclusively
  through attempt lists and validation rows (and event payloads).
* Requirement has NO verification_status column and NO updated_at consumer —
  status is always derived per read; nothing records WHEN/WHY it changed.
* Events are durable, sequenced (project_seq), and carry task/agent/
  execution/correlation/trace ids + payload — the timeline substrate is
  complete for all listed event kinds.
* SSE envelopes mirror DB rows (schema_version, sequence) — projection, not
  truth; resync restores from the authoritative table.
