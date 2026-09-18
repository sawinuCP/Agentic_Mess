# Execution Timeline performance — Wave 9

Measured 2026-09-18 (`src/timeline/performance.test.ts`, seeded synthetic
histories, node-side derivation).

## Derivation measurements

```json
{"benchmark":"wave9-timeline","events":100000,"normalized":100000,
 "searched":12155,"rosterTasks":100,"merged":100000,"elapsedMs":1331}
```

100,000 events normalize + search + full replay fold + page merge in
~1.3 s. 1k/10k scales complete far under the 5 s unit bound. Consequences:

- **No snapshot caching** (§19 measure-first: folds are single-digit
  milliseconds at 10k; snapshots would add versioning/invalidation
  complexity for no gain — documented decision, not an omission).
- **No virtualization library**: the DOM never holds the history. Pages are
  500 rows, rendering is chunked at 200 + "show more", replay holds one
  snapshot object. Browser frame timing for thousand-row chunks remains
  unprofiled (same standing caveat as Waves 6–8); the chunk control keeps
  the rendered set small by construction.
- Search runs over loaded rows only (labeled in-UI); the server narrows by
  `event_type`/`task_id` first. 12k-hit substring search over 100k rows is
  included in the 1.3 s above.

## Load characteristics

- Backward cursor paging (`before_seq` + strict `<`, symmetric with
  `since_seq`), 500 rows/page, id-dedupe merge; short page ⇒ exhausted with
  an explicit "history begins here" boundary note.
- Replay timer exists only while playing (cleaned up on pause/exit/
  unmount); speeds map to intervals, stepping is exact array indexing.
- SSE stream untouched; resync path untouched. The History view never
  writes the 120-row office projection.

## Regression coverage

- `timeline/performance.test.ts`: 1k/10k/100k derivation bounds.
- `timeline/model.test.ts`: ordering, dedupe, fold, sanitize, correlation.
- `smoke_history.py`: 514-event cursor paging across two real pages.
