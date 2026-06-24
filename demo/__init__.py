"""demo — the SYSTEM-UNDER-INVESTIGATION (5 FastAPI microservices), NOT the RCA agent.

Story 7.1 (Epic 7 — Infra & Deploy). This package is a **standalone deployable**:
the demo victim system the RCA agent (Epics 0-6, ``graph``/``services``/``routers``/
``adapters``/``tools``) *investigates* at runtime via read-only adapters. It imports
**NO agent code** — enforced by the import-linter ``forbidden`` contract in
``pyproject.toml`` (gate #2) and proven by ``tests/ci/test_gate2_demo_boundary.py``.

The read-only-investigator deny-set (gate #1: NO write/exec/patch/delete/scale/
rollback/restart/remediate) does **NOT** apply here — these are ordinary demo
services that may read/write their own state and call each other. That constraint
applies ONLY to the RCA agent, which this story leaves UNCHANGED (spine-13 frozen).

Determinism (AD-12 family extended to the demo system): the "normal traffic"
generator (:mod:`demo.model`) is a SEED-REPRODUCIBLE pure function — the same
healthy baseline is reproducible run-to-run so Story 7.3's chaos inject produces
reproducible symptoms.
"""
