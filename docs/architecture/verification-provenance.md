# Verification Provenance — Design Note (Backend Trust Hardening)

## 1. What is being verified?

An acceptance criterion (a machine-checkable condition on a requirement),
via `overseer.verify_criterion`, which writes one `Validation`
(kind=requirement, status=passed) + flips the criterion. Requirement status
stays DERIVED (no status column — §13 upheld).

## 2/3. Against what state, and how is it identified?

The codebase's authoritative source-state representation is the git HEAD sha
(`GitClient.head_sha`, already used as rollback anchors by
`snapshot_attempt_activity`). Provenance = `{source_head_sha, source_branch,
source_dirty}` captured at verify time. Non-git projects record all three
as null (explicit, not absent-by-accident).

## 4. Where is it stored?

`validations.detail` JSONB (existing metadata pattern: already holds
`artifact_name`), plus `validations.created_at` as `verified_at`. No
migration: no new columns, no new tables, fully backward compatible.
Traceability criterion entries surface the latest validation's
`{validation_id, verified_at, evidence_artifact_id, provenance}` so reads
stay single-query.

## 5/6. What happens when source changes (relevant or not)?

Nothing automatic. The architecture has NO dependency mapping from criteria
to files, so relevance cannot be determined safely. Conservative semantic
(§10): verification REMAINS HISTORICAL; status math UNCHANGED (still
VERIFIED); consumers compare recorded `source_head_sha` against current
HEAD themselves — match means "verified against current HEAD", mismatch
means "verified against an older state", null means "unverifiable binding".
The UI must render those three readings, never FAILED/INVALID.

## 7/8. Relations

Verification → task/attempt: via `validation.task_id` (already stored) and
criterion → requirement FK. Verification → evidence: `evidence_artifact_id`
(already stored) + artifact sha joinable. One `CRITERION_VERIFIED` durable
event per performed verification (transition, not read): criterion +
validation + evidence + task + provenance in payload.

## 9. How the future UI knows current/stale/unknown

Per-criterion provenance in traceability entries: `verified_at`,
`source_head_sha`, `source_branch`, `source_dirty`. UI rule: sha match →
"verified against current code"; mismatch → "verified against {sha[:8]} —
code has since changed"; null → "no source binding recorded".

## 10. Explicitly NOT guaranteed

No automatic invalidation, no per-file relevance, no verification history
beyond latest-per-criterion, no timestamps on the criterion row itself
(`created_at` on validations is the clock), no FAILED-criterion production
(no writer exists — Temporal validation activities don't link criteria).
