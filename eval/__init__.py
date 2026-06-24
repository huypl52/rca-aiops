"""eval/ — Eval & benchmark (FR-10 / AD-13 #6). Eval layer for Story 6.1: 11-scenario scaffold.

Trách nhiệm (Epic 6): 11-scenario benchmark (§3.7 ground-truth), diagnosis correctness (binary
conjunction §3.7 — Story 6.2), calibration (SM-2 — 6.2), partial-credit + tolerance window (lớp đo
BỔ SUNG trên conjunction, KHÔNG thay thế — AD-13 #6 — 6.3), anti-hallucination raw-vs-summary (Q10
— 6.3), playbook retrieval axis (A6 — 6.4), train/eval split (Q8 — 6.4).

**Story 6.1 ships the DATA + INJECT layer ONLY** (the foundation 6.2/6.3/6.4 build on):

  - :mod:`eval.schema`    — plain JSON-safe frozen dataclasses (``Scenario`` / ``RootCauseLabel`` /
    ``ExpectedEvidence`` / ``InjectCall``). AD-9 — NO Pydantic models defined here.
  - :mod:`eval.scenarios` — the 11 §3.7 ``Scenario`` instances + the deterministic canned inject
    (``RawBackendResponse`` wire shapes) + the A8 ``prod_only`` marking + the
    ``non_deterministic_extension`` flag. DERIVED from §3.7 + the brainstorm — never invented.

The inject → ``Evidence`` pipeline (the REAL adapter + the REAL evidence_normalizer, no synthesized
evidence — Epic-4 K2 real-stub discipline) lives in ``tests/eval_harness.py``: ``eval/`` is pure
DATA + the deterministic inject contract (import-restricted to ``ci.contract_schema`` + stdlib).

**Deferred (NOT this story):** 6.2 binary-conjunction eval harness + calibration; 6.3
partial-credit/tolerance window + anti-hallucination raw-vs-summary; 6.4 playbook-retrieval axis +
train/eval split. Gate #6 at 6.1 makes ONLY the **determinism axis** real (same inject → byte-stable
symptom, cross-``PYTHONHASHSEED``); the SCORING axes (conjunction / partial-credit /
anti-hallucination) are honestly deferred to 6.2/6.3 — never a silent green lie.
"""

from __future__ import annotations

from eval.scenarios import (
    BENCHMARK_CANONICAL_TRIGGERS,
    BENCHMARK_SCENARIOS,
)
from eval.schema import (
    ExpectedEvidence,
    InjectCall,
    RootCauseLabel,
    Scenario,
)

__all__ = [
    "BENCHMARK_CANONICAL_TRIGGERS",
    "BENCHMARK_SCENARIOS",
    "ExpectedEvidence",
    "InjectCall",
    "RootCauseLabel",
    "Scenario",
]
