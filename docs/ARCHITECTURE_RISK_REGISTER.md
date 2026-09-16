# Architecture Risk Register

| ID | Risk | Area | Likelihood | Impact | Evidence | Mitigation | Status |
|----|------|------|-----------|--------|----------|------------|--------|
| AR-01 | Office UI polls REST every 2.5 s — event latency, wasted load, does not scale to many projects/agents | Observability/Frontend | High | Medium | `state/officeStore.ts` (POLL_MS=2500) | SSE stream (W3-STREAM-1) | OPEN |
| AR-02 | Unbounded growth of `events`, artifacts, `model_invocations` | Data | High | Medium | No retention code paths exist | Retention/prune worker (W3-RETAIN-1) | OPEN |
| AR-03 | Recovery decisions are advisory — workflow retries identically instead of using class-specific actions | Reliability | Medium | High | `durable/activities/execution.py` returns `recovery`; workflow ignores it | Consume plan in workflow (W2-RECOV-1) | OPEN |
| AR-04 | In-memory singletons (terminals, browser sessions, office state) assume a single API process | Architecture | Medium | Medium | `TerminalManager`, `BrowserManager` in lifespan | Document single-worker; externalize sessions if scaling needed | OPEN (documented) |
| AR-05 | No DLQ for JetStream poison messages — repeated redelivery could loop | Messaging | Low | Medium | `messaging/broker.py` (dedup only) | DLQ + redelivery ceiling (W2-MSG-1) | OPEN |
| AR-06 | Diagnostics probes run sync DB/IO on the event loop | Performance | Medium | Low | `routes/core/diagnostics.py` | Wrap in to_thread (W3 follow-up) | OPEN |
| AR-07 | Context engine lacks long-history compaction — very long tasks may crowd lower tiers | AI | Medium | Medium | `context_broker.py` budget trimming only | Compaction pass (W4-PERF-3) | OPEN |
| AR-08 | Tool permissions are command-pattern based; capability model (spec §11) not implemented | Security | Medium | High | `agents_runtime/gateway.py` APPROVAL/DENY patterns | Capability model (Wave 1b) | OPEN |
| AR-09 | Docker sandbox lacks disk/pids limits and runs as root | Security | Medium | High | `runtime/runtimes.py` (no --user/--pids-limit) | Add flags (Wave 1) | OPEN |
| AR-10 | Port-allocator ledger is global — test/scale isolation depends on ranged fixtures | Correctness | Low | Low | `tests/conftest.py` port_range lesson | Partition by project (backlog) | OPEN |
| AR-11 | Single fallback hop for model providers; no backoff — transient 429/5xx can fail attempts | Reliability | Medium | Medium | `models_registry.complete` | Backoff + retry budget (W2-GATEWAY-1) | OPEN |
| AR-12 | Browser/MCP/research outputs enter context with only observation compression; injection flags not acted on | Security/AI | Medium | Medium | `observations.py` security_flags unused | Down-rank flagged content (Wave 1) | OPEN |

Registered but accepted (documented deferrals): Tauri shell (ADR-0008), LSP/call-graphs,
external embeddings, browser video capture, HTTP MCP transports.
