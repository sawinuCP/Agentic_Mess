# Failure Patterns (Wave 12 §23)

Clustered from real failures found by validation (not hypotheticals). Each
pattern states whether it was local or architectural.

## Local bugs (fixed, regression-tested)

1. **Skipped lifecycle steps** (orchestration): pause path jumped
   `running → paused` and resumed `resuming → verifying`, both unlawful.
   Pattern: workflow authors bypassing the transition matrix. Fix: lawful
   multi-step transitions; pause test enforces.
2. **Check-then-set races** (persistence): HITL decide and lease/slot acquire
   crashed or split under concurrency. Pattern: read-without-lock then write.
   Fix: `SELECT FOR UPDATE` for decisions; rollback + re-read for leases.
3. **Tokenizer asymmetry** (code intelligence): lexical and embedding
   tokenizers disagreed on splits and digit terms; semantic noise outranked
   exact matches. Pattern: two implementations of one contract. Fix: one
   shared split rule + max-guard on the blend.
4. **Stale test doubles** (tests): smoke assertions on exact glyph text and
   positional tab indices. Pattern: overspecific selectors. Fix: role-based
   selectors.

## Architectural (by design, documented)

5. **Dead waits**: every parked wait now has either a signal source, a
   deadline, or a pre-check (dependency pre-check, HITL timeouts). Rule for
   new waits: prove the wake-up path in a test.
6. **Evidence vs state**: rollback restores tracked state only; untracked
   files survive; nothing destructive is automatic. Rule: destructive
   operations require explicit human force.
7. **Single-process realtime**: buckets and registries are in-memory.
   Multi-replica would need shared state — out of scope for local-first.

## Watchlist (no evidence yet — do not "fix" without reproduction)

* NATS redelivery storms under large backlogs.
* pgvector index choice at 100k+ symbols (currently exact scan + limits).
* Workflow history growth beyond ~10 attempts (measured 83 events/run).
