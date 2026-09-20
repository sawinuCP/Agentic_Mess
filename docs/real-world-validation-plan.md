# Real-World Validation Plan (Wave 12)

Fixture repositories live in code (`services/api/tests/fixtures/e2e_projects.py`,
generated into tmp dirs — never committed blobs). All local-only.

| Project | Shape | Validates |
|---|---|---|
| A small Python | calc + pytest + ruff config | Index, retrieval, lint-path execution |
| B TypeScript/React | component + test + tsconfig | TSX indexing, symbol search |
| C FastAPI backend | endpoints + TestClient tests | Endpoint tests without a server |
| D multi-module | frontend + backend + compose | Parallel work, dependency reasoning |
| E messy legacy | duplication, TODOs, green tests | Comprehension without rewriting (read-only proof) |
| F large generated | 2000 modules / ~2000+ symbols | Index scale, incremental noop, retrieval latency |

Task levels L1–L4 map to: scripted command execution (rehearsal), multi-file
edits via worktrees, failure injection + recovery, and overseer-gated
verification. Ambiguity is validated negatively: vague requirements without
evidence must stay UNKNOWN (test-enforced), never auto-VERIFIED.
