"""eval/scenarios — the 11 §3.7 benchmark scenarios + deterministic inject contract (Story 6.1).

EVERY value here is **DERIVED, never invented**:

  - The 11 ``Scenario`` set + ``canonical_trigger`` + ``trigger_source`` + ``supporting_evidence``
    come verbatim from spec §3.7 (``docs/PROJECT_SPECS.md`` §3.7 table).
  - The A8 ``prod_only`` marking comes from the brainstorm ground-truth (``brainstorm-intent.md``
    :53 / :74 — *disk + memory are trustworthy ONLY multi-node* → prod-only; the other 9 are the
    POC single-node-deterministic set). ``memory_leak`` carries BOTH ``prod_only`` AND
    ``non_deterministic_extension``; ``disk_pressure`` carries ``prod_only`` only; ``latency_spike``
    carries ``non_deterministic_extension`` only — the two axes are ORTHOGONAL.
  - ``non_deterministic_extension`` (``"memory_leak"`` / ``"latency_spike"``) comes from brainstorm
    M3 (the two scenarios whose REAL metric shape is non-deterministic — tolerance window = Story 6.3).
  - ``signal_type`` / ``severity`` / ``service`` are derived from ``trigger_source`` + the §3.7 table
    + the POC ingest fixtures (``tests/test_ingest_normalize.py`` — order/payment/user-service,
    inventory, namespace ``demo``).

No 12th scenario; no renamed canonical — the test asserts
``{s.canonical_trigger} == services.normalize.BENCHMARK_CANONICAL_TRIGGERS`` (the frozen 11).

The ``inject`` per scenario = the canned read-only ``RawBackendResponse`` wire shapes (modeled on
the real backend shapes :class:`~adapters.transport.FakeReadOnlyTransport` models — Prometheus HTTP
vector, Loki streams, Kubernetes REST PodList/Pod/EventList/log). The test harness
(``tests/eval_harness.py``) routes each inject through a REAL :class:`~adapters.readonly.CompositeReadOnlyAdapter`
+ the REAL evidence_normalizer → tiered ``Evidence`` (no synthesized evidence — Epic-4 K2 real-stub
discipline). Same inject → byte-stable ``RawOutput``/``Evidence`` (AD-12 / NFR-Determinism).

Import-pure: ``eval.schema`` (the frozen dataclasses) + stdlib ONLY. See :mod:`eval.schema` for
the self-discipline rationale (``eval/`` is stdlib-only; the spec-domain membership of
``trigger_source`` / ``signal_type`` / ``severity`` is enforced in the TEST, not coupled here).
"""

from __future__ import annotations

from eval.schema import (
    ExpectedEvidence,
    InjectCall,
    RootCauseLabel,
    Scenario,
)

# Fixed incident window for every inject (deterministic — AD-12: no wall-clock). ISO-8601 UTC, the
# same shape evidence_normalizer validates as context["time_window"] for the non-windowed k8s tools.
_TIME_WINDOW: dict[str, str] = {"start": "2026-06-24T10:00:00Z", "end": "2026-06-24T10:05:00Z"}


# ---------------------------------------------------------------------------
# Canned RawBackendResponse builders — model the REAL backend wire shapes (Epic-4 K2).
# Plain ``dict[str, object]`` (JSON-safe — AD-9); bidirectional-typed so mypy-strict holds.
# ---------------------------------------------------------------------------


def _prometheus(query: str, service: str, value: str) -> dict[str, object]:
    """REAL Prometheus HTTP API instant-vector shape (status/data/resultType/result)."""
    return {
        "status": "success",
        "data": {
            "resultType": "vector",
            "result": [
                {"metric": {"__name__": query, "service": service}, "value": [1719216000.0, value]}
            ],
        },
    }


def _loki(service: str, line: str) -> dict[str, object]:
    """REAL Loki query_range streams shape (status/data/resultType=streams/result)."""
    return {
        "status": "success",
        "data": {
            "resultType": "streams",
            "result": [{"stream": {"service": service}, "values": [["1719216000000000000", line]]}],
        },
    }


def _k8s_events(reason: str, message: str, *, count: int = 3) -> dict[str, object]:
    """REAL Kubernetes EventList shape (kind/items — the fields k8s_get_events normalizes)."""
    return {
        "kind": "EventList",
        "items": [
            {
                "type": "Warning",
                "reason": reason,
                "message": message,
                "count": count,
                "involvedObject": {"name": "demo-pod-0"},
            }
        ],
    }


def _k8s_podlist(
    namespace: str, *, phase: str, restart_count: int, ready: bool = True
) -> dict[str, object]:
    """REAL Kubernetes PodList shape (kind/items — the fields k8s_get normalizes)."""
    return {
        "kind": "PodList",
        "items": [
            {
                "metadata": {"name": f"{namespace}-pod-0", "namespace": namespace},
                "status": {
                    "phase": phase,
                    "containerStatuses": [
                        {
                            "name": "app",
                            "ready": ready,
                            "restartCount": restart_count,
                            "state": {"running": {"startedAt": "2026-06-24T00:00:00Z"}},
                        }
                    ],
                },
            }
        ],
    }


def _k8s_pod(
    pod: str,
    namespace: str,
    *,
    phase: str,
    restart_count: int,
    termination_reason: str | None = None,
) -> dict[str, object]:
    """REAL Kubernetes single-Pod read shape (kind=Pod — the fields k8s_describe normalizes)."""
    last_state: dict[str, object] = (
        {"terminated": {"reason": termination_reason}} if termination_reason is not None else {}
    )
    return {
        "kind": "Pod",
        "metadata": {"name": pod, "namespace": namespace},
        "status": {
            "phase": phase,
            "containerStatuses": [
                {
                    "name": "app",
                    "ready": termination_reason is None,
                    "restartCount": restart_count,
                    "state": {},
                    "lastState": last_state,
                }
            ],
        },
    }


def _k8s_log(pod: str, lines: tuple[str, ...]) -> dict[str, object]:
    """REAL Kubernetes pod-log shape (a string body — the field k8s_logs normalizes into ``lines``)."""
    body = "\n".join(lines)
    return {"log": f"[{pod}] {body}"}


# ---------------------------------------------------------------------------
# The 11 §3.7 scenarios (DERIVED). trigger_source ∈ TRIGGER_SOURCES (3); each row matches §3.7.
# ---------------------------------------------------------------------------

DEPENDENCY_TIMEOUT = Scenario(
    name="dependency_timeout",
    canonical_trigger="DependencyTimeout",
    trigger_source="prometheus_alertmanager",
    signal_type="metric",
    severity="critical",
    service="order-service",
    namespace="demo",
    supporting_evidence=(
        "Downstream error counter, latency histogram, timeout logs."  # §3.7 verbatim
    ),
    root_cause=RootCauseLabel(
        faulty_service="payment-service",
        hypothesis="downstream dependency timeout — order-service calls to payment-service exceed timeout",
    ),
    expected_evidence=(
        ExpectedEvidence("prometheus", "order-service", "query_promql"),
        ExpectedEvidence("loki", "order-service", "query_loki"),
    ),
    inject=(
        InjectCall(
            "query_promql",
            {
                "query": "rate(http_client_duration_seconds_count{service='order-service'}[5m])",
                "time_window": dict(_TIME_WINDOW),
            },
            _prometheus("dependency_timeout_errors", "order-service", "42"),
        ),
        InjectCall(
            "query_loki",
            {"service": "order-service", "time_window": dict(_TIME_WINDOW), "correlation_id": None},
            _loki("order-service", "context deadline exceeded calling payment-service"),
        ),
    ),
    prod_only=False,
    non_deterministic_extension=None,
)

PAYMENT_FAILURE = Scenario(
    name="payment_failure",
    canonical_trigger="PaymentFailureHigh",
    trigger_source="prometheus_alertmanager",
    signal_type="metric",
    severity="critical",
    service="payment-service",
    namespace="demo",
    supporting_evidence=(
        "payment_failed_total, checkout_failed_total, order_rollback_total, provider error logs."  # §3.7
    ),
    root_cause=RootCauseLabel(
        faulty_service="payment-service",
        hypothesis="payment provider returning errors — payment_failed_total above threshold",
    ),
    expected_evidence=(
        ExpectedEvidence("prometheus", "payment-service", "query_promql"),
        ExpectedEvidence("loki", "payment-service", "query_loki"),
    ),
    inject=(
        InjectCall(
            "query_promql",
            {"query": "payment_failed_total", "time_window": dict(_TIME_WINDOW)},
            _prometheus("payment_failed_total", "payment-service", "137"),
        ),
        InjectCall(
            "query_loki",
            {
                "service": "payment-service",
                "time_window": dict(_TIME_WINDOW),
                "correlation_id": None,
            },
            _loki("payment-service", "provider returned 502 bad gateway"),
        ),
    ),
    prod_only=False,
    non_deterministic_extension=None,
)

LATENCY_SPIKE = Scenario(
    name="latency_spike",
    canonical_trigger="DownstreamLatencyHigh",
    trigger_source="prometheus_alertmanager",
    signal_type="metric",
    severity="warning",
    service="order-service",
    namespace="demo",
    supporting_evidence=(
        "p95/p99 latency, dependency duration histogram, service latency logs."  # §3.7
    ),
    root_cause=RootCauseLabel(
        faulty_service="order-service",
        hypothesis="downstream latency spike — p95/p99 above SLO on order-service dependency calls",
    ),
    expected_evidence=(
        ExpectedEvidence("prometheus", "order-service", "query_promql"),
        ExpectedEvidence("loki", "order-service", "query_loki"),
    ),
    inject=(
        InjectCall(
            "query_promql",
            {
                "query": "histogram_quantile(0.99, http_request_duration_seconds_bucket)",
                "time_window": dict(_TIME_WINDOW),
            },
            _prometheus("p99_latency", "order-service", "2.8"),
        ),
        InjectCall(
            "query_loki",
            {"service": "order-service", "time_window": dict(_TIME_WINDOW), "correlation_id": None},
            _loki("order-service", "slow request: downstream latency 2800ms"),
        ),
    ),
    prod_only=False,
    non_deterministic_extension="latency_spike",  # REAL p95/p99 metric is non-deterministic → 6.3
)

DISK_PRESSURE = Scenario(
    name="disk_pressure",
    canonical_trigger="NodeDiskPressure",
    trigger_source="prometheus_alertmanager",
    signal_type="metric",
    severity="critical",
    service="demo-node-1",  # node-scoped (DiskPressure is a node condition) — flagged in REVIEW-READY
    namespace="demo",
    supporting_evidence=(
        "node filesystem metrics, DiskPressure condition, Kubernetes events, write/no-space logs."  # §3.7
    ),
    root_cause=RootCauseLabel(
        faulty_service="demo-node-1",
        hypothesis="node disk pressure — filesystem near full, node DiskPressure condition raised",
    ),
    expected_evidence=(
        ExpectedEvidence("prometheus", "demo-node-1", "query_promql"),
        ExpectedEvidence("kubernetes", "demo", "k8s_get_events"),
        ExpectedEvidence("loki", "demo-node-1", "query_loki"),
    ),
    inject=(
        InjectCall(
            "query_promql",
            {"query": "node_filesystem_avail_bytes", "time_window": dict(_TIME_WINDOW)},
            _prometheus("node_filesystem_avail_bytes", "demo-node-1", "0.02"),
        ),
        InjectCall(
            "k8s_get_events",
            {"namespace": "demo", "field_selector": None},
            _k8s_events("DiskPressure", "node demo-node-1 has DiskPressure condition"),
        ),
        InjectCall(
            "query_loki",
            {"service": "demo-node-1", "time_window": dict(_TIME_WINDOW), "correlation_id": None},
            _loki("demo-node-1", "write error: no space left on device"),
        ),
    ),
    prod_only=True,  # A8: disk trustworthy ONLY multi-node (brainstorm:53,:74)
    non_deterministic_extension=None,
)

MEMORY_LEAK = Scenario(
    name="memory_leak",
    canonical_trigger="MemoryUsageHigh",
    trigger_source="prometheus_alertmanager",
    signal_type="metric",
    severity="critical",
    service="order-service",
    namespace="demo",
    supporting_evidence=(
        "memory growth trend, container_memory_working_set_bytes, restart count, leak logs."  # §3.7
    ),
    root_cause=RootCauseLabel(
        faulty_service="order-service",
        hypothesis="memory leak — container_memory_working_set_bytes growing monotonically toward the limit",
    ),
    expected_evidence=(
        ExpectedEvidence("prometheus", "order-service", "query_promql"),
        ExpectedEvidence("kubernetes", "demo", "k8s_get"),
        ExpectedEvidence("loki", "order-service", "query_loki"),
    ),
    inject=(
        InjectCall(
            "query_promql",
            {"query": "container_memory_working_set_bytes", "time_window": dict(_TIME_WINDOW)},
            _prometheus("container_memory_working_set_bytes", "order-service", "0.94"),
        ),
        InjectCall(
            "k8s_get",
            {"namespace": "demo", "label_selector": "app=order-service"},
            _k8s_podlist("demo", phase="Running", restart_count=4, ready=False),
        ),
        InjectCall(
            "query_loki",
            {"service": "order-service", "time_window": dict(_TIME_WINDOW), "correlation_id": None},
            _loki("order-service", "memory usage at 94% of limit; possible leak"),
        ),
    ),
    prod_only=True,  # A8: memory trustworthy ONLY multi-node (brainstorm:53,:74)
    non_deterministic_extension="memory_leak",  # REAL memory-trend metric is non-deterministic → 6.3
)

INVENTORY_RESERVE_FAILURE = Scenario(
    name="inventory_reserve_failure",
    canonical_trigger="InventoryReserveFailureHigh",
    trigger_source="prometheus_alertmanager",
    signal_type="metric",
    severity="critical",
    service="inventory",
    namespace="demo",
    supporting_evidence=(
        "inventory_reserve_failed_total, inventory reservation metrics, inventory/order logs."  # §3.7
    ),
    root_cause=RootCauseLabel(
        faulty_service="inventory",
        hypothesis="inventory reserve failing — inventory_reserve_failed_total above threshold",
    ),
    expected_evidence=(
        ExpectedEvidence("prometheus", "inventory", "query_promql"),
        ExpectedEvidence("loki", "inventory", "query_loki"),
    ),
    inject=(
        InjectCall(
            "query_promql",
            {"query": "inventory_reserve_failed_total", "time_window": dict(_TIME_WINDOW)},
            _prometheus("inventory_reserve_failed_total", "inventory", "58"),
        ),
        InjectCall(
            "query_loki",
            {"service": "inventory", "time_window": dict(_TIME_WINDOW), "correlation_id": None},
            _loki("inventory", "reserve failed: out of stock for sku"),
        ),
    ),
    prod_only=False,
    non_deterministic_extension=None,
)

DNS_FAILURE = Scenario(
    name="dns_failure",
    canonical_trigger="DNSFailureLogSpike",
    trigger_source="grafana_alerting_loki",
    signal_type="log",
    severity="warning",
    service="user-service",  # the alerting service (GRAFANA_DNS fixture); root cause is CoreDNS
    namespace="demo",
    supporting_evidence=(
        "DNS error logs, CoreDNS logs, downstream errors."  # §3.7
    ),
    root_cause=RootCauseLabel(
        faulty_service="coredns",  # DNS infra is the root cause, not the victim user-service — flagged
        hypothesis="DNS resolution failing — CoreDNS error log spike, downstream NXDOMAIN errors",
    ),
    expected_evidence=(ExpectedEvidence("loki", "user-service", "query_loki"),),
    inject=(
        InjectCall(
            "query_loki",
            {"service": "user-service", "time_window": dict(_TIME_WINDOW), "correlation_id": None},
            _loki("user-service", "dns resolution failed: NXDOMAIN for downstream.internal"),
        ),
    ),
    prod_only=False,
    non_deterministic_extension=None,
)

CERTIFICATE_EXPIRED = Scenario(
    name="certificate_expired",
    canonical_trigger="CertificateErrorDetected",
    trigger_source="grafana_alerting_loki",
    signal_type="log",
    severity="warning",
    service="order-service",
    namespace="demo",
    supporting_evidence=(
        "x509/certificate validation logs, TLS/external call failure logs."  # §3.7
    ),
    root_cause=RootCauseLabel(
        faulty_service="order-service",
        hypothesis="TLS certificate expired — x509 validation failure on outbound external calls",
    ),
    expected_evidence=(ExpectedEvidence("loki", "order-service", "query_loki"),),
    inject=(
        InjectCall(
            "query_loki",
            {"service": "order-service", "time_window": dict(_TIME_WINDOW), "correlation_id": None},
            _loki("order-service", "tls: certificate has expired (x509: certificate expired)"),
        ),
    ),
    prod_only=False,
    non_deterministic_extension=None,
)

CRASHLOOP = Scenario(
    name="crashloop",
    canonical_trigger="CrashLoopBackOff",
    trigger_source="kubernetes_event",
    signal_type="kubernetes_event",
    severity="critical",
    service="payment-service",  # K8S_CRASHLOOP fixture: payment pod, BackOff
    namespace="demo",
    supporting_evidence=(
        "pod status, restart count, BackOff events, previous logs."  # §3.7
    ),
    root_cause=RootCauseLabel(
        faulty_service="payment-service",
        hypothesis="crash loop — payment pod restarting repeatedly (BackOff); previous-container log shows the crash cause",
    ),
    expected_evidence=(
        ExpectedEvidence("kubernetes", "demo", "k8s_get"),
        ExpectedEvidence("kubernetes", "demo", "k8s_get_events"),
        ExpectedEvidence("kubernetes", "demo", "k8s_logs"),
    ),
    inject=(
        InjectCall(
            "k8s_get",
            {"namespace": "demo", "label_selector": "app=payment-service"},
            _k8s_podlist("demo", phase="Running", restart_count=7, ready=False),
        ),
        InjectCall(
            "k8s_get_events",
            {"namespace": "demo", "field_selector": None},
            _k8s_events("BackOff", "back-off restarting failed container payment"),
        ),
        InjectCall(
            "k8s_logs",
            {"namespace": "demo", "pod": "payment-abc", "previous": True},
            _k8s_log(
                "payment-abc", ("panic: nil pointer dereference", "container exited with code 2")
            ),
        ),
    ),
    prod_only=False,
    non_deterministic_extension=None,
)

OOM = Scenario(
    name="oom",
    canonical_trigger="OOMKilled",
    trigger_source="kubernetes_event",
    signal_type="kubernetes_event",
    severity="critical",
    service="order-service",
    namespace="demo",
    supporting_evidence=(
        "termination reason, exit code 137, memory metrics, Kubernetes events."  # §3.7
    ),
    root_cause=RootCauseLabel(
        faulty_service="order-service",
        hypothesis="OOMKilled — container terminated (reason OOMKilled, exit 137); memory limit exceeded",
    ),
    expected_evidence=(
        ExpectedEvidence("kubernetes", "demo", "k8s_describe"),
        ExpectedEvidence("kubernetes", "demo", "k8s_get_events"),
        ExpectedEvidence("prometheus", "order-service", "query_promql"),
    ),
    inject=(
        InjectCall(
            "k8s_describe",
            {"namespace": "demo", "pod": "order-service-abc"},
            _k8s_pod(
                "order-service-abc",
                "demo",
                phase="Failed",
                restart_count=3,
                termination_reason="OOMKilled",
            ),
        ),
        InjectCall(
            "k8s_get_events",
            {"namespace": "demo", "field_selector": None},
            _k8s_events("OOMKilling", "container order-service was OOMKilled (exit code 137)"),
        ),
        InjectCall(
            "query_promql",
            {"query": "container_memory_usage_bytes", "time_window": dict(_TIME_WINDOW)},
            _prometheus("container_memory_usage_bytes", "order-service", "0.99"),
        ),
    ),
    prod_only=False,
    non_deterministic_extension=None,
)

BAD_DEPLOYMENT_CONFIG = Scenario(
    name="bad_deployment_config",
    canonical_trigger="DeploymentUnavailable",
    trigger_source="kubernetes_event",
    signal_type="kubernetes_event",
    severity="critical",
    service="order-service",
    namespace="demo",
    supporting_evidence=(
        "rollout status, unavailable replicas, probe events, config/startup logs."  # §3.7
    ),
    root_cause=RootCauseLabel(
        faulty_service="order-service",
        hypothesis="bad deployment config — rollout stuck, replicas unavailable, readiness/startup probe failures",
    ),
    expected_evidence=(
        ExpectedEvidence("kubernetes", "demo", "k8s_get"),
        ExpectedEvidence("loki", "order-service", "query_loki"),
    ),
    inject=(
        InjectCall(
            "k8s_get",
            {"namespace": "demo", "label_selector": "app=order-service"},
            _k8s_podlist("demo", phase="Running", restart_count=0, ready=False),
        ),
        InjectCall(
            "query_loki",
            {"service": "order-service", "time_window": dict(_TIME_WINDOW), "correlation_id": None},
            _loki("order-service", "readiness probe failed: get http 500; startup config invalid"),
        ),
    ),
    prod_only=False,
    non_deterministic_extension=None,
)

#: The 11 §3.7 benchmark scenarios, in §3.7 table order. DERIVED, not invented.
BENCHMARK_SCENARIOS: tuple[Scenario, ...] = (
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

#: The 11 frozen canonical triggers, DERIVED from ``BENCHMARK_SCENARIOS`` (NOT re-hardcoded). The
#: test asserts this equals ``services.normalize.BENCHMARK_CANONICAL_TRIGGERS`` (the existing
#: source-of-truth) + the ``tests/test_ingest_normalize.py`` frozenset — proving no 12th / rename.
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
]
