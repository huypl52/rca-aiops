"""Story 6.1 — 11-scenario benchmark scaffold + ground-truth + inject contract.

Covers the Story-6.1 DEEP spotlights (the foundation all of 6.2/6.3/6.4 builds on):

  - AC1 derivation — the 11 scenarios are DERIVED from spec §3.7 (NOT invented): the scenario set
    + ``trigger_source`` + ``canonical_trigger`` + ``supporting_evidence`` match the §3.7 table, and
    ``{canonical_trigger}`` == ``services.normalize.BENCHMARK_CANONICAL_TRIGGERS`` (the existing
    frozen 11) — no 12th scenario, no renamed canonical.
  - AC1 contract conformance (gate#5 axes) — each scenario's fields build a VALID 18-field
    ``IncidentTrigger`` (source/signal_type/severity ∈ spec domains) + each expected-evidence source
    builds a VALID 9-field ``Evidence`` (tiered: 5 required / 2 optional-nullable / 2 derived).
  - AC1 routability + determinism — driving each scenario's inject through the REAL adapter + the
    REAL evidence_normalizer (no synthesized evidence — Epic-4 K2) produces routable ``Evidence``
    whose ``source_type`` set COVERS the scenario's expected-evidence sources (conjunction condition
    *a*). Every emitted evidence carries a non-null ``raw_excerpt`` (AD-6). Within-process:
    same inject → byte-identical symptom (determinism prerequisite).
  - AC2 A8 marking — ``prod_only`` marks disk_pressure + memory_leak ONLY (brainstorm:53,:74 — disk
    + memory trustworthy ONLY multi-node); the catalog keeps ALL 11 (does NOT remove, does NOT trust
    the prod-only two in the POC single-node scope).
  - orthogonality — ``prod_only`` ⊥ ``non_deterministic_extension``: memory_leak carries BOTH;
    disk_pressure carries ``prod_only`` only; latency_spike carries ``non_deterministic_extension``
    only.

The cross-``PYTHONHASHSEED`` determinism gate (the decisive one) lives in
``tests/ci/test_gate6_benchmark_determinism.py`` (gate #6). This test does the in-process
determinism prerequisite + the contract + the marking.
"""

from __future__ import annotations

import pytest

from ci.contract_schema import (
    SPEC_EVIDENCE_FIELDS,
    SPEC_INCIDENT_TRIGGER_FIELDS,
    TRIGGER_SEVERITIES,
    TRIGGER_SIGNAL_TYPES,
    TRIGGER_SOURCES,
)
from eval import BENCHMARK_CANONICAL_TRIGGERS, BENCHMARK_SCENARIOS
from eval.schema import Scenario
from models import Evidence, IncidentTrigger, Severity, SignalType, TriggerSource
from services.normalize import BENCHMARK_CANONICAL_TRIGGERS as SERVICES_CANONICAL_TRIGGERS
from tests.eval_harness import drive_evidence, scenario_symptom

# The 11 §3.7 scenario ids, in table order (DERIVED — the assertion the scaffold matches §3.7).
_SPEC_3_7_SCENARIO_NAMES: tuple[str, ...] = (
    "dependency_timeout",
    "payment_failure",
    "latency_spike",
    "disk_pressure",
    "memory_leak",
    "inventory_reserve_failure",
    "dns_failure",
    "certificate_expired",
    "crashloop",
    "oom",
    "bad_deployment_config",
)

# The 8 read-only adapter methods the inject may drive (ReadOnlyAdapterPort, Story 2.1).
_ADAPTER_METHODS: frozenset[str] = frozenset(
    {
        "query_promql",
        "query_loki",
        "k8s_get",
        "k8s_describe",
        "k8s_logs",
        "k8s_get_events",
        "search_playbook",
        "topology_read",
    }
)

# Repeated-read count for the within-process determinism prerequisite (AC1).
_REPEAT: int = 3


# ---------------------------------------------------------------------------
# AC1 — the 11 scenarios are DERIVED from §3.7 (set + names + canonical vocabulary).
# ---------------------------------------------------------------------------


def test_benchmark_has_exactly_eleven_scenarios() -> None:
    """§3.7 defines exactly 11 scenarios — the scaffold is 11, no more, no less."""
    assert len(BENCHMARK_SCENARIOS) == 11


def test_benchmark_scenario_names_match_spec_3_7_table_order() -> None:
    """The 11 scenario ids match §3.7 in table order (DERIVED, not invented/renamed)."""
    assert tuple(s.name for s in BENCHMARK_SCENARIOS) == _SPEC_3_7_SCENARIO_NAMES


def test_benchmark_canonical_triggers_match_frozen_vocabulary() -> None:
    """The 11 canonical_triggers == the existing frozen source-of-truth (no 12th, no rename).

    Cross-checks eval's derived frozenset against ``services.normalize.BENCHMARK_CANONICAL_TRIGGERS``
    (the ingest-side source-of-truth the gate#5 / ingest tests already pin). Single frozen 11.
    """
    assert len(BENCHMARK_CANONICAL_TRIGGERS) == 11
    assert BENCHMARK_CANONICAL_TRIGGERS == SERVICES_CANONICAL_TRIGGERS
    # No 12th / no rename — a 12th invented term would break this equality.
    assert BENCHMARK_CANONICAL_TRIGGERS == frozenset(
        {
            "DependencyTimeout",
            "PaymentFailureHigh",
            "DownstreamLatencyHigh",
            "NodeDiskPressure",
            "MemoryUsageHigh",
            "InventoryReserveFailureHigh",
            "DNSFailureLogSpike",
            "CertificateErrorDetected",
            "CrashLoopBackOff",
            "OOMKilled",
            "DeploymentUnavailable",
        }
    )


@pytest.mark.parametrize("scenario", BENCHMARK_SCENARIOS, ids=lambda s: s.name)
def test_scenario_has_required_derived_fields(scenario: Scenario) -> None:
    """Every scenario carries the §3.7-mandated fields (DERIVED from §3.7 + brainstorm + fixtures)."""
    assert scenario.trigger_source in TRIGGER_SOURCES, "trigger_source must be a §3.4 domain"
    assert scenario.signal_type in TRIGGER_SIGNAL_TYPES, "signal_type must be a §3.4 domain"
    assert scenario.severity in TRIGGER_SEVERITIES, "severity must be a §3.4 domain"
    assert scenario.service, "service (POC demo vocabulary) must be non-empty"
    assert scenario.namespace == "demo", "namespace is the POC demo tenant"
    assert scenario.supporting_evidence, "§3.7 supporting-evidence text must be present"
    assert scenario.root_cause.faulty_service, "ground-truth faulty_service must be non-empty"
    assert scenario.root_cause.hypothesis, "ground-truth hypothesis must be non-empty"
    assert scenario.expected_evidence, "each scenario must declare routable expected evidence"
    assert scenario.inject, "each scenario must carry a deterministic inject contract"


@pytest.mark.parametrize("scenario", BENCHMARK_SCENARIOS, ids=lambda s: s.name)
def test_scenario_inject_uses_only_read_only_adapter_methods(scenario: Scenario) -> None:
    """The inject drives ONLY the 8 read-only adapter methods (§3.8 read-only boundary — gate#1 axis)."""
    for call in scenario.inject:
        assert call.adapter_method in _ADAPTER_METHODS, (
            f"inject method {call.adapter_method!r} is not a read-only adapter method"
        )


# ---------------------------------------------------------------------------
# AC1 — contract conformance (gate#5 axes): 18-field IncidentTrigger + 9-field Evidence.
# ---------------------------------------------------------------------------


def _build_trigger(scenario: Scenario) -> IncidentTrigger:
    """Build a VALID 18-field IncidentTrigger from a scenario's derived fields (gate#5 conformance)."""
    return IncidentTrigger(
        trigger_id=f"tr-bench-{scenario.name}",
        source=TriggerSource(scenario.trigger_source),
        signal_type=SignalType(scenario.signal_type),
        canonical_trigger=scenario.canonical_trigger,
        alert_name=scenario.canonical_trigger,
        severity=Severity(scenario.severity),
        title=f"{scenario.canonical_trigger} on {scenario.service}",
        description=scenario.supporting_evidence,
        service=scenario.service,
        affected_services=[scenario.service],
        symptom=scenario.canonical_trigger,
        namespace=scenario.namespace,
        started_at="2026-06-24T10:00:00Z",
        ends_at=None,
        labels={
            "service": scenario.service,
            "namespace": scenario.namespace,
            "scenario": scenario.name,
        },
        annotations={
            "summary": scenario.canonical_trigger,
            "description": scenario.supporting_evidence,
        },
        raw_payload={"scenario": scenario.name},
        raw_payload_ref=None,
    )


@pytest.mark.parametrize("scenario", BENCHMARK_SCENARIOS, ids=lambda s: s.name)
def test_scenario_builds_valid_eighteen_field_incident_trigger(scenario: Scenario) -> None:
    """Each scenario's fields build a VALID IncidentTrigger (18 §3.4 fields; enums in spec domains)."""
    trigger = _build_trigger(scenario)
    dumped = trigger.model_dump()
    # exactly the 18 §3.4 fields (+ incident_id None default) — no drift, no invented field.
    spec_fields = set(SPEC_INCIDENT_TRIGGER_FIELDS)
    assert spec_fields <= set(dumped.keys()), "a §3.4 field is missing from the built trigger"
    assert trigger.canonical_trigger == scenario.canonical_trigger
    assert trigger.source.value == scenario.trigger_source
    assert trigger.signal_type.value == scenario.signal_type
    assert trigger.severity.value == scenario.severity
    assert trigger.raw_payload_ref is None  # §3.4 row 18 — None POC


@pytest.mark.parametrize("scenario", BENCHMARK_SCENARIOS, ids=lambda s: s.name)
def test_scenario_expected_evidence_conforms_to_nine_field_contract(scenario: Scenario) -> None:
    """Each expected-evidence source's type is a real Evidence source_type; the 9-field contract holds."""
    for expected in scenario.expected_evidence:
        assert expected.source_type in {
            "prometheus",
            "loki",
            "kubernetes",
            "playbook",
            "topology",
        }, f"expected source_type {expected.source_type!r} is not a real evidence source"
        assert expected.adapter_method in _ADAPTER_METHODS
    # The Evidence model itself is exactly 9 §3.6 fields (gate#5 invariant, re-asserted here).
    assert set(Evidence.model_fields.keys()) == set(SPEC_EVIDENCE_FIELDS)
    assert len(SPEC_EVIDENCE_FIELDS) == 9


# ---------------------------------------------------------------------------
# AC1 — routability + within-process determinism (real adapter + real normalizer).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("scenario", BENCHMARK_SCENARIOS, ids=lambda s: s.name)
def test_inject_produces_routable_evidence_covering_expected_sources(scenario: Scenario) -> None:
    """AC1 conjunction-condition-a: the inject → Evidence covers the expected source_types (routable).

    Drives the scenario's canned inject through the REAL adapter + the REAL evidence_normalizer
    (no synthesized evidence — Epic-4 K2). The produced Evidence ``source_type`` set must COVER the
    scenario's declared expected-evidence source_types. Every emitted evidence carries a non-null
    ``raw_excerpt`` (AD-6 no-RC-without-evidence).
    """
    evidence = drive_evidence(scenario)
    assert evidence, f"scenario {scenario.name!r} inject produced NO routable evidence"
    # Membership-filter (not set-subtraction): ``produced_types`` is set[object] (dict[str,object].get
    # → object), so ``set[str] - set[object]`` would trip strict-mypy's invariant ``__sub__``; the
    # ``in`` check is type-safe (set.__contains__ accepts object) and reads identically.
    produced_types = {e.get("source_type") for e in evidence}
    missing = [
        exp.source_type
        for exp in scenario.expected_evidence
        if exp.source_type not in produced_types
    ]
    assert not missing, (
        f"scenario {scenario.name!r}: inject did not routably produce expected sources {missing}"
    )
    # AD-6: every emitted evidence carries a non-null raw_excerpt (no claim-grade evidence without one).
    for ev in evidence:
        assert ev.get("raw_excerpt"), "an emitted evidence lacks a non-null raw_excerpt (AD-6)"
    # Every emitted evidence IS a valid 9-field Evidence (validates at the port — the normalizer did).
    for ev in evidence:
        Evidence.model_validate(ev)


@pytest.mark.parametrize("scenario", BENCHMARK_SCENARIOS, ids=lambda s: s.name)
def test_inject_symptom_is_within_process_deterministic(scenario: Scenario) -> None:
    """Determinism prerequisite: same inject → byte-identical symptom across repeated in-process runs.

    The decisive cross-``PYTHONHASHSEED`` proof is gate#6 (``tests/ci/test_gate6_*``); this asserts the
    in-process prerequisite (the symptom is a pure function of the inject — AD-12).
    """
    symptoms = [scenario_symptom(scenario) for _ in range(_REPEAT)]
    assert len(set(symptoms)) == 1, (
        f"scenario {scenario.name!r} inject is non-deterministic in-process (AD-12 violation)"
    )


# ---------------------------------------------------------------------------
# AC2 — A8 multi-node marking (prod_only). DERIVED from brainstorm:53,:74.
# ---------------------------------------------------------------------------


def test_a8_marks_disk_and_memory_prod_only_only() -> None:
    """A8: ONLY disk_pressure + memory_leak are prod_only (trustworthy ONLY multi-node — brainstorm)."""
    prod_only_names = {s.name for s in BENCHMARK_SCENARIOS if s.prod_only}
    assert prod_only_names == {"disk_pressure", "memory_leak"}, (
        "A8 prod_only marking must be disk_pressure + memory_leak ONLY"
    )


def test_a8_catalog_keeps_all_eleven_scenarios() -> None:
    """A8: prod_only MARKS, it does NOT remove — the catalog keeps all 11 (POC single-node scope).

    The two prod-only scenarios stay in the benchmark; they are flagged so the POC does NOT TRUST
    them as single-node-deterministic (their real multi-node failure mode is out of POC scope).
    """
    assert len(BENCHMARK_SCENARIOS) == 11  # none removed
    prod_only = [s for s in BENCHMARK_SCENARIOS if s.prod_only]
    assert len(prod_only) == 2
    # they are still full scenarios (carrying inject + expected evidence) — just marked.
    for s in prod_only:
        assert s.inject and s.expected_evidence


def test_a8_marking_is_orthogonal_to_non_deterministic_extension() -> None:
    """``prod_only`` ⊥ ``non_deterministic_extension`` (the two axes are independent).

    - memory_leak (MemoryUsageHigh): BOTH prod_only AND non_deterministic_extension.
    - disk_pressure (NodeDiskPressure): prod_only ONLY (disk is deterministically detectable).
    - latency_spike (DownstreamLatencyHigh): non_deterministic_extension ONLY (not multi-node).
    - the other 8: neither flag.
    """
    by_name = {s.name: s for s in BENCHMARK_SCENARIOS}
    memory = by_name["memory_leak"]
    disk = by_name["disk_pressure"]
    latency = by_name["latency_spike"]
    assert memory.prod_only and memory.non_deterministic_extension == "memory_leak"
    assert disk.prod_only and disk.non_deterministic_extension is None
    assert (not latency.prod_only) and latency.non_deterministic_extension == "latency_spike"
    # the two non_deterministic_extension scenarios are exactly memory_leak + latency_spike (brainstorm M3).
    nd = {s.name for s in BENCHMARK_SCENARIOS if s.non_deterministic_extension is not None}
    assert nd == {"memory_leak", "latency_spike"}
