**AI HARNESS CODE EDITOR**

**Complete Product Requirements, Feature Catalogue & Implementation Specification**

_Version 1.0 • 14 September 2026_

Purpose: a real, locally runnable, multi-language AI software-engineering code editor in which autonomous agents collaborate as an engineering team under a durable, observable, recoverable execution harness.

# Document Control

| **Item**                       | **Decision**                                                                                                                               |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------ |
| Product type                   | Desktop/local-first AI code editor and agentic software-engineering platform                                                               |
| Primary target                 | Windows first; architecture portable to macOS/Linux                                                                                        |
| Operating model                | Local-first, with optional cloud AI models/services                                                                                        |
| Language support               | Any programming language for which the environment can install/use a compiler, interpreter, formatter, linter, debugger or language server |
| AI architecture                | Model-agnostic, dynamically orchestrated multi-agent harness                                                                               |
| Core principle                 | Durable tasks/state/artifacts; replaceable agents/models/tools/runtimes                                                                    |
| Initial implementation posture | Production architecture + phased MVP + detailed implementation tasks                                                                       |
| Primary UI                     | Professional code editor + AI workspace + engineering office + execution graph                                                             |
| Authoritative state            | PostgreSQL                                                                                                                                 |

# 1\. Executive Summary

This project is a full AI-native code editor rather than a chat wrapper around a fixed LangChain/LangGraph workflow. The system accepts a software requirement and desired outcome, plans engineering work, dynamically creates and coordinates agents, lets them work in parallel and communicate asynchronously, executes code in isolated environments, validates results against requirements, recovers from failures, requests human approval when needed, and produces an auditable engineering result.

The editor must remain useful as a conventional code editor even when AI is disabled. It must support projects written in different languages and use the project's available toolchain—compiler/interpreter, formatter, linter, debugger, package manager and language server—rather than assuming a Python/JavaScript-only stack.

# 2\. Product Vision

Build an AI software-engineering environment where the user can say what should be built, while the harness behaves like a disciplined engineering organization: planning, assigning, implementing, reviewing, testing, debugging, researching, integrating and verifying work continuously.

The product should feel like a serious developer tool, not an autonomous chatbot.

# 3\. Core Design Principles

- Tasks are durable; agents are disposable.
- Models are replaceable; execution state is not.
- Artifacts and evidence are first-class objects.
- The orchestration runtime—not an LLM—controls lifecycle, permissions, scheduling and recovery.
- Use hybrid context: shared durable project state + private agent context + selected shared evidence.
- Progressive disclosure: retrieve only the context needed for the current decision.
- Every consequential action is observable and traceable.
- Parallel work requires isolation, leases and deterministic integration rules.
- Completion requires evidence, not an agent's claim of completion.
- Security and permission checks are enforced outside the model.
- Human approval can intervene before, during or after execution.
- Language support is toolchain-driven and extensible rather than hard-coded.

# 4\. Scope

## 4.1 In Scope

- Desktop code editor and project/workspace management.
- Multi-agent planning, execution, communication and dynamic spawning.
- Parallel agents with isolated Git worktrees.
- Durable task orchestration, checkpoints, pause/resume and recovery.
- Code intelligence, semantic navigation and context retrieval.
- Terminal, compiler/interpreter, formatter, linter, debugger, test runner and package-manager integration.
- Browser automation and application preview/debugging.
- MCP and web research integrations.
- Sandboxed local execution with resource controls.
- Requirement traceability and continuous oversight.
- Independent review/debate/adjudication for high-risk decisions.
- Human-in-the-loop approvals and intervention.
- Real-time agent office, timeline, execution graph and cost/usage views.
- Observability, audit history and evidence storage.

## 4.2 Non-Goals for the Initial Release

- Building a new compiler or language server for every language.
- Replacing Git itself.
- Guaranteeing unrestricted autonomous execution of arbitrary hostile code.
- Training proprietary foundation models.
- Exposing hidden chain-of-thought to users.
- Requiring a cloud control plane for normal local development.

# 5\. Primary User Journey

1. Create/open a repository or local project.
2. Select or auto-detect the project toolchain.
3. Describe the requirement and desired final outcome.
4. Harness parses requirements and acceptance criteria.
5. Planner creates an execution graph and identifies required roles.
6. Supervisor validates the plan and may request HITL approval.
7. Scheduler creates bounded concurrent tasks and assigns agents.
8. Agents retrieve task-specific context and work in isolated workspaces.
9. Agents use code tools, compilers, tests, browsers, MCP and web research as needed.
10. Agents communicate, request help, send artifacts and unblock dependencies.
11. Reviewers validate important changes independently.
12. Continuous requirement oversight checks implementation against acceptance criteria.
13. Integration service validates and merges compatible work.
14. Failures trigger retry, context rebuild, replanning, model escalation or agent replacement.
15. Final verification produces evidence-backed completion status.
16. User reviews diff, tests, requirements coverage and execution history.

# 6\. Functional Requirements

**FR-001 \[MUST\]** The editor shall open, create, clone and manage local software projects.

**FR-002 \[MUST\]** The editor shall support arbitrary programming languages through configurable toolchains.

**FR-003 \[MUST\]** The editor shall detect project languages and relevant build systems where possible.

**FR-004 \[MUST\]** Users shall be able to configure compilers, interpreters, formatters, linters, test runners, debuggers, package managers and language servers.

**FR-005 \[MUST\]** The AI harness shall accept natural-language requirements and explicit desired outcomes.

**FR-006 \[MUST\]** The harness shall decompose requirements into durable tasks.

**FR-007 \[MUST\]** The harness shall dynamically spawn agents based on task requirements.

**FR-008 \[MUST\]** Agents shall be disposable and replaceable without losing task identity.

**FR-009 \[MUST\]** Multiple instances of the same role shall be allowed concurrently.

**FR-010 \[MUST\]** Agents shall work asynchronously and communicate through durable structured messages.

**FR-011 \[MUST\]** The scheduler shall enforce configurable concurrency/resource limits.

**FR-012 \[MUST\]** Agents shall use isolated workspaces/worktrees for conflicting code work.

**FR-013 \[MUST\]** The system shall maintain requirement-to-task-to-code-to-test traceability.

**FR-014 \[MUST\]** The system shall support HITL approvals and interventions at any phase.

**FR-015 \[MUST\]** The system shall support pause/resume without destroying durable execution state.

**FR-016 \[MUST\]** The system shall classify failures and perform bounded recovery.

**FR-017 \[MUST\]** The system shall provide independent validation of high-risk decisions.

**FR-018 \[MUST\]** The system shall execute code in isolated runtimes.

**FR-019 \[MUST\]** The system shall provide compiler/interpreter and formatter execution as first-class tools.

**FR-020 \[MUST\]** The system shall provide browser-based debugging for web applications.

**FR-021 \[MUST\]** The system shall provide MCP tool discovery, invocation and permission controls.

**FR-022 \[MUST\]** The system shall provide web research with evidence/provenance.

**FR-023 \[MUST\]** The system shall normalize/compress tool observations before model context injection.

**FR-024 \[MUST\]** The system shall persist execution events, artifacts and audit information.

**FR-025 \[MUST\]** The system shall expose an engineering-office UI for live agent activity.

**FR-026 \[MUST\]** The system shall not declare completion solely from an agent's self-report.

**FR-027 \[MUST\]** The system shall produce a final evidence-backed completion report.

**FR-028 \[MUST\]** The editor shall remain usable for conventional manual coding workflows.

**FR-029 \[MUST\]** The system shall support project-level configuration without hard-coding one framework.

**FR-030 \[MUST\]** The system shall provide security boundaries independent of model instructions.

# 7\. Feature Catalogue

| **Area**          | **Features**                                                                                                                                            |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Code Editor       | Monaco-based editing, tabs, split panes, file tree, symbol navigation, search/replace, diff/merge, diagnostics, formatting, terminal, command palette   |
| Language Support  | Language/toolchain registry, compiler/interpreter adapters, formatter adapters, linter adapters, debugger adapters, LSP adapters, build-system adapters |
| AI Planning       | Requirement parsing, acceptance criteria, task graph, dependency analysis, plan review, replanning                                                      |
| Agent Runtime     | Dynamic spawn, roles, capabilities, lifecycle, heartbeats, checkpoints, replacement, cancellation                                                       |
| Collaboration     | Direct messaging, requests/responses, broadcast events, artifact sharing, dependency notifications                                                      |
| Context           | Code retrieval, project memory, task context, tool observation compression, research evidence, context budgets                                          |
| Code Intelligence | Tree-sitter, SCIP, LSP, symbol graph, dependency graph, call graph, data/control flow, semantic search, lexical search                                  |
| Execution         | Shell, compiler, interpreter, tests, formatter, linter, debugger, package manager, Docker/dev containers                                                |
| Web/Browser       | Web research, Playwright browser, screenshots, console/network inspection, preview URLs                                                                 |
| MCP               | Server registry, tool schemas, discovery, authorization, execution, timeout, output normalization                                                       |
| Quality           | Unit/integration/e2e tests, static analysis, security scans, requirement coverage, independent verification                                             |
| Recovery          | Retry, timeout, replan, model escalation, replacement agent, context rebuild, merge recovery                                                            |
| HITL              | Approval gates, questions, intervention, edit-plan, pause/resume, emergency stop                                                                        |
| Office UI         | Agent cards, team topology, status, active tools, waiting states, communication stream, files, branches, cost                                           |
| Observability     | Events, traces, logs, metrics, execution timeline, correlation IDs, audit trail                                                                         |
| Security          | Sandboxing, permissions, secrets isolation, network policies, redaction, tool allowlists                                                                |
| Git               | Branches, worktrees, commits, diffs, integration queue, conflict handling, rollback                                                                     |
| Project Runtime   | Environment detection, containers, ports, previews, process supervision, resource quotas                                                                |

# 8\. Multi-Language Toolchain Architecture

Language support must be capability-driven. The core editor does not need language-specific business logic for every language. Instead, it uses adapters around external developer tooling.

Conceptual model:

Language  
\-> Language Definition  
\-> Toolchain Profile  
\-> Compiler / Interpreter  
\-> Formatter  
\-> Linter  
\-> Test Runner  
\-> Debug Adapter  
\-> Language Server  
\-> Package Manager  
\-> Build System  
\-> Runtime Container

| **Capability** | **Examples / approach**                                                                                                        |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| Languages      | Python, Java, Go, Rust, C/C++, C#, JavaScript/TypeScript, Kotlin, Swift, PHP, Ruby, Dart and any future language with adapters |
| Compilers      | gcc/clang, javac, dotnet, rustc/cargo, go build, language-specific tools                                                       |
| Formatters     | Prettier, Black/Ruff, gofmt, rustfmt, clang-format, dotnet format, etc.                                                        |
| LSP            | Language Server Protocol adapter per language                                                                                  |
| Debugging      | Debug Adapter Protocol where supported                                                                                         |
| Build          | Make, CMake, Gradle, Maven, Cargo, npm/pnpm/yarn, dotnet, Bazel, custom commands                                               |
| Testing        | Framework auto-detection + configurable commands                                                                               |

**LANG-001 \[MUST\]** The toolchain registry shall store executable paths, arguments, environment variables, working-directory rules and capability metadata.

**LANG-002 \[MUST\]** A project may contain multiple languages and multiple toolchains.

**LANG-003 \[MUST\]** A missing tool shall produce an actionable environment diagnostic rather than silently failing.

**LANG-004 \[MUST\]** Formatting shall be available both manually and as an agent action.

**LANG-005 \[MUST\]** Compiler/test output shall pass through the observation normalizer.

# 9\. System Architecture

Recommended logical architecture:

Desktop UI  
|-- Editor / Explorer / Terminal / Office / Graph / Diff  
|-- WebSocket/SSE  
v  
Local Control Plane  
|-- API Gateway  
|-- Project & Workspace Manager  
|-- Agent Orchestrator  
|-- Scheduler  
|-- Context Broker  
|-- Requirement Supervisor  
|-- Recovery Manager  
|-- Tool Registry  
|-- Security/Policy Engine  
|-- Integration Manager  
|-- Runtime Manager  
v  
Durable State / Event Infrastructure  
|-- PostgreSQL (source of truth)  
|-- Temporal (durable workflows)  
|-- NATS JetStream (events/messages)  
|-- Redis (leases/cache/ephemeral state)  
|-- Object Storage (raw artifacts)  
|-- pgvector (semantic retrieval)  
v  
Execution Plane  
|-- Agent Workers  
|-- Dev Containers / Docker  
|-- Browser Workers  
|-- Language Toolchains  
|-- MCP Servers  
|-- Web Research

# 10\. Recommended Technology Stack

| **Layer**         | **Recommended technology**         | **Reason**                                                                |
| ----------------- | ---------------------------------- | ------------------------------------------------------------------------- |
| Desktop shell     | Tauri 2                            | Lightweight desktop distribution and native integration                   |
| Frontend          | React + TypeScript                 | Rich editor/UI ecosystem                                                  |
| Editor            | Monaco Editor                      | Professional code editing foundation                                      |
| Backend           | Python + FastAPI                   | Strong fit for orchestration, AI/tool integrations                        |
| Agent runtime     | Custom Python runtime              | Full control over lifecycle/protocol/policies                             |
| Durable workflows | Temporal                           | Durable execution, pause/resume, retries, timers                          |
| Event/message bus | NATS JetStream                     | Durable asynchronous messaging/event streaming                            |
| Database          | PostgreSQL                         | Authoritative relational state                                            |
| Cache/leases      | Redis                              | Short-lived coordination and rate limiting                                |
| Vector retrieval  | pgvector                           | Simple integrated semantic retrieval                                      |
| Code parsing      | Tree-sitter                        | Incremental multi-language syntax parsing                                 |
| Semantic index    | SCIP + LSP                         | Language-agnostic semantic navigation plus language-specific intelligence |
| Security analysis | Semgrep / CodeQL / Joern as needed | Specialized static/data-flow/security analysis                            |
| Execution         | Docker/dev containers initially    | Practical local isolation                                                 |
| Higher isolation  | gVisor / Firecracker / Kata later  | Stronger sandboxing for hostile workloads                                 |
| Browser           | Playwright                         | Browser automation and debugging                                          |
| Git               | Git worktrees                      | Parallel isolated agent changes                                           |
| Observability     | OpenTelemetry                      | Standardized traces/metrics/logs                                          |
| Object storage    | S3-compatible local/object store   | Large raw outputs and artifacts                                           |

# 11\. Agent Model

Agent identity is separate from task identity.

TASK-182  
Attempt 1 -> Agent-12 -> FAILED  
Attempt 2 -> Agent-19 -> FAILED  
Attempt 3 -> Agent-24 -> SUCCEEDED

| **Role**             | **Typical responsibility**                         |
| -------------------- | -------------------------------------------------- |
| Supervisor           | Global coordination, policy, completion authority  |
| Planner              | Requirement decomposition and execution planning   |
| Implementer          | Code implementation                                |
| Debugger             | Reproduce and fix failures                         |
| Reviewer             | Independent code/architecture review               |
| Security             | Security analysis and remediation                  |
| Tester               | Test design/execution and coverage                 |
| Researcher           | Web/documentation/library research                 |
| Code Intelligence    | Repository mapping and dependency/context analysis |
| Integration          | Merge/cherry-pick/resolve conflicts                |
| Requirement Overseer | Continuous compliance verification                 |
| Adjudicator          | Resolve competing proposals/reviews                |

# 12\. Agent Lifecycle

CREATED -> PLANNING -> RUNNING -> WAITING/BLOCKED -> VERIFYING -> COMPLETED  
| |  
PAUSE_REQUESTED FAILED  
| |  
PAUSED <- RECOVERING <-+  
|  
RESUMING

- Heartbeat and lease renewal are mandatory while running.
- Pause means reaching a safe checkpoint before suspending new work.
- Emergency stop is distinct from normal pause.
- Agent replacement preserves the task and attempt history.
- Every lifecycle transition emits a durable event.

# 13\. Task Protocol

Every assigned task should contain explicit engineering intent:

{  
task_id,  
parent_task_id,  
request,  
expected_output,  
constraints,  
acceptance_criteria,  
dependencies,  
priority,  
context_refs,  
resource_requirements,  
allowed_tools,  
deadline,  
retry_policy  
}

**TASK-001 \[MUST\]** No task should be assigned with only a vague natural-language description when acceptance criteria can be made explicit.

**TASK-002 \[MUST\]** Task state shall be persisted independently of the worker process executing it.

**TASK-003 \[MUST\]** Task attempts shall preserve failure reasons and evidence.

# 14\. Inter-Agent Communication

- Direct asynchronous request/response.
- Broadcast status/event notifications.
- Artifact references instead of large inline payloads.
- Correlation IDs for request/response chains.
- Agents may continue independent work while waiting for another agent.
- Messages are durable and replayable.
- Permission policies determine which agents may communicate or access specific resources.

{  
message_id,  
conversation_id,  
sender_agent_id,  
recipient_agent_id,  
task_id,  
type,  
payload_ref,  
priority,  
created_at,  
correlation_id,  
reply_to,  
expires_at  
}

# 15\. Context Engineering

The context system is a Context Broker/Orchestrator. Agents do not receive the entire project by default. Before each model call, the broker determines what information is necessary, retrieves it, ranks it, compresses it and constructs the context.

| **Context tier** | **Contents**                                      |
| ---------------- | ------------------------------------------------- |
| T0               | Safety/policy/tool permissions                    |
| T1               | Agent identity, current task, acceptance criteria |
| T2               | Global project state and current plan             |
| T3               | Relevant code/symbols/dependencies/tests          |
| T4               | Recent task history and selected agent messages   |
| T5               | Research/evidence/artifacts                       |
| T6               | Raw details only when explicitly required         |

- Maintain token budgets per model call.
- Use progressive disclosure.
- Cache stable summaries but invalidate by repository/version.
- Store raw tool outputs externally.
- Use an RTK-like observation compressor for command/tool output.
- Every context item should carry provenance, timestamp/version and confidence where applicable.

# 16\. Code Intelligence

Use a layered stack rather than choosing one technique as the universal solution.

| **Layer**             | **Purpose**                                                       |
| --------------------- | ----------------------------------------------------------------- |
| Tree-sitter           | Fast syntax parsing, symbols, incremental updates                 |
| LSP                   | Definitions, references, diagnostics, language-specific semantics |
| SCIP                  | Language-agnostic semantic index/interchange                      |
| Lexical/BM25          | Exact names, strings, error messages and configuration retrieval  |
| Embeddings            | Semantic similarity for requirements, docs and code summaries     |
| Dependency/call graph | Repository relationships and impact analysis                      |
| CFG/DFG               | Control and data-flow reasoning                                   |
| PDG                   | Deeper dependency relationships                                   |
| CPG/Joern             | Deep security/program-pattern analysis                            |
| Requirement graph     | Requirement -> task -> symbol -> change -> test -> evidence       |

Context selection should rank evidence by relevance, dependency proximity, authority, freshness and task scope. Repository-wide dumps are prohibited by default.

# 17\. Workspace & Git Isolation

Project  
Workspace  
Repository  
Canonical Branch  
Agent Worktrees  
Runtime(s)  
Index  
Artifacts

- Each parallel code-writing agent gets an isolated branch/worktree when file conflicts are possible.
- Agents must not directly overwrite another active worktree.
- Integration happens through a controlled integration queue.
- Conflicts are treated as explicit tasks.
- Failed attempts remain inspectable and reversible.
- Canonical workspace changes require validation before integration.

# 18\. Concurrency, Locks & Deadlocks

- Use resource leases rather than permanent locks.
- Lockable resources may include files, symbols, ports, environments, branches and exclusive external tools.
- Leases have TTLs and heartbeat renewal.
- Use deterministic lock acquisition ordering.
- Detect dependency cycles before scheduling where possible.
- Use wait timeouts and deadlock detection.
- On worker failure, leases expire or are explicitly released.
- Prefer work decomposition that minimizes shared mutable resources.

# 19\. Execution & Sandbox

- Every agent execution occurs inside a controlled runtime.
- Default MVP runtime: Docker/dev container.
- Per-project and optionally per-agent filesystem isolation.
- CPU, memory, process, disk and execution-time quotas.
- Configurable network policy.
- Secrets are injected only for approved tools and never placed into model prompts.
- Command allow/deny policies are enforced outside the model.
- Host filesystem access is explicit and minimal.
- Raw stdout/stderr is stored as an artifact; compact observations go to the model.

## 19.1 Port Management

- Central port allocator.
- Agents request ports instead of guessing.
- Runtime-to-runtime networking should prefer internal container networking.
- Preview gateway exposes only approved application ports.
- Ports are released when runtimes terminate.

# 20\. Browser & Application Debugging

- Start project runtime and detect preview URL.
- Open application with Playwright.
- Capture screenshots and console errors.
- Inspect network failures and relevant requests.
- Reproduce user-visible bugs.
- Pass compact browser evidence to the debugging agent.
- Apply fix, rerun and verify.
- Store screenshots/videos/logs as artifacts.

# 21\. MCP & Tool System

- Central tool registry.
- Schema validation before invocation.
- Capability/permission checks.
- Timeout and cancellation.
- Retry only when safe/idempotent.
- Tool output normalization.
- Credential isolation.
- Tool provenance and audit events.
- MCP servers may be local or remote, subject to policy.

Tool  
\-> discovery  
\-> authorization  
\-> invocation  
\-> raw result  
\-> normalization/compression  
\-> artifact storage  
\-> model observation

# 22\. Web Research

- Search can be invoked by agents throughout development.
- Research tasks should have explicit questions and evidence requirements.
- Store source URL, title, timestamp, relevant excerpt/summary and confidence.
- Do not flood agent context with complete pages.
- Use compact evidence packets with citations/provenance.
- Separate factual evidence from an agent's interpretation.

# 23\. Requirement Overseer & Traceability

The Requirement Overseer continuously compares the actual implementation with the original requirement and acceptance criteria.

Requirement  
\-> Acceptance Criterion  
\-> Task  
\-> Agent Attempt  
\-> Code Change  
\-> Test  
\-> Evidence  
\-> VERIFIED / FAILED / UNKNOWN

- Requirements may be marked VERIFIED only with evidence.
- Unverified mandatory requirements block final completion.
- Scope drift should create an alert or re-planning event.
- User-approved scope changes become new durable decisions.

# 24\. Debate, Review & Adjudication

Proposer  
\-> Independent Reviewer(s)  
\-> Adversarial Critic  
\-> Evidence Verifier  
\-> Adjudicator  
\-> Decision + Evidence

- Use independent contexts.
- Prefer different model families for high-risk verification where practical.
- Reviewers receive proposal/evidence, not hidden chain-of-thought.
- Bound number of rounds, token budget and time.
- Evidence outranks unsupported preference.
- Persist the final decision and rationale summary.

# 25\. HITL

- Approval before high-impact operations.
- Approval during execution when policy/risk requires it.
- Approval after implementation for final acceptance.
- User can pause/resume/cancel/replan.
- User can edit requirements, constraints and task priorities.
- Approval requests contain clear decision, risk, impact and available choices.
- Timeout behaviour is configurable; sensitive actions should fail closed.

# 26\. Failure & Recovery

| **Failure class**   | **Recovery**                                                 |
| ------------------- | ------------------------------------------------------------ |
| MODEL_FAILURE       | Retry, alternate model, context reduction, replacement agent |
| TOOL_FAILURE        | Retry if safe, diagnose, fallback tool                       |
| ENVIRONMENT_FAILURE | Recreate runtime, restore workspace                          |
| CONTEXT_FAILURE     | Rebuild/retrieve context, reduce noise                       |
| TASK_FAILURE        | Debug/decompose/replan                                       |
| TIMEOUT             | Checkpoint, retry, escalate or reassign                      |
| DEPENDENCY_FAILURE  | Wait, repair dependency, replan                              |
| MERGE_CONFLICT      | Create integration/conflict task                             |
| RESOURCE_LIMIT      | Throttle, resize within policy or reschedule                 |
| HITL_TIMEOUT        | Apply configured safe default or stop                        |
| SECURITY_BLOCK      | Stop action and require review                               |

**REC-001 \[MUST\]** Recovery shall preserve task identity and previous attempt evidence.

**REC-002 \[MUST\]** Retries shall be bounded.

**REC-003 \[MUST\]** Repeated failure shall trigger escalation or replanning rather than infinite looping.

# 27\. Pause / Resume

- Pause request changes agent state to PAUSE_REQUESTED.
- Runtime reaches a safe checkpoint and stops scheduling new actions.
- Current atomic operation may complete if safe.
- Checkpoint includes task state, active context references, workspace state and pending dependencies.
- Resume reconstructs context from durable state rather than relying on process memory.
- Emergency stop is separate and may terminate runtime immediately.

# 28\. Observability & History

execution_id  
agent_id  
task_id  
timestamp  
event_type  
payload  
correlation_id  
trace_id

- Persist important events.
- Stream live events to the UI through WebSocket/SSE.
- Use OpenTelemetry traces across model calls, tools, messages and runtime operations.
- Provide timeline filtering by agent/task/tool/file.
- Track token usage, estimated cost, execution time and retries.
- Keep raw artifacts separately from compact UI summaries.

# 29\. Database Model

Initial PostgreSQL entities:

| **Entity**          | **Key responsibilities**                               |
| ------------------- | ------------------------------------------------------ |
| projects            | Project metadata, configuration, repository references |
| workspaces          | Local workspace/runtime state                          |
| requirements        | Original and revised requirements                      |
| acceptance_criteria | Machine-checkable completion conditions                |
| plans               | Plan versions and approval state                       |
| tasks               | Durable work units and dependency graph                |
| task_attempts       | Agent attempts and outcomes                            |
| agents              | Agent identity, role, model, capabilities and state    |
| agent_sessions      | Runtime execution sessions                             |
| messages            | Inter-agent communication                              |
| context_items       | Durable context/evidence references                    |
| memories            | Project/agent/execution memory                         |
| artifacts           | Files, logs, screenshots, reports and evidence         |
| tool_definitions    | Registered tools and permissions                       |
| tool_calls          | Tool invocation history                                |
| worktrees           | Git isolation metadata                                 |
| resources           | Leases for files/ports/runtimes/etc.                   |
| decisions           | Architecture and engineering decisions                 |
| reviews             | Review/debate results                                  |
| validations         | Tests/security/requirement verification                |
| hitl_requests       | Human decisions and approvals                          |
| events              | Durable execution events                               |
| runtime_instances   | Containers/processes/browser sessions                  |
| toolchains          | Language/build/debug configurations                    |

# 30\. Agent/Task State Persistence

The database is the source of truth. NATS transports events; Redis accelerates coordination; object storage holds large artifacts. No critical execution state may exist only in an in-memory agent process.

# 31\. Security Requirements

**SEC-001 \[MUST\]** All tool execution shall pass through policy enforcement.

**SEC-002 \[MUST\]** Agents shall have least-privilege access to files, network, secrets and tools.

**SEC-003 \[MUST\]** Secrets shall never be embedded into model prompts or persisted in normal logs.

**SEC-004 \[MUST\]** Sensitive tool actions shall support HITL approval.

**SEC-005 \[MUST\]** Untrusted code shall execute in stronger isolation when configured.

**SEC-006 \[MUST\]** Tool outputs shall be treated as untrusted input.

**SEC-007 \[MUST\]** Prompt injection from repository files, web pages and tool output shall not override system policy.

**SEC-008 \[MUST\]** Audit events shall record security-sensitive actions.

**SEC-009 \[MUST\]** User data and project data shall remain local by default unless the user configures external services.

**SEC-010 \[MUST\]** The system shall support credential redaction and secret scanning.

# 32\. Model Routing & Cost Control

- Model selection is a runtime policy, not hard-coded into agents.
- Cheap/fast models handle routine extraction, formatting and low-risk tasks.
- Stronger models handle architecture, difficult debugging and adjudication.
- Independent verification may use a different model family.
- Per-task and per-project token/cost budgets are enforced.
- Context compression is mandatory before expensive calls when equivalent evidence is available.
- Failed attempts must not automatically multiply cost without bounded policy.
- Users can configure preferred models and fallbacks.

| **Role**                  | **Default strategy**                    |
| ------------------------- | --------------------------------------- |
| Routine worker            | Fast/cost-efficient model               |
| Planner                   | Strong reasoning model                  |
| Complex implementer       | Strong coding model                     |
| Reviewer                  | Independent strong model                |
| Security                  | Strong reasoning/security-capable model |
| Adjudicator               | Highest-confidence model within budget  |
| Simple tool orchestration | Fast model                              |

# 33\. UI/UX Specification

The application should have a modern, professional developer-tool visual language with information density comparable to serious IDEs.

| **View**          | **Required capabilities**                                               |
| ----------------- | ----------------------------------------------------------------------- |
| Editor            | Files, tabs, splits, diagnostics, symbols, inline AI actions, diff      |
| AI Command Center | Requirement input, plan, approvals, run controls                        |
| Office            | Agents, tasks, status, tools, communications, waiting/dependencies      |
| Execution Graph   | Live DAG, dependencies, retries, blocked tasks                          |
| Requirements      | Criteria, traceability, verification status                             |
| Diff/Review       | Changes by agent/attempt, comments, merge decisions                     |
| Terminal          | Interactive shells and task-linked terminals                            |
| Runtime           | Containers, processes, ports, previews, resource usage                  |
| History           | Timeline, events, traces, artifacts                                     |
| Settings          | Models, tool permissions, language toolchains, sandbox/network policies |

# 34\. Office / Team Visualization

- Agent cards show role, status, task, model, elapsed time and current tool.
- Show active file/resource where safe.
- Show waiting-on relationships.
- Show communication activity.
- Show spawn/replace/failure events.
- Allow pause/resume/restart/stop where authorized.
- Allow opening the associated task, diff, logs and artifacts.
- Do not display hidden chain-of-thought.

# 35\. API & Event Contracts

Core API domains:

- /projects, /workspaces, /repositories
- /requirements, /plans, /tasks
- /agents, /agent-sessions
- /messages
- /context, /artifacts
- /tools, /tool-calls
- /runtimes, /ports
- /reviews, /validations
- /hitl
- /events
- /models and /routing policies

Real-time channels should stream normalized execution events rather than raw internal process output.

# 36\. Repository Structure

ai-harness/  
apps/  
desktop/  
web-ui/  
services/  
api/  
orchestrator/  
agent-runtime/  
context-engine/  
code-intelligence/  
runtime-manager/  
tool-gateway/  
integration-manager/  
requirement-supervisor/  
packages/  
protocols/  
schemas/  
tool-adapters/  
language-adapters/  
ui-components/  
infrastructure/  
docker/  
temporal/  
nats/  
postgres/  
observability/  
migrations/  
tests/  
unit/  
integration/  
e2e/  
security/  
docs/

# 37\. Implementation Phases

| **Phase** | **Deliverable**         | **Exit criteria**                                         |
| --------- | ----------------------- | --------------------------------------------------------- |
| 0         | Architecture foundation | Repo, CI, schemas, local services, observability skeleton |
| 1         | Conventional editor     | Project open/edit/search/terminal/Git/toolchain basics    |
| 2         | Single-agent harness    | Task creation, tool use, context broker, artifacts        |
| 3         | Durable orchestration   | Temporal workflows, checkpoints, retries, pause/resume    |
| 4         | Multi-agent team        | Dynamic spawn, scheduler, messaging, worktrees            |
| 5         | Code intelligence       | Tree-sitter + LSP/SCIP + retrieval/ranking                |
| 6         | Execution plane         | Containers, quotas, ports, process supervision            |
| 7         | Browser/MCP/web         | Playwright, MCP gateway, research evidence                |
| 8         | Quality/oversight       | Requirement graph, reviewers, security, adjudication      |
| 9         | Office UI               | Live team view, graph, timeline, evidence                 |
| 10        | Hardening               | Security, recovery, performance, packaging, documentation |

# 38\. Detailed MVP Definition

The MVP should already demonstrate the core product identity, not merely a chatbot.

- Desktop app launches locally.
- Open a real repository and edit code manually.
- Auto-detect or configure at least several representative toolchains.
- User enters a software requirement.
- Planner produces durable task graph.
- At least 2–4 agents can execute parallel tasks.
- Agents use isolated Git worktrees.
- Agents communicate asynchronously.
- Agents can run shell/build/test/format commands.
- Tool outputs are normalized/compressed.
- Tasks survive worker failure and can be retried/reassigned.
- User can pause/resume execution.
- Requirement Overseer validates completion.
- Office UI displays live agent activity.
- Final result includes diff, tests, requirement coverage and evidence.

# 39\. Representative End-to-End Scenario

Example: user asks the harness to add a new authentication module to an existing multi-language application.

1. Supervisor inspects repository and detects frontend/backend/toolchains.
2. Planner creates tasks for architecture, backend, frontend, tests and security.
3. Two implementers work in isolated worktrees.
4. Security agent independently reviews authentication design.
5. Test agent prepares and runs tests.
6. Agents exchange structured messages and artifacts.
7. Backend agent encounters a failing integration test; debugger agent is spawned.
8. Requirement Overseer notices one acceptance criterion is not yet evidenced.
9. User receives an approval request before a sensitive migration.
10. Integration manager merges validated changes.
11. Final verification runs build, formatter, tests and security checks.
12. Final report marks each requirement VERIFIED with evidence references.

# 40\. Testing Strategy

| **Level**      | **Coverage**                                                          |
| -------------- | --------------------------------------------------------------------- |
| Unit           | Schedulers, state transitions, context ranking, parsers, adapters     |
| Contract       | Agent/task/message/tool schemas                                       |
| Integration    | Temporal, NATS, PostgreSQL, Redis, runtime manager                    |
| Agent protocol | Spawn, message, checkpoint, failure, replacement                      |
| Concurrency    | Race conditions, resource leases, parallel worktrees                  |
| Recovery       | Crash, timeout, duplicate events, retry exhaustion                    |
| Security       | Sandbox escape attempts, prompt injection, secret leakage, tool abuse |
| E2E            | Requirement -> agents -> code -> tests -> verification                |
| UI             | Editor, office, graph, approvals, history                             |
| Multi-language | Representative compiled/interpreted projects and toolchain adapters   |

# 41\. Performance & Reliability Requirements

**PERF-001 \[MUST\]** The UI shall remain responsive while agents and runtimes execute in the background.

**PERF-002 \[MUST\]** Live event streaming shall be incremental and backpressure-aware.

**PERF-003 \[MUST\]** Scheduler concurrency shall be bounded by configurable limits.

**PERF-004 \[MUST\]** Large logs shall not be injected wholesale into model context.

**PERF-005 \[MUST\]** Recovery operations shall be idempotent where possible.

**PERF-006 \[MUST\]** Durable state must survive application restart.

**PERF-007 \[MUST\]** Agent process loss must not destroy task state.

**PERF-008 \[MUST\]** Index updates should be incremental after file changes.

# 42\. Configuration

- Global settings: model providers, budgets, sandbox policy, event retention.
- Project settings: languages, commands, toolchains, environment variables, test commands.
- Agent policies: allowed tools, model routing, concurrency.
- Security settings: network mode, secrets, approval requirements.
- UI settings: layout, office density, notifications.
- All configuration should be versionable where appropriate.

# 43\. Packaging & Local Deployment

- Package the desktop application for Windows first.
- Bundle or provision required local services through a guided setup.
- Use Docker Desktop/compatible runtime where required by the selected execution mode.
- Provide health checks for PostgreSQL, NATS, Redis, Temporal and runtime dependencies.
- Provide migration/version management.
- Provide a local diagnostics screen.
- Provide export/import of project harness metadata.
- Keep cloud dependencies optional for core editor functionality.

# 44\. Acceptance Criteria for the Complete Product

**AC-001 \[MUST\]** A user can open a real repository and edit/format/build/test code without AI.

**AC-002 \[MUST\]** A user can submit a requirement and receive a structured execution plan.

**AC-003 \[MUST\]** The system can dynamically create multiple agents and execute independent tasks concurrently.

**AC-004 \[MUST\]** Agents can communicate asynchronously and share durable artifacts.

**AC-005 \[MUST\]** Parallel code changes are isolated and safely integrated.

**AC-006 \[MUST\]** Agents can use compilers/interpreters, formatters, linters and test runners for supported toolchains.

**AC-007 \[MUST\]** Agents can pause/resume and recover from worker failure.

**AC-008 \[MUST\]** The system can inspect relevant repository code through semantic/structural indexing.

**AC-009 \[MUST\]** Tool output is compressed before context injection where appropriate.

**AC-010 \[MUST\]** Web/MCP/browser capabilities are permission-controlled and observable.

**AC-011 \[MUST\]** Requirement coverage is continuously tracked.

**AC-012 \[MUST\]** High-risk decisions can be independently reviewed/adjudicated.

**AC-013 \[MUST\]** HITL can intervene without destroying execution state.

**AC-014 \[MUST\]** The Office UI accurately represents live execution state.

**AC-015 \[MUST\]** Final completion is evidence-backed and blocked by unmet mandatory criteria.

**AC-016 \[MUST\]** Application restart does not lose durable execution state.

**AC-017 \[MUST\]** The system supports multiple programming languages through configurable toolchains rather than language-specific hard coding.

# 45\. Definition of Done

- All mandatory requirements have VERIFIED evidence.
- Critical automated tests pass.
- Build/package checks pass.
- Formatting/linting checks pass where configured.
- Security checks pass or documented exceptions have explicit approval.
- No unresolved critical integration conflicts remain.
- No active blocked mandatory task remains.
- Required HITL approvals are complete.
- Execution history and artifacts are persisted.
- Final diff is reviewable.
- Known limitations are explicitly reported.
- Application can restart and recover durable state.
- Representative multi-language projects have passed the end-to-end acceptance suite.

# 46\. Future Extensions

- Remote/cloud execution workers.
- GPU/ML development environments.
- Distributed agent pools.
- Enterprise policy management and SSO.
- Team collaboration across users.
- Advanced semantic code graphs and repository-scale impact analysis.
- Specialized autonomous QA/security environments.
- Marketplace for toolchain/agent adapters.
- Optional model hosting/local models.
- Cross-project organizational memory.

# 47\. Architecture Decision Summary

| **Decision**           | **Final direction**                           |
| ---------------------- | --------------------------------------------- |
| Architecture style     | Stateful agentic software-engineering harness |
| Agent lifecycle        | Ephemeral/replacable                          |
| Task lifecycle         | Durable                                       |
| Orchestration          | Temporal                                      |
| Messaging              | NATS JetStream                                |
| Source of truth        | PostgreSQL                                    |
| Ephemeral coordination | Redis                                         |
| Context                | Hybrid Context Broker                         |
| Code parsing           | Tree-sitter                                   |
| Semantic navigation    | SCIP + LSP                                    |
| Deep analysis          | CFG/DFG/PDG/CPG selectively                   |
| Semantic retrieval     | pgvector + lexical ranking                    |
| Code isolation         | Git worktrees                                 |
| Execution              | Docker/dev containers                         |
| Browser                | Playwright                                    |
| Tools                  | MCP + native adapters                         |
| Observability          | OpenTelemetry                                 |
| Desktop                | Tauri                                         |
| UI                     | React + TypeScript + Monaco                   |
| Backend                | FastAPI                                       |
| Language support       | Extensible toolchain/adapter architecture     |
| Completion authority   | Requirement Overseer + evidence               |
| Human control          | HITL throughout lifecycle                     |

# 48\. Critical Engineering Rules

1. Never make an LLM the authoritative source of execution state.
2. Never make a running agent process the only place where task state exists.
3. Never let parallel agents freely edit the same mutable workspace without isolation.
4. Never inject full raw logs into model context when a compact evidence packet is sufficient.
5. Never accept agent self-reported completion without verification evidence.
6. Never let model instructions bypass external security/policy enforcement.
7. Never create unlimited recursive agents or retries.
8. Never expose hidden chain-of-thought as a product feature.
9. Never hard-code the system around one programming language.
10. Always preserve artifacts and evidence from failed attempts.
11. Always make recovery resumable and observable.
12. Always distinguish facts, evidence, decisions and opinions in durable memory.
13. Always make model/tool selection replaceable through policy.

# 49\. Final Product Mental Model

USER  
|  
REQUIREMENT  
|  
REQUIREMENT ENGINE  
|  
PLAN / DAG  
|  
SUPERVISOR  
|  
+--------------+--------------+  
| | |  
AGENT A AGENT B AGENT C  
| | |  
Context Context Context  
| | |  
Tools Tools Tools  
| | |  
Worktree Worktree Worktree  
+--------------+--------------+  
|  
REVIEW / VERIFY  
|  
REQUIREMENT OVERSEER  
|  
INTEGRATION  
|  
FINAL EVIDENCE PACK  
|  
USER

**End of Specification**