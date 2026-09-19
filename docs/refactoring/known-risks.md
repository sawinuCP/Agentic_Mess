# Known Risks (Phase E)

1. **Uncommitted Wave-12 work in tree** (18 paths): analysis added no
   implementation changes, but any Phase F+ branch must account for it —
   commit or stash Wave-12 first. No refactoring branch created yet, deliberately.
2. **R-03 scope creep**: the services↔models pattern tempts a big-bang
   repository layer. Mitigation: rule as written (as-touched only).
3. **Temporal determinism**: any workflow edit risks replay breakage.
   Mitigation: R-02 guard test + workflow test suite per change.
4. **Event-type rename (R-06)**: backfill risk on historical queries.
   Default DECLINE unless review decides otherwise.
5. **Frontend view moves**: sidebar graph (views ↔ panels) could break
   keyboard/smoke selectors. Mitigation: role-based selectors already in
   smokes; run all three smokes per frontend batch.
6. **Docs drift**: 38 files rot fast. Mitigation: hierarchy entry point +
   dated wave docs; link check in R-01.
