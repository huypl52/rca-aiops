"""The 10 read-only executor functions — spec §3.6 tool set (7 row / 10 function).

Story 2.1 — AD-3 (BLOCKER read-only boundary) / FR-5 / AD-9 (JSON-safe raw output).

Each executor is a **read-only** callable: it takes a **query** (service / metric / logql / pod /
time-window / playbook as relevant) + an **adapter PORT** (``ReadOnlyAdapterPort``) and returns
**RAW output as a plain JSON-safe dict** (AD-9). An executor **MUST NOT** construct ``Evidence``
objects — the 9-field Evidence normalization is **Story 4.2 (E4)**. The contract here is the raw
hand-off: ``raw output → evidence_normalizer (E4)``.

Each executor only **reads / collects / summarizes** (AC3, §3.8). NO cluster side-effect; NO
write/exec/patch/... path. Names are the EXACT spec §3.6 table — none equals a deny-verb (gate #1
AST exact-match safe; ``topology_executor != "exec"``).

Sync + deterministic: real cluster I/O lives in the adapter (Story 2.2). The default
``StubReadOnlyAdapter`` makes every executor callable offline now.

ONE-WAY (AD-1 / gate #2): imports ``tools.port`` (same layer) + stdlib only. NEVER imports
``routers``/``services``/``graph``/``adapters``.
"""

from __future__ import annotations

from tools.port import RawOutput, ReadOnlyAdapterPort, TimeWindow, ToolExecutor

# ONE-WAY (AD-1 / gate #2): tools.port (same layer) + stdlib only.


def collect_prometheus_metric_evidence(
    adapter: ReadOnlyAdapterPort,
    *,
    service: str,
    metric: str,
    evidence_type: str,
    time_window: TimeWindow,
) -> RawOutput:
    """Collect a Prometheus metric summary by template evidence type (spec §3.6 row 1).

    Runs the metric's PromQL diagnostic query through the adapter and tags the RAW result with the
    requested ``evidence_type`` template. Read-only; returns RAW output (Evidence = 4.2).
    """
    query = f'{metric}{{service="{service}"}}'
    raw = adapter.query_promql(query=query, time_window=time_window)
    return {
        **raw,
        "source_name": service,
        "metric": metric,
        "evidence_type": evidence_type,
    }


def query_prometheus_raw(
    adapter: ReadOnlyAdapterPort,
    *,
    query: str,
    time_window: TimeWindow,
) -> RawOutput:
    """Run a diagnostic PromQL query (spec §3.6 row 2). Read-only; RAW output."""
    return adapter.query_promql(query=query, time_window=time_window)


def query_prometheus_histogram_percentile(
    adapter: ReadOnlyAdapterPort,
    *,
    metric: str,
    percentile: float,
    time_window: TimeWindow,
) -> RawOutput:
    """Query a p95/p99 latency from a histogram bucket (spec §3.6 row 3). Read-only; RAW output."""
    quantile = f"{percentile:g}"
    query = f"histogram_quantile({quantile}, sum(rate({metric}_bucket[5m])) by (le))"
    raw = adapter.query_promql(query=query, time_window=time_window)
    return {
        **raw,
        "metric": metric,
        "percentile": percentile,
    }


def query_loki_service_logs(
    adapter: ReadOnlyAdapterPort,
    *,
    service: str,
    time_window: TimeWindow,
    correlation_id: str | None = None,
    query: str | None = None,
) -> RawOutput:
    """Query Loki logs by service / time window / correlation id (spec §3.6 row 4). Read-only.

    ``query`` is accepted as an inert identifying field so graph-level plans can satisfy the shared
    ``tool``/``query``/``timestamp_range`` contract without inventing a second Loki-only plan shape.
    The actual Loki adapter contract remains ``service`` + ``time_window`` + ``correlation_id``.
    """
    del query
    return adapter.query_loki(
        service=service,
        time_window=time_window,
        correlation_id=correlation_id,
    )


def k8s_get_pods(
    adapter: ReadOnlyAdapterPort,
    *,
    namespace: str,
    label_selector: str | None = None,
) -> RawOutput:
    """List pods — phase, readiness, restart count, container state (spec §3.6 row 5). Read-only."""
    return adapter.k8s_get(namespace=namespace, label_selector=label_selector)


def k8s_describe_pod(
    adapter: ReadOnlyAdapterPort,
    *,
    namespace: str,
    pod: str,
) -> RawOutput:
    """Describe a pod — termination reason, container state (spec §3.6 row 6). Read-only."""
    return adapter.k8s_describe(namespace=namespace, pod=pod)


def k8s_logs(
    adapter: ReadOnlyAdapterPort,
    *,
    namespace: str,
    pod: str,
    previous: bool = False,
) -> RawOutput:
    """Read current/previous pod logs (spec §3.6 row 7). Read-only."""
    return adapter.k8s_logs(namespace=namespace, pod=pod, previous=previous)


def k8s_get_events(
    adapter: ReadOnlyAdapterPort,
    *,
    namespace: str,
    field_selector: str | None = None,
) -> RawOutput:
    """Read namespace/object events (spec §3.6 row 8). Read-only."""
    return adapter.k8s_get_events(namespace=namespace, field_selector=field_selector)


def search_playbook(
    adapter: ReadOnlyAdapterPort,
    *,
    query: str,
    top_k: int = 5,
) -> RawOutput:
    """Search playbook/runbook (Qdrant / local Markdown) (spec §3.6 row 9). Read-only."""
    return adapter.search_playbook(query=query, top_k=top_k)


def topology_executor(
    adapter: ReadOnlyAdapterPort,
    *,
    service: str | None = None,
) -> RawOutput:
    """Read service/dependency relations (topology) (spec §3.6 row 10). Read-only.

    NOTE: the name ``topology_executor`` is NOT a gate #1 false positive — the AST gate matches
    ``node.name in WRITE_VERBS`` EXACTLY (``"topology_executor" != "exec"``). Do not rename it.
    """
    return adapter.topology_read(service=service)


# The canonical spec §3.6 set, in registry order. EXACTLY 10 — count by the spec TABLE (L2).
# ``executor_map`` is what ``build_default_registry`` registers; keeping it here (next to the
# functions) makes the "no invented / no missing count" contract locally checkable.
EXECUTORS: dict[str, ToolExecutor] = {
    "collect_prometheus_metric_evidence": collect_prometheus_metric_evidence,
    "query_prometheus_raw": query_prometheus_raw,
    "query_prometheus_histogram_percentile": query_prometheus_histogram_percentile,
    "query_loki_service_logs": query_loki_service_logs,
    "k8s_get_pods": k8s_get_pods,
    "k8s_describe_pod": k8s_describe_pod,
    "k8s_logs": k8s_logs,
    "k8s_get_events": k8s_get_events,
    "search_playbook": search_playbook,
    "topology_executor": topology_executor,
}


__all__ = [
    "EXECUTORS",
    "collect_prometheus_metric_evidence",
    "k8s_describe_pod",
    "k8s_get_events",
    "k8s_get_pods",
    "k8s_logs",
    "query_loki_service_logs",
    "query_prometheus_histogram_percentile",
    "query_prometheus_raw",
    "search_playbook",
    "topology_executor",
]
