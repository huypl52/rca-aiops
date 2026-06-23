"""Read-only source adapters — real normalization logic over the transport seam (AD-3 / AC3 / AC5).

Story 2.2 — AD-3 (read-only boundary) / AD-2 (port) / AD-12 (determinism) / AD-9 (JSON-safe) / AC3.

Five source adapter classes (Prometheus / Loki / Kubernetes / Qdrant / topology) together implement
the **8 read methods** of ``tools.port.ReadOnlyAdapterPort`` (the PORT shipped in Story 2.1). A
``CompositeReadOnlyAdapter`` holds all five and delegates each of the 8 methods to its source adapter
— that composite is the object a tool receives, and it satisfies ``ReadOnlyAdapterPort``
(``isinstance`` runtime_checkable, AC5 seam held — ``tools/`` is UNCHANGED).

Division of labor (the real value of this story lives here):
  - **Transport** (``adapters/transport.py``) = the I/O seam. Returns the raw backend response
    (the REAL wire shape — Prometheus HTTP API, Loki streams, Kubernetes REST, Qdrant hits, a
    topology graph) or raises ``TransportError``. Real transport = Epic 7; 2-2 ships a deterministic
    fake that models the real shapes so the normalization below is genuinely exercised offline.
  - **Source adapter** (this module) = real read-only NORMALIZATION. Maps the backend response into
    the tool ``RawOutput`` shape — the SAME shape the Story-2.1 ``StubReadOnlyAdapter`` produced, so
    the Evidence normalizer (Story 4.2) sees one stable contract regardless of which adapter is
    plugged. Plus: a structured error envelope on failure (AC3 — NEVER raises into the graph), and
    time_window pass-through (AC3) for the time-windowed queries (prom/loki).

Read-only (AD-3 / §3.8 / gate #1): every method here is read/query. The transport issues READ verbs
only (GET for the HTTP APIs; list/read semantics for K8s REST; query-only for Qdrant) — no
``write``/``exec``/``patch``/``delete``/``scale``/``rollback``/``restart``/``remediate`` method name,
no POST/PUT/PATCH/DELETE / mutating K8s verb anywhere (leader-grep'd in the contract tests). A
backend that returns an ERROR response (Prometheus/Loki ``status == "error"``, a Kubernetes
``kind == "Status"`` failure, a Qdrant/topology ``"error"`` payload) is folded into the SAME error
envelope as a transport failure — both are AC3 "source failure → structured RawOutput".

ONE-WAY (AD-1 / gate #2): imports ``adapters.transport`` (same layer) + ``tools.port`` (FORWARD edge
— tools idx4, adapters idx3, allowed) + stdlib only. NEVER imports ``graph``/``services``/``routers``.

RAW output, NOT Evidence (boundary = 4.2): adapters return plain JSON-safe dicts. NO ``models``
import / ``Evidence(`` construction.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from adapters.transport import ReadOnlyTransport, TransportError
from tools.port import JsonValue, RawOutput, TimeWindow

# ONE-WAY (AD-1 / gate #2): adapters.transport (same layer) + tools.port (forward, allowed) + stdlib.
# NEVER imports routers/services/graph (back-edge forbidden). NEVER imports models (Evidence = 4.2).


def _echo_time_window(time_window: TimeWindow) -> dict[str, JsonValue]:
    """Bounded ``timestamp_range`` echo (AC3) — same shape as ``tools.port._echo_time_window``."""
    return {"start": time_window.get("start"), "end": time_window.get("end")}


def _error_envelope(
    source_type: str,
    code: str,
    detail: str,
    **extra: JsonValue,
) -> RawOutput:
    """Structured RawOutput error envelope (AC3) — a tool ALWAYS returns a dict, never raises.

    ``code`` is one of ``transport_error`` (the seam raised ``TransportError``) or ``backend_error``
    (the source returned an error response). Interpretation of the envelope (mapping to an Evidence
    tier / sufficiency consequence) is Story 4.2 — adapters only PRODUCE the raw envelope.
    """
    envelope: dict[str, JsonValue] = {
        "source_type": source_type,
        "error": {"code": code, "detail": detail},
    }
    envelope.update(extra)
    return envelope


# --- JSON-value narrowing helpers (JsonValue is a wide union; narrow before .get/iterate) ---


def _as_mapping(value: JsonValue | None) -> Mapping[str, JsonValue]:
    """Narrow a JSON value to a ``Mapping[str, JsonValue]`` (empty dict if not a mapping)."""
    return value if isinstance(value, Mapping) else {}


def _as_mapping_list(value: JsonValue | None) -> list[Mapping[str, JsonValue]]:
    """Narrow a JSON value to a list of Mappings (drops non-mapping items)."""
    out: list[Mapping[str, JsonValue]] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, Mapping):
                out.append(item)
    return out


def _as_json_list(value: JsonValue | None) -> list[JsonValue]:
    """Narrow a JSON value to a ``list[JsonValue]`` (empty if not a list)."""
    return list(value) if isinstance(value, list) else []


def _to_json_list(items: Iterable[JsonValue]) -> list[JsonValue]:
    """Materialize a ``JsonValue``-valued iterable into ``list[JsonValue]``.

    Needed because ``list`` is INVARIANT: ``list[dict[str, JsonValue]]`` is not a ``list[JsonValue]``
    even though ``dict[str, JsonValue]`` is a ``JsonValue``. ``Iterable`` IS covariant, so a generator
    of ``dict[str, JsonValue]`` items is an ``Iterable[JsonValue]`` and this materializes it cleanly.
    """
    return list(items)


# --- Kubernetes response helpers (read-only normalization of the REST object graph) ---


def _normalize_pod(pod: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    """Read a single K8s Pod REST object → the stub-aligned pod summary (name/phase/ready/...)."""
    meta = _as_mapping(pod.get("metadata"))
    status = _as_mapping(pod.get("status"))
    containers = _as_mapping_list(status.get("containerStatuses"))
    first_map = containers[0] if containers else {}
    return {
        "name": meta.get("name"),
        "phase": status.get("phase"),
        "ready": bool(first_map.get("ready", False)),
        "restart_count": first_map.get("restartCount", 0),
        "container_state": first_map.get("state") or {},
    }


def _k8s_is_status_failure(resp: Mapping[str, JsonValue]) -> bool:
    """A K8s REST failure is returned as a ``kind == "Status"`` object (NOT an HTTP raise)."""
    return resp.get("kind") == "Status"


def _k8s_backend_error_or(
    resp: Mapping[str, JsonValue],
    *,
    source_name: str,
    **extra: JsonValue,
) -> RawOutput | None:
    """If ``resp`` is a K8s ``Status`` failure, return its error envelope; else None (success path)."""
    if _k8s_is_status_failure(resp):
        return _error_envelope(
            "kubernetes",
            "backend_error",
            str(resp.get("message") or "k8s status failure"),
            source_name=source_name,
            **extra,
        )
    return None


class PrometheusAdapter:
    """Prometheus read adapter — PromQL diagnostic query (1 of the 8 port methods)."""

    def __init__(self, transport: ReadOnlyTransport) -> None:
        self._transport = transport

    def query_promql(self, *, query: str, time_window: TimeWindow) -> RawOutput:
        try:
            resp = self._transport.read_prometheus(query=query, time_window=time_window)
        except TransportError as exc:
            return _error_envelope(
                "prometheus",
                "transport_error",
                str(exc),
                query=query,
                time_window=_echo_time_window(time_window),
            )
        if resp.get("status") == "error":
            return _error_envelope(
                "prometheus",
                "backend_error",
                str(resp.get("error") or resp.get("errorType") or "unknown"),
                query=query,
                time_window=_echo_time_window(time_window),
            )
        data = resp.get("data") or {}
        data_map: Mapping[str, JsonValue] = data if isinstance(data, Mapping) else {}
        return {
            "source_type": "prometheus",
            "query": query,
            "time_window": _echo_time_window(time_window),
            "result_type": data_map.get("resultType"),
            "result": data_map.get("result"),
        }


class LokiAdapter:
    """Loki read adapter — service logs by LogQL selector (1 of the 8 port methods)."""

    def __init__(self, transport: ReadOnlyTransport) -> None:
        self._transport = transport

    def query_loki(
        self,
        *,
        service: str,
        time_window: TimeWindow,
        correlation_id: str | None,
    ) -> RawOutput:
        try:
            resp = self._transport.read_loki(
                service=service,
                time_window=time_window,
                correlation_id=correlation_id,
            )
        except TransportError as exc:
            return _error_envelope(
                "loki",
                "transport_error",
                str(exc),
                source_name=service,
                time_window=_echo_time_window(time_window),
                correlation_id=correlation_id,
            )
        if resp.get("status") == "error":
            return _error_envelope(
                "loki",
                "backend_error",
                str(resp.get("error") or "unknown"),
                source_name=service,
                time_window=_echo_time_window(time_window),
                correlation_id=correlation_id,
            )
        data = resp.get("data") or {}
        data_map: Mapping[str, JsonValue] = data if isinstance(data, Mapping) else {}
        return {
            "source_type": "loki",
            "source_name": service,
            "time_window": _echo_time_window(time_window),
            "correlation_id": correlation_id,
            "streams": data_map.get("result"),
        }


class K8sAdapter:
    """Kubernetes read adapter — pods / describe / logs / events (4 of the 8 port methods).

    All four map to READ-only K8s REST calls via ``read_k8s`` (list Pods, read a Pod, read a Pod log,
    list Events). No mutating K8s verb is ever forwarded (gate #1 + leader-grep enforced).
    """

    def __init__(self, transport: ReadOnlyTransport) -> None:
        self._transport = transport

    def k8s_get(self, *, namespace: str, label_selector: str | None) -> RawOutput:
        try:
            resp = self._transport.read_k8s(
                namespace=namespace,
                kind="pods",
                name=None,
                subresource=None,
                label_selector=label_selector,
                field_selector=None,
                previous=False,
            )
        except TransportError as exc:
            return _error_envelope(
                "kubernetes",
                "transport_error",
                str(exc),
                source_name=namespace,
                label_selector=label_selector,
            )
        backend_error = _k8s_backend_error_or(
            resp, source_name=namespace, label_selector=label_selector
        )
        if backend_error is not None:
            return backend_error
        pods = _to_json_list(_normalize_pod(p) for p in _as_mapping_list(resp.get("items")))
        return {
            "source_type": "kubernetes",
            "source_name": namespace,
            "label_selector": label_selector,
            "pods": pods,
        }

    def k8s_describe(self, *, namespace: str, pod: str) -> RawOutput:
        try:
            resp = self._transport.read_k8s(
                namespace=namespace,
                kind="pods",
                name=pod,
                subresource=None,
                label_selector=None,
                field_selector=None,
                previous=False,
            )
        except TransportError as exc:
            return _error_envelope(
                "kubernetes",
                "transport_error",
                str(exc),
                source_name=pod,
                namespace=namespace,
            )
        backend_error = _k8s_backend_error_or(resp, source_name=pod, namespace=namespace)
        if backend_error is not None:
            return backend_error
        status_map = _as_mapping(resp.get("status"))
        containers = _as_mapping_list(status_map.get("containerStatuses"))
        first_map = containers[0] if containers else {}
        last_state = first_map.get("lastState")
        terminated = last_state.get("terminated") if isinstance(last_state, Mapping) else None
        termination_reason = terminated.get("reason") if isinstance(terminated, Mapping) else None
        return {
            "source_type": "kubernetes",
            "source_name": pod,
            "namespace": namespace,
            "describe": {
                "phase": status_map.get("phase"),
                "termination_reason": termination_reason,
                "container_state": first_map.get("state") or {},
            },
        }

    def k8s_logs(self, *, namespace: str, pod: str, previous: bool) -> RawOutput:
        try:
            resp = self._transport.read_k8s(
                namespace=namespace,
                kind="pods",
                name=pod,
                subresource="log",
                label_selector=None,
                field_selector=None,
                previous=previous,
            )
        except TransportError as exc:
            return _error_envelope(
                "kubernetes",
                "transport_error",
                str(exc),
                source_name=pod,
                namespace=namespace,
                previous=previous,
            )
        backend_error = _k8s_backend_error_or(
            resp, source_name=pod, namespace=namespace, previous=previous
        )
        if backend_error is not None:
            return backend_error
        body = str(resp.get("log") or "")
        lines = _to_json_list(ln for ln in body.splitlines() if ln)
        return {
            "source_type": "kubernetes",
            "source_name": pod,
            "namespace": namespace,
            "previous": previous,
            "lines": lines,
        }

    def k8s_get_events(self, *, namespace: str, field_selector: str | None) -> RawOutput:
        try:
            resp = self._transport.read_k8s(
                namespace=namespace,
                kind="events",
                name=None,
                subresource=None,
                label_selector=None,
                field_selector=field_selector,
                previous=False,
            )
        except TransportError as exc:
            return _error_envelope(
                "kubernetes",
                "transport_error",
                str(exc),
                source_name=namespace,
                field_selector=field_selector,
            )
        backend_error = _k8s_backend_error_or(
            resp, source_name=namespace, field_selector=field_selector
        )
        if backend_error is not None:
            return backend_error
        events = _to_json_list(
            {
                "type": e.get("type"),
                "reason": e.get("reason"),
                "message": e.get("message"),
                "count": e.get("count", 1),
            }
            for e in _as_mapping_list(resp.get("items"))
        )
        return {
            "source_type": "kubernetes",
            "source_name": namespace,
            "field_selector": field_selector,
            "events": events,
        }


class QdrantAdapter:
    """Qdrant read adapter — top-K playbook search (1 of the 8 port methods). Search/query only."""

    def __init__(self, transport: ReadOnlyTransport) -> None:
        self._transport = transport

    def search_playbook(self, *, query: str, top_k: int) -> RawOutput:
        try:
            resp = self._transport.read_qdrant(query=query, top_k=top_k)
        except TransportError as exc:
            return _error_envelope(
                "playbook", "transport_error", str(exc), query=query, top_k=top_k
            )
        if "error" in resp:
            return _error_envelope(
                "playbook",
                "backend_error",
                str(resp.get("error")),
                query=query,
                top_k=top_k,
            )

        def _hit(h: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
            payload = h.get("payload")
            title: JsonValue = payload.get("title") if isinstance(payload, Mapping) else None
            return {"id": h.get("id"), "score": h.get("score"), "title": title}

        hits = _to_json_list(_hit(h) for h in _as_mapping_list(resp.get("result")))
        return {
            "source_type": "playbook",
            "query": query,
            "top_k": top_k,
            "hits": hits,
        }


class TopologyAdapter:
    """Topology read adapter — service/dependency relations (1 of the 8 port methods)."""

    def __init__(self, transport: ReadOnlyTransport) -> None:
        self._transport = transport

    def topology_read(self, *, service: str | None) -> RawOutput:
        try:
            resp = self._transport.read_topology(service=service)
        except TransportError as exc:
            return _error_envelope("topology", "transport_error", str(exc), service=service)
        if "error" in resp:
            return _error_envelope(
                "topology",
                "backend_error",
                str(resp.get("error")),
                service=service,
            )
        services = _as_json_list(resp.get("services"))
        return {
            "source_type": "topology",
            "service": service,
            "services": services,
            "dependencies": _as_json_list(resp.get("dependencies")),
        }


class CompositeReadOnlyAdapter:
    """Composite of the 5 source adapters — implements the FULL ``ReadOnlyAdapterPort`` (8 methods).

    This is the object a tool receives. It satisfies ``ReadOnlyAdapterPort`` (runtime_checkable
    ``isinstance``) because it exposes all 8 read methods with matching keyword signatures. It holds
    ONE transport (the I/O seam) shared by the 5 delegates — Story 3.5 / app composition injects a
    concrete transport here (real = Epic 7; fake = 2-2 tests).
    """

    def __init__(self, transport: ReadOnlyTransport) -> None:
        self._prometheus = PrometheusAdapter(transport)
        self._loki = LokiAdapter(transport)
        self._k8s = K8sAdapter(transport)
        self._qdrant = QdrantAdapter(transport)
        self._topology = TopologyAdapter(transport)

    def query_promql(self, *, query: str, time_window: TimeWindow) -> RawOutput:
        return self._prometheus.query_promql(query=query, time_window=time_window)

    def query_loki(
        self,
        *,
        service: str,
        time_window: TimeWindow,
        correlation_id: str | None,
    ) -> RawOutput:
        return self._loki.query_loki(
            service=service, time_window=time_window, correlation_id=correlation_id
        )

    def k8s_get(self, *, namespace: str, label_selector: str | None) -> RawOutput:
        return self._k8s.k8s_get(namespace=namespace, label_selector=label_selector)

    def k8s_describe(self, *, namespace: str, pod: str) -> RawOutput:
        return self._k8s.k8s_describe(namespace=namespace, pod=pod)

    def k8s_logs(self, *, namespace: str, pod: str, previous: bool) -> RawOutput:
        return self._k8s.k8s_logs(namespace=namespace, pod=pod, previous=previous)

    def k8s_get_events(self, *, namespace: str, field_selector: str | None) -> RawOutput:
        return self._k8s.k8s_get_events(namespace=namespace, field_selector=field_selector)

    def search_playbook(self, *, query: str, top_k: int) -> RawOutput:
        return self._qdrant.search_playbook(query=query, top_k=top_k)

    def topology_read(self, *, service: str | None) -> RawOutput:
        return self._topology.topology_read(service=service)


__all__ = [
    "CompositeReadOnlyAdapter",
    "K8sAdapter",
    "LokiAdapter",
    "PrometheusAdapter",
    "QdrantAdapter",
    "TopologyAdapter",
]
