"""chaos/driver — the LIVE cluster seam (Story 7.3 AC1).

Documents HOW chaos would, in a live cluster, drive the demo SUT (Story 7.1) into
each §3.7 fault so the affected demo service emits the abnormal symptom the 7.2
stack detects — the live chain that :mod:`chaos.inject` condenses into one
deterministic trigger payload. This mirrors the 7.2 ``event_watcher_runner`` live
seam: it is RUNNER GLUE, NOT unit-tested (no local K8s in this dev env), and is
correct-by-construction; the TESTED, agent-free, deterministic core lives in
:mod:`chaos.inject` (proven in-process for all 11).

Determinism note (AD-12): this module DESCRIBES live actions, which inherently
involve a real cluster + wall-clock (e.g. a real poll cadence, a real scrape).
It is therefore NOT on the AD-12 determinism path — the deterministic proof
surface is :mod:`chaos.inject` + the in-process normalization test. The function
here returns a stable, literal action string per scenario (no cluster call), so
its OWN output is reproducible, but executing the action is a live-only op.

Import-pure: stdlib + :mod:`chaos.scenarios` ONLY. ``chaos`` MAY import ``demo``
to drive the SUT (a permitted edge); this POC keeps the edge unused (the driver is
descriptive) so the chaos core has zero coupling — wiring the live demo import is
deferred to a cluster-backed environment, alongside the 5-A1 real-transport.
"""

from __future__ import annotations

from chaos.scenarios import BENCHMARK_SCENARIOS

#: Per-scenario live fault + detection chain. The left side is the demo-SUT fault
#: chaos would create; the right side is the 7.2 detection path that fires the
#: incident. Each action is a literal string (AD-12-safe: no call, no clock).
_LIVE_FAULT_ACTION: dict[str, str] = {
    "dependency_timeout": (
        "set DEMO_UPSTREAM_PAYMENT_URL to a blackhole -> order call_upstream records "
        "demo_upstream_errors_total>0 -> DependencyTimeout rule -> Alertmanager -> ingest"
    ),
    "payment_failure": (
        "flip DEMO_UPSTREAM_PAYMENT to return 5xx -> payment call_upstream records "
        "demo_upstream_errors_total>0 -> PaymentFailureHigh rule -> Alertmanager -> ingest"
    ),
    "latency_spike": (
        "raise DEMO_REQUEST rate / inject slow upstream -> demo_requests_total spike -> "
        "DownstreamLatencyHigh rule -> Alertmanager -> ingest (NON-DET real p95 -> 6.3)"
    ),
    "disk_pressure": (
        "fill a node volume (prod multi-node) -> node_filesystem_avail_bytes low -> "
        "NodeDiskPressure rule -> Alertmanager -> ingest (prod_only -> 6.3)"
    ),
    "memory_leak": (
        "leak memory toward the container limit -> container_memory_working_set_bytes high -> "
        "MemoryUsageHigh rule -> Alertmanager -> ingest (prod_only + NON-DET -> 6.3)"
    ),
    "inventory_reserve_failure": (
        "flip DEMO_UPSTREAM_INVENTORY to 5xx -> order/inventory call_upstream records "
        "demo_upstream_errors_total>0 -> InventoryReserveFailureHigh rule -> Alertmanager -> ingest"
    ),
    "dns_failure": (
        "emit user-service logs matching dns+failure -> Loki LogQL DNSFailureLogSpike rule -> "
        "Grafana Alerting -> ingest"
    ),
    "certificate_expired": (
        "emit order-service logs matching certificate+expired -> Loki LogQL "
        "CertificateErrorDetected rule -> Grafana Alerting -> ingest"
    ),
    "crashloop": (
        "force the payment pod to exit non-zero -> k8s BackOff event -> event-watcher "
        "POSTs /api/events/kubernetes -> normalize BackOff->CrashLoopBackOff"
    ),
    "oom": (
        "exceed the order container memory limit -> k8s OOMKilled event -> event-watcher "
        "POSTs /api/events/kubernetes -> normalize OOMKilled->OOMKilled"
    ),
    "bad_deployment_config": (
        "ship an invalid readiness probe / bad env on the order Deployment -> k8s "
        "DeploymentReplicasNotUpdated event -> event-watcher POSTs /api/events/kubernetes "
        "-> normalize -> DeploymentUnavailable"
    ),
}


def live_fault_action(scenario: str) -> str:
    """Return the documented live fault + 7.2 detection chain for one §3.7 scenario.

    Pure + deterministic (a dict lookup of a literal string — no cluster call).
    Raises ``KeyError`` for a scenario key outside the §3.7 eleven.
    """
    if scenario not in _LIVE_FAULT_ACTION:
        raise KeyError(f"unknown §3.7 scenario: {scenario!r}")
    return _LIVE_FAULT_ACTION[scenario]


def main() -> None:
    """Print every scenario's live fault + detection chain (a runbook / reporting aid)."""
    for spec in BENCHMARK_SCENARIOS:
        print(f"{spec.name} [{spec.canonical_trigger}]: {live_fault_action(spec.name)}")


if __name__ == "__main__":  # pragma: no cover - reporting entrypoint
    main()


__all__ = ["live_fault_action", "main"]
