// Engineering intent model (Wave 10): deterministic normalization of
// natural-language requests into structured intents over existing
// capabilities. No model calls, no giant prompts — ordered keyword/pattern
// rules over (verbatim text, UI scope). Unit-tested incl. the §34 cases.

export type IntentType =
  | "implement_feature"
  | "fix_failure"
  | "explain_code"
  | "explain_failure"
  | "find_usages"
  | "find_affected_code"
  | "run_tests"
  | "review_requirement"
  | "review_security"
  | "review_implementation"
  | "create_plan"
  | "start_execution"
  | "control_execution"
  | "open_surface"
  | "ask_architecture"
  | "research_topic"
  | "cost_query"
  | "hitl_guidance"
  | "unsupported"
  | "unknown";

export type ControlKind = "start" | "pause" | "resume" | "stop" | "retry";

export interface IntentScope {
  projectId: string | null;
  requirementId: string | null;
  taskId: string | null;
  agentId: string | null;
  filePath: string | null;
  selectionLines: number;
  hasSelection: boolean;
  hasFailedTask: boolean;
  hasFailureOutput: boolean;
}

export interface EngineeringIntent {
  intentType: IntentType;
  request: string;
  scope: IntentScope;
  control?: ControlKind;
  surface?: string;
  requestedOutcome?: string;
  confirmationRequired: boolean;
  confirmReason: string | null;
  confidence: "high" | "medium" | "low";
  clarifyPrompt: string | null;
}

export interface ClassifyContext {
  projectId: string | null;
  requirementId: string | null;
  taskId: string | null;
  agentId: string | null;
  filePath: string | null;
  selectionChars: number;
  selectionLines: number;
  hasFailedTask: boolean;
  hasFailureOutput: boolean;
}

const has = (text: string, ...words: string[]): boolean =>
  words.some((w) => text.includes(w));

function base(request: string, scope: IntentScope): EngineeringIntent {
  return {
    intentType: "unknown",
    request,
    scope,
    confirmationRequired: false,
    confirmReason: null,
    confidence: "low",
    clarifyPrompt: null,
  };
}

function toScope(ctx: ClassifyContext): IntentScope {
  return {
    projectId: ctx.projectId,
    requirementId: ctx.requirementId,
    taskId: ctx.taskId,
    agentId: ctx.agentId,
    filePath: ctx.filePath,
    selectionLines: ctx.selectionLines,
    hasSelection: ctx.selectionChars > 0,
    hasFailedTask: ctx.hasFailedTask,
    hasFailureOutput: ctx.hasFailureOutput,
  };
}

const SURFACES: { surface: string; words: string[] }[] = [
  { surface: "office", words: ["office", "agents", "team"] },
  { surface: "graph", words: ["graph", "lineage", "dependencies"] },
  { surface: "timeline", words: ["timeline", "history", "events", "what happened"] },
  { surface: "requirements", words: ["requirement", "requirements", "coverage", "criteria"] },
  { surface: "terminal", words: ["terminal", "shell", "console"] },
];

/** Ordered deterministic classification. First match wins; annotated below. */
export function classifyIntent(request: string, ctx: ClassifyContext): EngineeringIntent {
  const text = request.trim().toLowerCase();
  const scope = toScope(ctx);
  const intent = base(request, scope);
  if (!text) {
    intent.clarifyPrompt = "Describe the engineering task, naming the requirement, file, failure, or agent it concerns.";
    return intent;
  }
  const scoped = scope.requirementId ?? scope.taskId ?? scope.agentId ?? scope.filePath;

  // Destructive or out-of-scope verbs: never dispatch, always guide. The
  // Center has no delete/deploy capability, so all such verbs stay here.
  if (/\b(delete|drop|destroy|wipe)\b/.test(text) ||
    has(text, "rm -rf", "format the disk", "production deploy", "deploy to prod")) {
    intent.intentType = "unsupported";
    intent.clarifyPrompt = "That action is not supported from the Command Center. Destructive and deployment operations stay outside it by design.";
    return intent;
  }
  // Approval language must never decide HITL by text.
  if (has(text, "approv", "reject the", "consent")) {
    intent.intentType = "hitl_guidance";
    intent.confidence = "high";
    intent.clarifyPrompt = null;
    return intent;
  }
  // Explicit execution control verbs.
  const controlMatch: [string, ControlKind][] = [
    ["resume", "resume"],
    ["pause", "pause"],
    ["stop", "stop"],
    ["cancel", "stop"],
    ["retry", "retry"],
    ["re-run", "retry"],
    ["rerun", "retry"],
    ["start", "start"],
    ["run it", "start"],
    ["execute", "start"],
  ];
  for (const [word, kind] of controlMatch) {
    if (has(text, word) && (scope.taskId || scope.agentId || has(text, "task", "execution", "workflow", "it", "this"))) {
      intent.intentType = kind === "start" ? "start_execution" : "control_execution";
      intent.control = kind;
      intent.confirmationRequired = true;
      intent.confirmReason = kind === "start"
        ? "Starting execution may run tools and consume model budget."
        : "Control signals change live execution state.";
      intent.confidence = scope.taskId ? "high" : "medium";
      return intent;
    }
  }
  // Failure language with failure scope wins over generic implement.
  if ((scope.hasFailedTask || scope.hasFailureOutput || has(text, "fail", "broken", "error", "stack trace", "exception")) &&
    has(text, "fix", "repair", "resolve", "why", "investigat", "debug", "diagnos", "root cause", "broken", "fail")) {
    intent.intentType = "fix_failure";
    intent.confidence = scope.hasFailedTask || scope.hasFailureOutput ? "high" : "medium";
    return intent;
  }
  // Explanations (skipped when the question is really about external knowledge).
  if (has(text, "explain", "what does", "what is", "describe", "how does", "walk me through") &&
    !has(text, "best practice", "how do others", "research", "compare", "alternative", "recommend")) {
    if (scope.hasFailedTask || scope.hasFailureOutput || has(text, "fail", "error")) {
      intent.intentType = "explain_failure";
    } else {
      intent.intentType = "explain_code";
    }
    intent.confidence = scope.filePath || scope.hasSelection ? "high" : "medium";
    return intent;
  }
  // Repository relationships (deterministic intel, never LLM guesses).
  if (has(text, "where", "usages", "used", "callers", "calls this", "references", "who calls")) {
    intent.intentType = "find_usages";
    intent.confidence = scope.filePath ? "high" : "medium";
    return intent;
  }
  if (has(text, "affect", "impact", "blast radius", "related code", "dependenc")) {
    intent.intentType = "find_affected_code";
    intent.confidence = scoped ? "high" : "medium";
    return intent;
  }
  // Tests.
  if (has(text, "test") && has(text, "run", "execute", "pytest", "all tests", "related tests")) {
    intent.intentType = "run_tests";
    intent.confirmationRequired = true;
    intent.confirmReason = "Running tools executes project commands.";
    intent.confidence = "high";
    return intent;
  }
  // Reviews.
  if (has(text, "review", "audit", "inspect")) {
    if (has(text, "secur", "vuln", "threat", "injection", "auth flow")) {
      intent.intentType = "review_security";
      intent.confidence = scope.filePath || scope.requirementId ? "high" : "medium";
      return intent;
    }
    if (scope.requirementId || has(text, "requirement", "coverage", "criteria", "acceptance")) {
      intent.intentType = "review_requirement";
      intent.confidence = "high";
      return intent;
    }
    intent.intentType = "review_implementation";
    intent.confirmationRequired = true;
    intent.confirmReason = "Reviews invoke model reviewers and consume budget.";
    intent.confidence = scope.taskId ? "high" : "medium";
    return intent;
  }
  // Research (external network → confirmation). Strong triggers only, and
  // before explanations so "best practice" questions route correctly.
  if (has(text, "research", "best practice", "how do others", "compare", "alternative", "recommend")) {
    intent.intentType = "research_topic";
    intent.confirmationRequired = true;
    intent.confirmReason = "Research performs external network lookups.";
    intent.confidence = "medium";
    return intent;
  }
  // Planning / implementation.
  if (has(text, "plan", "break down", "steps to", "roadmap", "task list")) {
    intent.intentType = "create_plan";
    intent.confidence = scoped ? "high" : "medium";
    return intent;
  }
  // Pronoun-only requests without scope clarify instead of guessing.
  const hasPronoun = /\b(it|this|that|them)\b/.test(text);
  if (has(text, "implement", "build", "create", "add", "refactor", "optimize", "migrate", "document", "generate tests", "write tests", "fix", "repair")) {
    if (!scoped && hasPronoun) {
      intent.clarifyPrompt = "I need scope first: select a requirement, file, failure, task, or agent — or name one — then ask.";
      return intent;
    }
    intent.intentType = "implement_feature";
    intent.confirmationRequired = true;
    intent.confirmReason = "Creating tasks starts real tracked work; execution is a separate confirmed step.";
    intent.confidence = scoped ? "high" : "medium";
    return intent;
  }
  if (!scoped && hasPronoun) {
    intent.clarifyPrompt = "I need scope first: select a requirement, file, failure, task, or agent — or name one — then ask.";
    return intent;
  }
  // Navigation.
  if (has(text, "open", "show", "go to", "navigate", "switch to")) {
    for (const entry of SURFACES) {
      if (has(text, ...entry.words)) {
        intent.intentType = "open_surface";
        intent.surface = entry.surface;
        intent.confidence = "high";
        return intent;
      }
    }
  }
  // Architecture / health.
  if (has(text, "architect", "structure", "health", "overview", "how is", "status of the project", "latest", "current")) {
    intent.intentType = "ask_architecture";
    intent.confidence = "medium";
    return intent;
  }
  // Costs.
  if (has(text, "cost", "token", "spend", "budget", "how much")) {
    intent.intentType = "cost_query";
    intent.confidence = "high";
    return intent;
  }
  // Fallback: clarify with selectable scope, never guess.
  intent.clarifyPrompt = scoped
    ? "I could not map that to an engineering action. Try: implement, fix, explain, review, run tests, or open a surface."
    : "I need scope first: select a requirement, file, failure, task, or agent — or name one — then ask.";
  return intent;
}
