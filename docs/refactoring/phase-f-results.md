# Phase F Results

## 1. Changes Made
Docs-only analysis (13 new docs) + 2 small commits: boundary-enforcement
tests (4 AST guards) and the full 19-smoke battery wiring. One filesystem
cleanup (3 ignored temp logs). No architecture replacement of any kind.

## 2. Files Removed
`tmp-w3-api-err.log`, `tmp-w3-api.log`, `tmp-w3-repro2.log` (root, git-ignored,
unreferenced by code/CI/docs — verified before deletion).

## 3. Files Moved
None. (Deliberate: moves break links/history for zero behavior gain.)

## 4. Files Merged
None. All duplication suspects were proven non-duplicates (toolchains
layering, error taxonomy, event names) — documented, not merged.

## 5. Architectural Boundaries Introduced
Four CI-enforced AST rules: deterministic workflows, framework-free agent
domain, no engine construction in routes, projection-only realtime.

## 6. Architectural Violations Remaining
Services→ORM models (accepted P2, as-touched discipline); codeintel SQL in
domain (accepted Case C); routes single-row `db.get` (as-touched). None P0/P1.

## 7. Dependencies Removed
None — audit found every declared dep mapped to real usage.

## 8. Documentation Consolidation
`docs/architecture/` entry point + 12 ADRs; refactoring tree; wave docs kept
in place (moves would break links); stale-count claims corrected with evidence.

## 9. Test Changes
+4 boundary tests (all green). No tests weakened, deleted, or skipped.

## 10. Baseline vs Current Validation
Baseline: 311 unit / 217 integration / 7 evals / 144 frontend, clean lint/type.
Current: 315 unit (+4 boundary) / 217 / 7 / 144, clean lint/type/format.
Zero regressions. Smokes: battery now covers all 19 (previously 8).

## 11. End-to-End Results
Full integration suite (217) exercises project→requirement→plan→task→agent→
execute→recover→verify→evidence across waves; journey + chaos + realtime
scenarios green. Live browser smokes not re-run this phase (no UI changes).

## 12. Performance Impact
None measurable: docs + 4 unit tests + deleted logs + runner list.

## 13. Remaining Technical Debt
R-03 (services↔models, ongoing), R-04 (routes direct reads, as-touched),
R-05 done (no removals), R-06 decision pending (likely decline),
CenterView.tsx 713 lines (watch-item, not split).

## 14. Remaining Architectural Risks
See `known-risks.md` (6 items, unchanged — none introduced by this phase).

## 15. Recommended Next Refactoring Batch
R-02 is committed and enforcing. Next: R-01 link check + R-04 as-touched
only. No further batches without review (STOPPING CONDITION honored).
