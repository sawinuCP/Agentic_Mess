# Wave 4 performance checkpoint — partial, not complete

## Environment and scope

Windows, 8 logical processors, 16,905,965,568 bytes RAM. Existing Docker Postgres,
Redis, NATS and Temporal were running. No new infrastructure, indexes, cache or
schema changes. This checkpoint addresses two measured bottlenecks, not all Wave 4 criteria.

## Findings

Measured:
- Task lists issued two related-data queries per task, plus the task query.
- Process output caps applied after `communicate()` buffered all output.
- Event listing used the existing project/time index; no new index justified yet.

Inspected but not performance-validated:
- Several collection routes, including task lists, remain unpaginated.
- Symbol retrieval caps symbols at 5,000 but loads project file metadata separately.
- Timeline state is capped at 120 events; historical navigation remains incomplete.
- Office has an explicit 10-second degraded fallback poll (not the old 2.5-second poll).
  Earlier statements that no fallback remains were inaccurate.
- Temporal Worker construction has no explicit application-configured concurrency arguments.
- Artifact reads load full blobs; optional age-based deletion does not distinguish final
  evidence from disposable output. Do not enable it as a safe archival policy.

## Implemented changes

Process runner: drain stdout/stderr concurrently, retain only the configured character prefix,
use incremental UTF-8 decoding, preserve diagnostics on timeout, and clean up on cancellation.
Existing environment sanitization remains. Excess output is discarded, not archived; streaming
full raw output into artifacts is still open work.

Task service: fetch tasks, dependencies and attempts in three statements (one for empty lists).
Related-data subqueries preserve project/status filters without an expanding parameter list.
Response fields and attempt ordering remain intact. This fixes N+1 but does NOT paginate or
bound overall task response size.

## Before/after results

Task-only dataset, five samples per size, created inside rolled-back transactions:

| Tasks | Queries before / after | Median before / after |
|---:|---:|---:|
| 10 | 21 / 3 | 51.169 / 9.827 ms |
| 100 | 201 / 3 | 461.889 / 20.280 ms |
| 500 | 1,001 / 3 | 2,020.126 / 102.439 ms |

Single process-output samples, 1,000-character cap, tracemalloc Python allocation peak:

| Output | Peak before / after | Duration before / after |
|---:|---:|---:|
| 1 MiB | 2.176 / 0.607 MiB | 0.222 / 0.283 s |
| 16 MiB | 32.167 / 0.581 MiB | 0.203 / 0.429 s |
| 64 MiB | 128.256 / 0.580 MiB | 1.165 / 0.816 s |

Some after samples ran alongside validation; timing is noisy, not a throughput claim.
The 16 MiB run became slower. The demonstrated improvement is bounded capture memory.
Tracemalloc is not whole-process RSS, child memory or a long-running leak test.

## Repeatable benchmarks and regression budgets

Run `scripts/benchmark_wave4.py` using the repository virtualenv, preferably from the API
working directory to load its settings (or supply HARNESS_DATABASE_URL).
Arguments: `--tasks 10 100 500 --samples 20 --output-mib 1 16 64 --output <outside-repo-path>`.
It generates deterministic task content, dependency edges and one attempt per task;
IDs are run-namespace-scoped. All generated rows roll back. No model calls.
This is not yet a generator for every domain entity.

Final repeat with related data, 20 warmed samples:

| Tasks | p50 ms | p95 ms | p99 ms | Query budget | Status |
|---:|---:|---:|---:|---:|---|
| 10 | 11.052 | 17.474 | 26.757 | 3 | PASS |
| 100 | 32.720 | 48.205 | 84.191 | 3 | PASS |
| 500 | 121.896 | 154.190 | 171.073 | 3 | PASS |

At 20 samples p99 is the sample maximum, not a reliable tail estimate.
Dual-pipe regression emits 16 MiB per pipe: Python peak budget <8 MiB with caps 0/1,000 PASS.
Structural budgets are tested; end-to-end latency budgets remain to be established.

Read-only event API baseline: 100 requests, concurrency 5; 2,066 total events, selected
project 27 events; 12,170-byte response. p50 63.049 / p95 100.647 / p99 193.074 ms;
zero errors. EXPLAIN ANALYZE used ix_events_project_occurred; execution 2.288 ms in one sample.
This small dataset does not establish large-history scalability.

## Validation

- Backend: 338 passed, two dependency deprecation warnings, 61.78 seconds.
- Focused task regression: 3 passed; filters, project isolation and DTO parity.
- Runner plus Wave 1 security selection: 46 passed.
- Backend Ruff passed. Mypy passed, 263 source files.
- Benchmark script checked with API Ruff configuration and executed successfully.
- Frontend: 10 tests passed; lint has existing CodeEditor fast-refresh warning.
  TypeScript/Vite build passed with bundle-size warning (main JS approximately 3.87 MB).
- Disposable fresh-database validation: Alembic migrated 0001→0010 from scratch and the
  full backend suite passed 338 tests in 52.07 s; the temporary database was dropped after.
  The earlier schema-only check failed only because pgvector lives in the shared public
  schema; a URL-encoded search-path attempt also failed on Alembic interpolation.
- No fresh complete live Temporal/recovery/browser smoke chain executed.

Raw output resides outside the repository in the OS temporary harness-wave4 directory.

## Open acceptance items

Complete query/index audit; coordinated pagination; large-history/UI benchmarks; resource
limits and worker concurrency; safe reference-aware retention; artifact streaming; repository,
index/search/context benchmarks; render profiling/virtualization; concurrent agent/container/
port/worktree validation; NATS bursts; cost monitoring; extended leak/soak tests; clean Alembic
validation and live smoke battery. No production-capacity or long-running stability claim.
Wave 5 has not started.

## Verification round — 2026-09-18 (measured on the same box)

Environment: Windows, Docker Desktop (Postgres :15432, NATS :14222, Temporal
:7233 all healthy). No new infrastructure; one behavior-neutral error-type fix
(`ArtifactStoreError` is now a `DomainError`, so pruned-blob 404s no longer
escape as 500s).

### Bottlenecks found by measurement

| # | Finding | Evidence | Fix | After |
|---|---------|----------|-----|-------|
| 1 | Requirements list N+1 (criteria per row) | 20 reqs → **21 queries** (counted) | Batched criteria (2 queries) + `limit`/`offset` | **2 queries** (test asserts) |
| 2 | Unbounded agents / requirements / memories / context-items lists | no `limit` in SQL; leases fetched-all-then-sliced in Python | `limit`/`offset` on agents + requirements; `limit` on memories/items; SQL-side status filter + limit for leases | all bounded server-side (tests assert tiling + caps) |
| 3 | Artifact content loads full blob into memory | `store.open` → `read_bytes`, no Range | Constant-memory chunked streaming + single-range 206/416 + `Accept-Ranges` | 10 KiB fixture: full/range/suffix/416 verified |
| 4 | Temporal worker concurrency = SDK defaults | no `max_concurrent_*` in `worker.py` | `HARNESS_TEMPORAL_MAX_CONCURRENT_WORKFLOWS` (10) / `_ACTIVITIES` (4) / `_ACTIVITIES_PER_SECOND` (0 = off) | asserted in `test_config.py` |
| 5 | Blob retention blind to evidence | age-only prune could delete final evidence | Reference-aware prune: attempt + terminal-task evidence shas spared (event payloads excluded by design — they duplicate attempt evidence) | evidence blob survives, disposable pruned (test asserts) |

### Deliberately NOT changed (measured adequate)

* **Indexes**: EXPLAIN on the new paginated queries shows index scans
  (`ix_requirements_project`, 0.65 ms; leases via `ix_resources_expires` with
  SQL-side filter+limit). No new indexes — write overhead unjustified at
  measured scale. Full audit table recorded in the verification log below.
* **Codeintel**: 500-file / 1500-symbol synthetic repo — full index 7.6 s,
  incremental noop 68 ms, retrieval 269 ms. Incremental path already skips by
  sha; no bottleneck found.
* **Frontend virtualization**: lists are bounded at the data layer (100/page
  agents+tasks, 120-event timeline cap, 0 selector invalidations in the
  foundation perf test). No virtualization library added.
* **NATS/Temporal/Redis replacement**: nothing measured warrants it.

### Index audit (verified 2026-09-18, live DB)

| Table | Index | Serves |
|---|---|---|
| requirements | `ix_requirements_project (project_id)` | page filter (sort is in-memory, sub-ms measured) |
| acceptance_criteria | `ix_acceptance_criteria_requirement (requirement_id)` | batched criteria fetch |
| agents | `ix_agents_project_state (project_id, state)` | project page filter |
| resources | `ix_resources_expires (expires_at)`, `uq_resources_kind_key (kind, key)` | expiry scans; scheduler conflict checks |
| tasks | `ix_tasks_project_status`, `ix_tasks_requirement`, `ix_tasks_plan`, `ix_tasks_parent` | list filter, graph joins |
| events | `ix_events_project_seq (project_id, project_seq)` | replay + resync cursors |

### Performance matrix (§52)

| Scenario | Dataset/Load | Metric | Result | Target | Status |
|---|---|---|---|---|---|
| Requirements list | 20 reqs + criteria | queries | 2 | ≤3 | PASS |
| Requirements list | 7 reqs | tiling limit=5 | 5+2 exact | exact | PASS |
| Agents list | 5 agents | tiling limit=3 | 3+2 exact | exact | PASS |
| Memories / context-items | 120 rows each | returned | 100 + 100 (caps) | ≤100 | PASS |
| Leases filtered | 3 leases | SQL-side filter+limit | exact per status | exact | PASS |
| Artifact content | 10 KiB blob | full/range/suffix/416 | all correct | correct | PASS |
| Hot-read soak | 60 rounds tasks+reqs | tracemalloc growth | <5 MiB | <5 MiB | PASS |
| Codeintel full index | 500 files / 1500 symbols | duration | 7.6 s | <60 s | PASS |
| Codeintel incremental noop | same, unchanged | duration | 0.068 s | <5 s | PASS |
| Codeintel retrieval k=6 | same index | latency | 269 ms | <2 s | PASS |
| Task list (prior round) | 500 tasks | p50/p95/p99 | 122/154/171 ms, 3 queries | 3 queries | PASS |

### Remaining Wave 4 residuals (honest)

* 100k-event index review under production-like volume (dataset too small here).
* Long soak (hours) for RSS-level leaks — tracemalloc covers Python allocs only.
* Concurrent agent/container/port/worktree stress beyond existing quota/chaos tests.
* NATS burst + cost-monitoring dashboards (metrics exist; no UI yet — Wave 6+).
* Artifact streaming uses single-range only (multi-range → 416).
