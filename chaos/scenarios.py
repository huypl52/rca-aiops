"""chaos/scenarios — the 11 §3.7 fault-injection specs (Story 7.3 AC1).

EVERY value here is **DERIVED, never invented**:

  - the 11 scenario keys (``name``) come verbatim from spec §3.7 left-most column
    (``docs/PROJECT_SPECS.md`` §3.7 table) AND are the exact keys
    ``services.normalize._SCENARIO_TO_CANONICAL`` maps — so the chaos-injected
    ``labels.scenario`` tag resolves to the correct §3.7 canonical (the robust
    canonical-resolution path);
  - ``canonical_trigger`` / ``trigger_source`` / ``signal_type`` / ``severity``
    come verbatim from §3.7 (and equal ``eval.scenarios`` + the §3.4 source
    domain) — chaos re-derives them independently (it does NOT import ``eval``;
    the two layers share the §3.7 source, not code);
  - ``prod_only`` / ``non_deterministic`` mirror ``eval.scenarios.py``:
    ``disk_pressure`` + ``memory_leak`` are prod-only (trustworthy only
    multi-node — A8); ``memory_leak`` + ``latency_spike`` carry a
    non-deterministic REAL metric shape (M3) → their tolerance window is
    Story 6.3, NOT deterministic construction here.

This module is the SPEC for the chaos injector — it names WHAT chaos creates per
scenario (the fault + the §3.7 canonical it must drive) without being the
injector (:mod:`chaos.inject`) or the live driver (:mod:`chaos.driver`).

Import-pure: stdlib ONLY. ``chaos`` is a WRITE outside the agent's read-only
perimeter (a benchmark/infra layer, like ``demo``/``observability``) — it imports
NO agent module (``routers``/``services``/``graph``/``adapters``/``tools``/
``models``/``eval``/``ci``/``config``), enforced HARD-FAIL by the Story 7.3
``forbidden`` import-linter contract (``tests/ci/test_gate2_chaos_boundary.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

#: The 3 §3.4 trigger sources that carry a chaos symptom to ingest.
TriggerSource = Literal["prometheus_alertmanager", "grafana_alerting_loki", "kubernetes_event"]

#: The §3.4 signal types.
SignalType = Literal["metric", "log", "kubernetes_event"]

#: The §3.4 severity domain.
Severity = Literal["critical", "warning", "info"]


@dataclass(frozen=True)
class ScenarioSpec:
    """One §3.7 fault-injection spec — what chaos creates + which §3.7 canonical it drives.

    ``name`` is the §3.7 snake_case key carried as ``labels.scenario`` on the
    injected trigger payload — the robust canonical-resolution path
    (``services.normalize._resolve_canonical`` checks ``labels.scenario`` FIRST,
    before the alert/event identifier, and anti-collapse-rejects a disagreement).

    ``alert_name`` is the prometheus/grafana alertname OR the kubernetes event
    ``reason`` — both map 1-1 to ``canonical_trigger`` via
    ``services.normalize._ALERT_TO_CANONICAL`` (e.g. ``BackOff``→CrashLoopBackOff,
    ``DeploymentReplicasNotUpdated``→DeploymentUnavailable), so the payload
    resolves even if a consumer strips the scenario tag.

    ``service`` is the demo-SUT service chaos drives (illustrative — canonical
    resolves via ``name``, not via ``service``; the value is the demo topology
    short name, with ``demo-node-1`` for the node-scoped disk-pressure fault).

    ``fingerprint_suffix`` is a deterministic trigger_id fragment (AD-12: no
    hash()/uuid/clock — a literal stable string per scenario).
    """

    name: str
    canonical_trigger: str
    trigger_source: TriggerSource
    signal_type: SignalType
    severity: Severity
    service: str
    alert_name: str
    summary: str
    description: str
    prod_only: bool
    non_deterministic: bool
    fingerprint_suffix: str

    @property
    def is_kubernetes(self) -> bool:
        """True when the symptom is a kubernetes Event (not a prometheus/grafana alert)."""
        return self.trigger_source == "kubernetes_event"


# ---------------------------------------------------------------------------
# The 11 §3.7 scenarios, in §3.7 table order. DERIVED (see module docstring).
# ---------------------------------------------------------------------------

DEPENDENCY_TIMEOUT = ScenarioSpec(
    name="dependency_timeout",
    canonical_trigger="DependencyTimeout",
    trigger_source="prometheus_alertmanager",
    signal_type="metric",
    severity="critical",
    service="order",
    alert_name="DependencyTimeout",
    summary="upstream dependency timing out",
    description="order -> payment upstream errors (demo_upstream_errors_total > 0)",
    prod_only=False,
    non_deterministic=False,
    fingerprint_suffix="dependency_timeout",
)

PAYMENT_FAILURE = ScenarioSpec(
    name="payment_failure",
    canonical_trigger="PaymentFailureHigh",
    trigger_source="prometheus_alertmanager",
    signal_type="metric",
    severity="critical",
    service="payment",
    alert_name="PaymentFailureHigh",
    summary="payment charge failures elevated",
    description="payment provider returning errors (demo_upstream_errors_total > 0 on payment)",
    prod_only=False,
    non_deterministic=False,
    fingerprint_suffix="payment_failure",
)

LATENCY_SPIKE = ScenarioSpec(
    name="latency_spike",
    canonical_trigger="DownstreamLatencyHigh",
    trigger_source="prometheus_alertmanager",
    signal_type="metric",
    severity="warning",
    service="order",
    alert_name="DownstreamLatencyHigh",
    summary="downstream latency elevated",
    description="request-volume / p95 latency anomaly (demo_requests_total spike)",
    prod_only=False,
    non_deterministic=True,  # M3: REAL p95/p99 metric is non-deterministic → 6.3 tolerance
    fingerprint_suffix="latency_spike",
)

DISK_PRESSURE = ScenarioSpec(
    name="disk_pressure",
    canonical_trigger="NodeDiskPressure",
    trigger_source="prometheus_alertmanager",
    signal_type="metric",
    severity="critical",
    service="demo-node-1",  # node-scoped (DiskPressure is a node condition)
    alert_name="NodeDiskPressure",
    summary="node disk pressure",
    description="node filesystem near full, DiskPressure condition raised (node_filesystem_avail_bytes low)",
    prod_only=True,  # A8: disk trustworthy only multi-node
    non_deterministic=False,
    fingerprint_suffix="disk_pressure",
)

MEMORY_LEAK = ScenarioSpec(
    name="memory_leak",
    canonical_trigger="MemoryUsageHigh",
    trigger_source="prometheus_alertmanager",
    signal_type="metric",
    severity="critical",
    service="order",
    alert_name="MemoryUsageHigh",
    summary="memory usage high",
    description="container memory growing toward limit (container_memory_working_set_bytes high)",
    prod_only=True,  # A8: memory trustworthy only multi-node
    non_deterministic=True,  # M3: REAL memory-trend metric is non-deterministic → 6.3 tolerance
    fingerprint_suffix="memory_leak",
)

INVENTORY_RESERVE_FAILURE = ScenarioSpec(
    name="inventory_reserve_failure",
    canonical_trigger="InventoryReserveFailureHigh",
    trigger_source="prometheus_alertmanager",
    signal_type="metric",
    severity="critical",
    service="inventory",
    alert_name="InventoryReserveFailureHigh",
    summary="inventory reserve failures elevated",
    description="inventory reserve failing (demo_upstream_errors_total > 0 on inventory)",
    prod_only=False,
    non_deterministic=False,
    fingerprint_suffix="inventory_reserve_failure",
)

DNS_FAILURE = ScenarioSpec(
    name="dns_failure",
    canonical_trigger="DNSFailureLogSpike",
    trigger_source="grafana_alerting_loki",
    signal_type="log",
    severity="warning",
    service="user",
    alert_name="DNSFailureLogSpike",
    summary="DNS failure log spike",
    description="dns+failure log pattern elevated (CoreDNS NXDOMAIN errors)",
    prod_only=False,
    non_deterministic=False,
    fingerprint_suffix="dns_failure",
)

CERTIFICATE_EXPIRED = ScenarioSpec(
    name="certificate_expired",
    canonical_trigger="CertificateErrorDetected",
    trigger_source="grafana_alerting_loki",
    signal_type="log",
    severity="warning",
    service="order",
    alert_name="CertificateErrorDetected",
    summary="certificate error detected",
    description="certificate+expired log pattern (x509 validation failure on outbound TLS)",
    prod_only=False,
    non_deterministic=False,
    fingerprint_suffix="certificate_expired",
)

CRASHLOOP = ScenarioSpec(
    name="crashloop",
    canonical_trigger="CrashLoopBackOff",
    trigger_source="kubernetes_event",
    signal_type="kubernetes_event",
    severity="critical",
    service="payment",
    alert_name="BackOff",  # k8s event reason → normalize maps BackOff→CrashLoopBackOff
    summary="CrashLoopBackOff",
    description="back-off restarting failed container payment (CrashLoopBackOff)",
    prod_only=False,
    non_deterministic=False,
    fingerprint_suffix="crashloop",
)

OOM = ScenarioSpec(
    name="oom",
    canonical_trigger="OOMKilled",
    trigger_source="kubernetes_event",
    signal_type="kubernetes_event",
    severity="critical",
    service="order",
    alert_name="OOMKilled",  # k8s event reason → normalize maps OOMKilled→OOMKilled
    summary="OOMKilled",
    description="container order OOMKilled — memory limit exceeded (exit code 137)",
    prod_only=False,
    non_deterministic=False,
    fingerprint_suffix="oom",
)

BAD_DEPLOYMENT_CONFIG = ScenarioSpec(
    name="bad_deployment_config",
    canonical_trigger="DeploymentUnavailable",
    trigger_source="kubernetes_event",
    signal_type="kubernetes_event",
    severity="critical",
    service="order",
    alert_name="DeploymentReplicasNotUpdated",  # reason → normalize maps →DeploymentUnavailable
    summary="DeploymentUnavailable",
    description="rollout stuck — replicas unavailable, readiness/startup probe failures",
    prod_only=False,
    non_deterministic=False,
    fingerprint_suffix="bad_deployment_config",
)

#: The 11 §3.7 fault-injection specs, in §3.7 table order. DERIVED, not invented.
BENCHMARK_SCENARIOS: tuple[ScenarioSpec, ...] = (
    DEPENDENCY_TIMEOUT,
    PAYMENT_FAILURE,
    LATENCY_SPIKE,
    DISK_PRESSURE,
    MEMORY_LEAK,
    INVENTORY_RESERVE_FAILURE,
    DNS_FAILURE,
    CERTIFICATE_EXPIRED,
    CRASHLOOP,
    OOM,
    BAD_DEPLOYMENT_CONFIG,
)

#: The 11 frozen canonical triggers, DERIVED from ``BENCHMARK_SCENARIOS``. The test
#: asserts this equals ``services.normalize.BENCHMARK_CANONICAL_TRIGGERS`` — proving
#: chaos's §3.7 derivation matches the agent's canonical vocabulary (no 12th / rename).
BENCHMARK_CANONICAL_TRIGGERS: frozenset[str] = frozenset(
    s.canonical_trigger for s in BENCHMARK_SCENARIOS
)


__all__ = [
    "BAD_DEPLOYMENT_CONFIG",
    "BENCHMARK_CANONICAL_TRIGGERS",
    "BENCHMARK_SCENARIOS",
    "CERTIFICATE_EXPIRED",
    "CRASHLOOP",
    "DEPENDENCY_TIMEOUT",
    "DISK_PRESSURE",
    "DNS_FAILURE",
    "INVENTORY_RESERVE_FAILURE",
    "LATENCY_SPIKE",
    "MEMORY_LEAK",
    "OOM",
    "PAYMENT_FAILURE",
    "ScenarioSpec",
    "Severity",
    "SignalType",
    "TriggerSource",
]
