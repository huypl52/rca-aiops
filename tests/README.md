# `tests/` — Tests — CI gate self-tests + smoke

Trách nhiệm: 2-tier CI gate self-tests (AD-13 #1/#2 negative tests) + package smoke tests.

**Gate #1 negative test:** `tests/ci/test_gate1_readonly.py` — inject `def scale()`/`def restart()` → gate exit 1.
**Gate #2 negative test:** `tests/ci/test_gate2_deps.py` — inject adapters→graph back-edge → lint-imports fail.
**Smoke:** `tests/test_packages_import.py` — import mọi package thành công.
