# Real-World Validation Results (Wave 12)

Measured on the dev box (Windows, Docker Desktop, live Postgres/NATS/Temporal).
No model calls; rehearsal + fakes throughout.

## Retrieval & indexing (fixtures A/B/E/F)

| Check | Result |
|---|---|
| Project A index + top-1 `add` | PASS (ms-scale) |
| Project B TSX `SettingsButton` retrieval | PASS |
| Project E messy comprehension (`calc_total` wins) + read-only proof | PASS |
| Project F 2000 modules: full index | bounded (tens of seconds; exact in test output `REALWORLD`) |
| Project F incremental noop (500→500 skipped) | ~0.1 s scale |
| Project F exact `process_payload_1999` top-k | PASS after fixes below |
| Context bundle on 2000-function input | ≤8000 tokens, truncation markers present |

## Failures found and fixed (§24 loop)

1. **Lexical tokenizer ignored identifier structure** — `process_payload_1999`
   was one opaque token; digit-suffixed symbols invisible to exact search.
   Fix: snake/camel split aligned with the embedding tokenizer.
2. **Digit-leading query terms dropped** (`1999` never tokenized in queries).
   Fix: tokenizer accepts leading digits in both modules.
3. **Semantic noise outranked exact matches** — with uninformative vectors the
   0.4 semantic term beat the best lexical score. Fix: exact lexical matches
   are never outranked (`max(lex_norm, blend)`); semantics still breaks ties
   and finds synonyms.
4. **Pause path violated the lifecycle twice** — `running → paused` and
   `resuming → verifying` both crashed the checkpoint activity, so pausing
   any execution failed the workflow. Fix: lawful
   `running → pause_requested → paused` and resume through `running`.
   Proven by pause-park-resume-complete with a single attempt.
5. **API-created tasks unexecutable** (Wave 11 fix, exercised here): validated
   `payload` on `TaskIn`; journey test creates tasks purely via HTTP.

## Ambiguity, pause, docker, multi-client

| Check | Result |
|---|---|
| Vague requirement + no evidence → UNKNOWN (never VERIFIED) | PASS |
| Pause mid-execution → parked (`paused`) → resume → success, 1 attempt | PASS |
| Docker backend real execution (`python:3.11-slim` cached) + `6*7=42` | PASS |
| `--network none` container cannot reach 8.8.8.8:53 | PASS (SEC-005 live) |
| Two SSE clients converge on identical cursors (replay + live) | PASS |
| Workflow history bound (83 events for a full run, budget 300) | PASS |
