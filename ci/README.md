# `ci/` — CI infrastructure — gate scripts + contracts

Trách nhiệm: CI gate scripts (`gate1_readonly_registry.py` — read-only HARD-FAIL), deny-set canonical source (`denyset.py`), import-linter contract (`[tool.importlinter]` trong pyproject), 6-gate reference (`GATES.md`).

**Dev decision (leader APPROVE gate-1):** `ci/` package thêm ngoài spine 11 pkg — gate scanner + import-linter contract cần chỗ, KHÔNG thuộc `tests/` vì là CI infra (không phải test thuần).

**NOT application runtime code** — KHÔNG import trong routers/services/graph/adapters/tools.
