"""chaos — the deterministic §3.7 fault injector (Story 7.3 AC1).

A WRITE outside the agent's read-only perimeter: chaos CREATES the 11 §3.7 faults
(as trigger-source payloads the 7.2 stack detects) — it is benchmark/infra, NOT
agent production code (it is NOT under ``tools``/``adapters`` and is therefore
correctly NOT scanned by gate #1's read-only registry; its isolation from the
agent is enforced HARD-FAIL by the Story 7.3 ``forbidden`` import-linter contract,
parallel to the 7.1 demo + 7.2 observability boundaries).

The deterministic core (:mod:`chaos.inject`) is proven in-process for all 11
scenarios (chaos→symptom→trigger→canonical via ``services.normalize``); the live
cluster driver (:mod:`chaos.driver`) is a reported, correct-by-construction seam
(no local K8s in this dev env).
"""

from __future__ import annotations

from chaos.inject import UnknownScenarioError, inject, inject_all
from chaos.scenarios import BENCHMARK_CANONICAL_TRIGGERS, BENCHMARK_SCENARIOS, ScenarioSpec

__all__ = [
    "BENCHMARK_CANONICAL_TRIGGERS",
    "BENCHMARK_SCENARIOS",
    "ScenarioSpec",
    "UnknownScenarioError",
    "inject",
    "inject_all",
]
