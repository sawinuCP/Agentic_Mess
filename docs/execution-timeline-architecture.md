# Execution Timeline architecture — Wave 9

Status: contract inspection completed before implementation (paths cited).
Authoritative source: the **PostgreSQL `events` table** via `GET
/api/events` — never NATS (transport only), never the 120-row office
projection, never Temporal internals.

## 1. Event sources

- Durable history: `GET /api/events?project_id&order&limit` (default 100,
  max 500), forward cursor `since_seq`, backward cursor `before_seq` and
  `task_id` scope added in Wave 9 (additive params on the existing route —
  no new infrastructure), exact `event_type` filter (pre-existing).
  `EventOut` now also exposes `correlation_id` (indexed column, was
  SSE-only).
- Live edge: the existing SSE stream + office store (newest ~120). History
  view merges head arrivals explicitly ("N new events") rather than
  silently interleaving.
- Retention: pruning is opt-in (`retention_events_days=0` default); when
  enabled, pruned prefixes are silently absent — the UI labels the oldest
  loaded event as "history begins here" without claiming completeness.

## 2. Event normalization (`src/timeline/model.ts`)

`EventEntry` → `TimelineEvent`: stable id, type, ISO timestamp, numeric
sequence (nullable), execution/task/agent/correlation ids, actor
(agent→name/role, task→title, system fallback), one-line summary, derived
status + tone, related resources (files, worktree, commit, tool, test,
artifacts — each labeled persisted vs derived), evidence refs, raw payload
(sanitized, collapsed by default). Backend domain models are referenced,
not duplicated; unknown types render with their raw label, never as success.

## 3. Ordering

`project_seq` ascending is the total order (gapless per project, assigned
in-transaction); `occurred_at` breaks ties and labels rows. `desc` pages
stay newest-first; reconstruction folds ascending. Duplicate deliveries
dedupe by event id on merge.

## 4. Pagination

Backward cursor paging: newest page (`order=desc, limit=500`), then
`before_seq=min(seq)` repeatedly until a short page (exhausted). Merged
client-side with id-dedupe. Chunked rendering (200 rows + "show more")
bounds the DOM; no virtualization library. `task_id` scoping and
`event_type` narrowing happen server-side; text search runs over loaded
rows with a "searches loaded history only" label.

## 5. Replay model

Replay = fold ascending events through a pure projection
(`src/timeline/replay.ts`), scrubbed by index: play/pause/step/speeds
(0.5/1/2/5/10×)/jump-to-event. Reconstructed state covers agent roster +
states, task states, counts, active set, failure/recovery milestones, tool
outcomes, HITL requests, commits — everything derivable from the event
record. Explicitly NOT reconstructed (labeled wherever relevant):
attempt-level detail, payload values, pre-window history, requirement
verification states (shown as-of-now from the traceability report),
message contents (no message events exist). Replay never writes the live
store and never executes anything; speeds map to intervals, stepping is
exact. No snapshot caching (§19: measure-first — folds over 10k events
measure in single milliseconds, so snapshots would add complexity for no
gain; documented with numbers).

## 6. Filtering

Category (execution/tasks/agents/tools/communication/recovery/validation/
artifacts/HITL mapped from the real 39-literal vocabulary — categories
without events render empty with the reason, never with invented rows),
status (derived tones), entity (agent/task/requirement selects; requirement
scoping resolves through task links and says so), time (entire loaded
window / recent-N / custom range inputs over loaded data). Filtering
preserves chronological order; counts disclose hidden rows.

## 7. State reconstruction

Pure fold, O(steps) per scrub, memoized per (eventsHash, index). Roster
entries carry `lastEvent` + `since` for "why is it in this state" answers.
Requirement verification is intentionally excluded from the fold (no
verification events exist) and displayed as-of-now.

## 8. Performance strategy

Bounded pages (≤500), chunked DOM (200 + more), memoized normalize/filter/
fold, no polling (replay timer only while playing, cleaned up), synthetic
seeded generators for 1k/10k/100k node-side measurements (see
`docs/execution-timeline-performance.md`). Snapshots deliberately omitted
per measurement.

## 9. Security

Same auth/project isolation on every fetch; payload sanitizer redacts
secret-shaped keys, truncates long strings, caps depth/breadth (unit-tested
with attack samples); raw payload collapsed by default; artifact content
never fetched (metadata only); no chain-of-thought exists in events, and
message payload values stay unrendered per Wave 7.

## 10. Retention interaction

With pruning disabled (default), history is complete from the first stored
event. With pruning enabled, the oldest loaded page is labeled as the
retention boundary. The UI never claims an unloaded prefix.
