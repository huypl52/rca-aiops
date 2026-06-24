"""Story 7.3 — chaos injects the 11 §3.7 faults; each normalizes to its canonical.

The AC1 proof surface, IN-PROCESS (no cluster needed — this dev env has none):
``chaos.inject(scenario)`` returns the exact trigger-source payload the 7.2 stack
would carry, and ``services.normalize`` turns it into a valid ``IncidentTrigger``
with the correct §3.7 ``canonical_trigger`` — for ALL 11 scenarios. This is the
chaos→symptom→trigger→canonical mapping, proven deterministically. The live
cluster chain (``chaos.driver``) is a reported seam, not exercised here.

The two non-deterministic scenarios (``memory_leak`` / ``latency_spike``) are
still injected (their payload resolves to the correct canonical) — they are
MARKED ``non_deterministic`` because their REAL metric shape is non-reproducible
run-to-run; the tolerance window is Story 6.3, not deterministic construction.
"""

from __future__ import annotations

import pytest

from chaos import BENCHMARK_SCENARIOS, UnknownScenarioError, inject, inject_all
from chaos.driver import live_fault_action
from chaos.scenarios import ScenarioSpec
from models import IncidentTrigger, SignalType, TriggerSource
from services.normalize import (
    BENCHMARK_CANONICAL_TRIGGERS,
    normalize_grafana,
    normalize_kubernetes,
    normalize_prometheus,
)

# scenario.trigger_source (Literal str) -> the matching 1.1 normalizer.
_NORMALIZER = {
    "prometheus_alertmanager": normalize_prometheus,
    "grafana_alerting_loki": normalize_grafana,
    "kubernetes_event": normalize_kubernetes,
}

# scenario.trigger_source -> TriggerSource enum the normalizer stamps.
_TRIGGER_SOURCE_ENUM = {
    "prometheus_alertmanager": TriggerSource.PROMETHEUS_ALERTMANAGER,
    "grafana_alerting_loki": TriggerSource.GRAFANA_ALERTING_LOKI,
    "kubernetes_event": TriggerSource.KUBERNETES_EVENT,
}

# scenario.signal_type -> SignalType enum the normalizer stamps.
_SIGNAL_TYPE_ENUM = {
    "metric": SignalType.METRIC,
    "log": SignalType.LOG,
    "kubernetes_event": SignalType.KUBERNETES_EVENT,
}


def _normalize(scenario: ScenarioSpec) -> IncidentTrigger:
    return _NORMALIZER[scenario.trigger_source](inject(scenario.name))


@pytest.mark.parametrize("scenario", BENCHMARK_SCENARIOS, ids=lambda s: s.name)
def test_chaos_payload_normalizes_to_correct_canonical(scenario: ScenarioSpec) -> None:
    """The headline AC1 invariant: chaos(scenario) -> trigger -> correct §3.7 canonical."""
    trigger = _normalize(scenario)
    assert isinstance(trigger, IncidentTrigger)
    assert trigger.canonical_trigger == scenario.canonical_trigger
    assert trigger.source == _TRIGGER_SOURCE_ENUM[scenario.trigger_source]
    assert trigger.signal_type == _SIGNAL_TYPE_ENUM[scenario.signal_type]
    assert trigger.service == scenario.service
    assert trigger.namespace == "demo"


@pytest.mark.parametrize("scenario", BENCHMARK_SCENARIOS, ids=lambda s: s.name)
def test_chaos_payload_is_deterministic(scenario: ScenarioSpec) -> None:
    """inject is pure + AD-12-deterministic: same scenario -> byte-identical payload (twice)."""
    first = inject(scenario.name)
    second = inject(scenario.name)
    assert first == second
    # the scenario tag (robust canonical path) is always present + equals the §3.7 key.
    labels = first["labels"]
    assert isinstance(labels, dict)
    assert labels["scenario"] == scenario.name


def test_inject_all_covers_eleven_scenarios_each_resolving_to_its_canonical() -> None:
    """inject_all() yields 11 payloads, each normalizing to its scenario canonical, unique ids."""
    payloads = inject_all()
    assert len(payloads) == 11
    fingerprints: set[str] = set()
    for scenario, payload in zip(BENCHMARK_SCENARIOS, payloads, strict=True):
        trigger = _NORMALIZER[scenario.trigger_source](payload)
        assert trigger.canonical_trigger == scenario.canonical_trigger
        # trigger_id is fingerprint (alerts) or metadata.uid (events) — both chaos-prefixed.
        fingerprints.add(trigger.trigger_id)
    assert len(fingerprints) == 11  # 11 distinct deterministic trigger_ids


def test_chaos_canonical_vocabulary_matches_the_agent_canonical_vocabulary() -> None:
    """chaos's §3.7 derivation == services.normalize's frozen 11 (no 12th, no rename)."""
    chaos_canonicals = frozenset(s.canonical_trigger for s in BENCHMARK_SCENARIOS)
    assert chaos_canonicals == BENCHMARK_CANONICAL_TRIGGERS


def test_exactly_two_scenarios_are_marked_non_deterministic() -> None:
    """memory_leak + latency_spike are the two NON-DET scenarios (tolerance -> Story 6.3)."""
    non_det = {s.name for s in BENCHMARK_SCENARIOS if s.non_deterministic}
    assert non_det == {"memory_leak", "latency_spike"}


def test_disk_and_memory_are_prod_only() -> None:
    """disk_pressure + memory_leak are trustworthy only multi-node (A8)."""
    prod_only = {s.name for s in BENCHMARK_SCENARIOS if s.prod_only}
    assert prod_only == {"disk_pressure", "memory_leak"}


def test_inject_rejects_an_unknown_scenario() -> None:
    """inject surfaces (never silently drops) a scenario key outside the §3.7 eleven."""
    with pytest.raises(UnknownScenarioError):
        inject("not-a-real-scenario")


@pytest.mark.parametrize("scenario", BENCHMARK_SCENARIOS, ids=lambda s: s.name)
def test_live_fault_action_is_stable_and_non_empty(scenario: ScenarioSpec) -> None:
    """chaos.driver documents a deterministic live fault + detection chain per scenario."""
    action = live_fault_action(scenario.name)
    assert isinstance(action, str)
    assert action.strip()
    assert live_fault_action(scenario.name) == action  # stable (pure lookup)


def test_live_fault_action_rejects_an_unknown_scenario() -> None:
    with pytest.raises(KeyError):
        live_fault_action("not-a-real-scenario")
