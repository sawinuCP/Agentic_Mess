# Known Limitations (Wave 12 living document)

Honest boundaries — each item states what is missing, why, and what would
change the decision. Nothing here is disguised as a feature.

1. **No autonomous planner loop.** Cases execute scripted repairs and repo
   tests. Planning quality, context sufficiency and tool choice under autonomy
   are unmeasured. Would need: model-backed planner + autonomy evaluation
   dimension (§5 L4 remains aspirational).
2. **No evaluator model.** Deterministic gates only, by design (§10).
3. **No per-agent pause/resume/stop.** Agents are disposable per attempt;
   workflows own control. Session release exists for stuck sessions.
4. **No message composing as agents.** Operator compose exists with explicit
   null-sender attribution; faking agent provenance is refused permanently.
5. **Light theme is basic.** Variable layer + Monaco/xterm themes ship and work;
   third-party widget theming and contrast fine-tuning beyond the token layer
   are best-effort only.
6. **No virtualization.** Lists bounded at data layer (100/page, 120 events,
   500/page history). Would need: measured render bottleneck (none found).
7. **Single-range artifact serving.** Multi-range requests get 416.
8. **Test NATS consumers accumulate** (`realtime-gateway-test-*`); hermetic
   tests clean their own, older strays need occasional manual `consumer rm`.
9. **Disk quota absent** in docker runtime (memory/PID/network capped).
10. **100k-event / hour-soak / 25–50-agent tiers** unproven (see
    performance-envelope.md for the demonstrated envelope).
11. **No automated backups in-repo** (procedure in disaster-recovery.md).
12. **Alerts are operator-owned** (metrics/logs exist; no alerting stack).
