# Performance Envelope (Wave 12 — demonstrated, not claimed)

Measured on the dev box (Windows, Docker Desktop, live infra). Do not present
these as production SLAs.

| Workload | Measurement |
|---|---|
| Task/requirement lists | 2–3 queries; paginated; sub-ms–tens of ms |
| Codeintel full index, 500 files / 1500 symbols | ~7.6 s |
| Codeintel incremental noop, 500 files | ~0.07 s |
| Codeintel retrieval k=6 | ~0.27 s |
| Codeintel 2000 modules | bounded (tens of seconds; exact in test output) |
| Context bundle, 2000-function input | ≤8000 tokens, truncation marked |
| 8 parallel agents, quota 2 | 2 run + 6 clean deferrals, no crash |
| Workflow history, full run | 83 events (budget 300) |
| Live NATS fan-out, 300 events / 3 clients | seconds end-to-end, in order |
| Gateway fan-out, 1000 events / 5 clients | < 5 s, drops counted |
| Eval full suite, 10 cases | ~67–76 s |
| Frontend suite | 144 tests, seconds; 0 selector invalidations |
| SSE reconnect + replay | covered by scenarios D/G + multi-client test |

## Operating envelope (supported by evidence)

* Agents: 8 concurrent proven; 25–50 tiers NOT demonstrated — do not promise.
* Repositories: 2000 modules proven; 100k symbols NOT measured.
* Histories: hundreds of events proven; hour-scale soak NOT run.
* Realtime: single process; multi-replica NOT supported.
