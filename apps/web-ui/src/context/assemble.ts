// Context assembly (Wave 10): client-side T0–T5 snapshot mirroring broker
// tiering without duplicating it. Budgets enforced, secrets redacted, every
// truncation labeled. Pure and unit-tested.

const DEFAULT_BUDGET_CHARS = 12_000;
const DEFAULT_SLICE_LINES = 80;
const DEFAULT_MAX_SYMBOLS = 15;
const DEFAULT_MAX_EVENTS = 10;
const DEFAULT_MAX_TESTS = 6;
const DEFAULT_MAX_SELECTION = 2000;

/** Redact hardcoded secret-looking assignments in code text. */
export function redactSecrets(text: string): { text: string; redacted: boolean } {
  const pattern = /((?:password|passwd|secret|api[_-]?key|access[_-]?key|client[_-]?secret|auth[_-]?token)\s*[:=]\s*)(["'][^"'\n]{1,200}["']|[^\s,;)\n]{4,200})/gi;
  let redacted = false;
  const out = text.replace(pattern, (_m, prefix: string) => {
    redacted = true;
    return `${prefix}"[redacted]"`;
  });
  return { text: out, redacted };
}

export interface AssembleInputs {
  actionLabel: string;
  scopeLabel: string;
  safetyNote: string | null;
  entityLines: string[];
  requirementLine: string | null;
  filePath: string | null;
  fileContent: string;
  selection: { startLine: number; endLine: number; text: string } | null;
  symbols: { name: string; kind: string; line: number }[];
  relatedTests: { path: string; name: string }[];
  executionLines: string[];
  agentLines: string[];
  dependencyLines: string[];
  recentEvents: string[];
  attemptLines: string[];
  artifactRefs: string[];
  budgetChars?: number;
  sliceLines?: number;
  maxSymbols?: number;
  maxEvents?: number;
  maxTests?: number;
  maxSelection?: number;
}

export interface ContextSnapshot {
  t0: string[];
  t1: string[];
  t2: string[];
  t3: string[];
  t4: string[];
  t5: string[];
  truncated: string[];
  totalChars: number;
  withinBudget: boolean;
}

export function assembleContext(inputs: AssembleInputs): ContextSnapshot {
  const budget = inputs.budgetChars ?? DEFAULT_BUDGET_CHARS;
  const sliceLines = inputs.sliceLines ?? DEFAULT_SLICE_LINES;
  const maxSymbols = inputs.maxSymbols ?? DEFAULT_MAX_SYMBOLS;
  const maxEvents = inputs.maxEvents ?? DEFAULT_MAX_EVENTS;
  const maxTests = inputs.maxTests ?? DEFAULT_MAX_TESTS;
  const maxSelection = inputs.maxSelection ?? DEFAULT_MAX_SELECTION;
  const truncated: string[] = [];

  const t0 = [inputs.actionLabel, `Scope: ${inputs.scopeLabel}`];
  if (inputs.safetyNote) t0.push(inputs.safetyNote);

  const t1 = [...inputs.entityLines];
  if (inputs.requirementLine) t1.push(inputs.requirementLine);

  const t2: string[] = [];
  if (inputs.filePath && inputs.fileContent) {
    const lines = inputs.fileContent.split("\n");
    let slice: string[];
    let note: string | null = null;
    if (inputs.selection) {
      const { startLine, endLine } = inputs.selection;
      const from = Math.max(0, startLine - 21);
      const to = Math.min(lines.length, endLine + 20);
      slice = lines.slice(from, to);
      note = `slice lines ${from + 1}–${to} of ${lines.length}`;
    } else {
      slice = lines.slice(0, sliceLines);
      if (lines.length > sliceLines) note = `first ${sliceLines} of ${lines.length} lines`;
    }
    let text = slice.join("\n");
    if (inputs.selection && inputs.selection.text.length > maxSelection) {
      truncated.push(`selection capped at ${maxSelection} chars`);
    }
    const redacted = redactSecrets(text);
    text = redacted.text;
    if (redacted.redacted) truncated.push("secret-shaped assignments redacted in code slice");
    t2.push(`File ${inputs.filePath}${note ? ` (${note})` : ""}:\n${text}`);
  }
  const symbols = inputs.symbols.slice(0, maxSymbols);
  if (inputs.symbols.length > maxSymbols) truncated.push(`symbols capped at ${maxSymbols}`);
  for (const s of symbols) t2.push(`Symbol ${s.name} (${s.kind}) @ line ${s.line}`);
  const tests = inputs.relatedTests.slice(0, maxTests);
  if (inputs.relatedTests.length > maxTests) truncated.push(`related tests capped at ${maxTests}`);
  for (const t of tests) t2.push(`Related test ${t.name} (${t.path})`);

  const t3 = [...inputs.executionLines, ...inputs.agentLines, ...inputs.dependencyLines];
  const events = inputs.recentEvents.slice(0, maxEvents);
  if (inputs.recentEvents.length > maxEvents) truncated.push(`events capped at ${maxEvents}`);
  for (const e of events) t3.push(`Event: ${e}`);

  const t4 = [...inputs.attemptLines];
  const t5 = inputs.artifactRefs.length > 0
    ? [`Artifact refs (metadata only): ${inputs.artifactRefs.join(", ")}`]
    : [];

  const totalChars = [...t0, ...t1, ...t2, ...t3, ...t4, ...t5].join("\n").length;
  const withinBudget = totalChars <= budget;
  if (!withinBudget) truncated.push(`snapshot ${totalChars} chars exceeds ${budget} budget`);
  return { t0, t1, t2, t3, t4, t5, truncated, totalChars, withinBudget };
}
