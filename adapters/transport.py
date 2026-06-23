"""Injectable read-only TRANSPORT seam — the actual external read call per source (AD-2 PORT / AC3).

Story 2.2 — AD-3 (read-only boundary) / AD-2 (port seam) / AD-12 (determinism) / AD-9 (JSON-safe).

The 5 source adapters in ``adapters/readonly.py`` do NOT talk to any backend directly. Each holds an
injectable ``ReadOnlyTransport`` and calls ONE of its 5 read methods. The transport is the single
I/O seam:

  - **2-2 ships a deterministic ``FakeReadOnlyTransport``** here (offline, pure — AD-12). The fake
    models the REAL backend response shapes (Prometheus HTTP API vector/matrix, Loki ``streams``,
    Kubernetes REST list/read, Qdrant ``result`` hits, a topology graph) so the adapters' real
    normalization logic (backend shape → tool ``RawOutput``) is genuinely exercised offline.
  - **Epic 7 (7-1/7-2/7-4) wires the REAL transport** — a single implementation built on the real
    standard clients (httpx for the Prometheus/Loki/K8s HTTP APIs, qdrant-client for Qdrant) issuing
    READ verbs only (GET; query-only) — against the live observability stack + integration tests.

This mirrors the PORT-seam pattern from Story 1-4 (``GraphRunner`` + ``StubGraphRunner``) and
Story 2-1 (``ReadOnlyAdapterPort`` + ``StubReadOnlyAdapter``): ship the real shape/logic now, test
offline via the injected seam, plug the live backend later WITHOUT changing the contract.

Seam CONTRACT (the only thing an adapter assumes about a transport): each read method returns the
raw backend response as a plain ``Mapping[str, JsonValue]`` (JSON-safe — AD-9), OR raises
``TransportError``. A real transport (Epic 7) is responsible for translating its client's native
exceptions (HTTP error, timeout, connection refused, empty) into ``TransportError`` so the adapter's
error handling stays deterministic + testable. A backend that returns an ERROR response (e.g.
Prometheus/Loki ``status == "error"``, a Kubernetes ``kind == "Status"`` failure, Qdrant/topology
``"error"`` payload) is NOT a transport failure — it is a normal response the adapter folds into a
structured error envelope (AC3), so the two failure modes are independently testable.

ONE-WAY (AD-1 / gate #2): imports ``tools.port`` (FORWARD edge — tools idx4, adapters idx3, allowed)
+ stdlib only. NEVER imports ``graph``/``services``/``routers`` (back-edge forbidden).

Read-only (AD-3): every method here is a read/query. No deny-verb name; no mutating call. A real
transport MUST use read verbs only (GET for the HTTP APIs; list/read semantics for K8s REST;
query-only for Qdrant) — enforced + leader-grep'd in ``adapters/readonly.py``'s contract tests.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from tools.port import JsonValue, TimeWindow

# ONE-WAY (AD-1 / gate #2): tools.port (forward edge, allowed) + stdlib only.
# NEVER imports routers/services/graph (back-edge forbidden).

# Re-exported so a real transport (Epic 7) + tests can catch the seam's error type without importing
# the adapter layer.
RawBackendResponse = Mapping[str, JsonValue]
"""The raw backend response a transport returns (the wire shape, JSON-safe — AD-9). NOT the tool
``RawOutput``: the source adapter normalizes this into the tool ``RawOutput`` shape (stub-aligned)."""


class TransportError(Exception):
    """Transport-seam failure (network / timeout / refused / malformed wire response).

    Raised by a transport's read method when the external call itself fails. Adapters catch this and
    fold it into a structured ``RawOutput`` error envelope (AC3 — never an uncaught exception into
    the graph). A backend ERROR response is NOT a ``TransportError`` (it is a normal response) — the
    adapter detects + envelopes it separately.
    """


@runtime_checkable
class ReadOnlyTransport(Protocol):
    """PORT — one read method per source (the I/O seam; 5 sources, all read-only).

    Each method returns the raw backend response (``RawBackendResponse``) or raises
    ``TransportError``. Real impl = Epic 7; 2-2 ships ``FakeReadOnlyTransport`` for offline tests.
    Method names are read-only (none is a deny-verb — gate #1 AST exact-match safe).
    """

    def read_prometheus(self, *, query: str, time_window: TimeWindow) -> RawBackendResponse:
        """Read a PromQL diagnostic query from Prometheus (GET /api/v1/query[[_range]]). Read-only."""
        ...

    def read_loki(
        self,
        *,
        service: str,
        time_window: TimeWindow,
        correlation_id: str | None,
    ) -> RawBackendResponse:
        """Read Loki service logs by LogQL selector + range (GET /loki/api/v1/query_range). Read-only."""
        ...

    def read_k8s(
        self,
        *,
        namespace: str,
        kind: str,
        name: str | None,
        subresource: str | None,
        label_selector: str | None,
        field_selector: str | None,
        previous: bool,
    ) -> RawBackendResponse:
        """Read a Kubernetes REST resource — list/read a Pod/Event, read a Pod log (GET only).

        Read-only K8s semantics: ``kind`` selects the resource (``"pods"``/``"events"``), ``name``
        a single object read (else a list), ``subresource == "log"`` reads the Pod log (``previous``
        selects the previous container's log). All list/read — no mutating K8s verb.
        """
        ...

    def read_qdrant(self, *, query: str, top_k: int) -> RawBackendResponse:
        """Read a top-K playbook/playbook-vector search from Qdrant (search/query — read-only)."""
        ...

    def read_topology(self, *, service: str | None) -> RawBackendResponse:
        """Read service/dependency relations from the topology source. Read-only."""
        ...


def _echo_time_window(time_window: TimeWindow) -> dict[str, JsonValue]:
    """Deterministic plain-copy of a time window (AD-9 / mirrors ``tools.port._echo_time_window``).

    The transport echoes the bounded ``timestamp_range`` it received so an adapter can assert the
    time window reached the seam (AC3) without coupling to the real wire encoding (Epic 7).
    """
    return {"start": time_window.get("start"), "end": time_window.get("end")}


class FakeReadOnlyTransport:
    """Deterministic offline transport (AD-12) — models the REAL backend response shapes.

    Pure: no wall-clock, no ``random``, no network, no filesystem mutation, NO ``hash()`` on strings
    (PYTHONHASHSEED randomizes it). Outputs are seeded ONLY by the query args, so same args →
    identical response (and the adapters' normalization is reproducibly exercised).

    Two failure modes (independently configurable, for the AC3 negative tests):
      - ``fail_source`` (one of the 5 source keys): the matching read_* raises ``TransportError``
        (transport-level failure).
      - ``backend_error_source`` (one of the 5 source keys): the matching read_* returns a REALISTIC
        backend ERROR response (backend-level failure) that the adapter folds into an error envelope.
    """

    SOURCES = ("prometheus", "loki", "k8s", "qdrant", "topology")

    def __init__(
        self,
        *,
        fail_source: str | None = None,
        backend_error_source: str | None = None,
    ) -> None:
        self.fail_source = fail_source
        self.backend_error_source = backend_error_source
        # Deterministic call recorder — lets a test assert the time_window reached the seam (AC3)
        # and that read-only params were forwarded. Pure; no external state.
        self.calls: list[tuple[str, dict[str, object]]] = []

    def _record(self, source: str, kwargs: dict[str, object]) -> None:
        self.calls.append((source, dict(kwargs)))

    def read_prometheus(self, *, query: str, time_window: TimeWindow) -> RawBackendResponse:
        self._record("prometheus", {"query": query, "time_window": _echo_time_window(time_window)})
        if self.fail_source == "prometheus":
            raise TransportError("prometheus unreachable (fake)")
        if self.backend_error_source == "prometheus":
            return {"status": "error", "errorType": "bad_data", "error": f"invalid query {query}"}
        # REAL Prometheus HTTP API shape: {"status":"success","data":{"resultType","result":[...]}}.
        return {
            "status": "success",
            "data": {
                "resultType": "vector",
                "result": [
                    {
                        "metric": {"__name__": query, "service": "demo-svc"},
                        "value": [1719216000.0, str(len(query))],
                    }
                ],
            },
        }

    def read_loki(
        self,
        *,
        service: str,
        time_window: TimeWindow,
        correlation_id: str | None,
    ) -> RawBackendResponse:
        self._record(
            "loki",
            {
                "service": service,
                "time_window": _echo_time_window(time_window),
                "correlation_id": correlation_id,
            },
        )
        if self.fail_source == "loki":
            raise TransportError("loki unreachable (fake)")
        if self.backend_error_source == "loki":
            return {"status": "error", "error": "loki query timeout"}
        # REAL Loki query_range shape: {"status":"success","data":{"resultType":"streams","result":[...]}}.
        line = (
            f"log line for {service}"
            if correlation_id is None
            else f"log {correlation_id} for {service}"
        )
        return {
            "status": "success",
            "data": {
                "resultType": "streams",
                "result": [
                    {"stream": {"service": service}, "values": [["1719216000000000000", line]]}
                ],
            },
        }

    def read_k8s(
        self,
        *,
        namespace: str,
        kind: str,
        name: str | None,
        subresource: str | None,
        label_selector: str | None,
        field_selector: str | None,
        previous: bool,
    ) -> RawBackendResponse:
        self._record(
            "k8s",
            {
                "namespace": namespace,
                "kind": kind,
                "name": name,
                "subresource": subresource,
                "label_selector": label_selector,
                "field_selector": field_selector,
                "previous": previous,
            },
        )
        if self.fail_source == "k8s":
            raise TransportError("k8s apiserver unreachable (fake)")
        if self.backend_error_source == "k8s":
            # REAL K8s failure shape: a Status object.
            return {
                "kind": "Status",
                "status": "Failure",
                "message": f"{kind} not found",
                "code": 404,
            }

        if subresource == "log":
            # Pod log: a string body. Wrapped so the response stays a JSON-safe Mapping.
            tag = "previous" if previous else "current"
            return {"log": f"[{tag}] demo line for {name} in {namespace}"}

        if kind == "events":
            # REAL EventList shape, trimmed to the fields the adapter normalizes.
            return {
                "kind": "EventList",
                "items": [
                    {
                        "type": "Warning",
                        "reason": "BackOff",
                        "message": f"back-off in {namespace}",
                        "count": 3,
                        "involvedObject": {"name": f"{namespace}-pod-0"},
                    }
                ],
            }

        if name is None:
            # PodList (list pods).
            return {
                "kind": "PodList",
                "items": [
                    {
                        "metadata": {"name": f"{namespace}-pod-0", "namespace": namespace},
                        "status": {
                            "phase": "Running",
                            "containerStatuses": [
                                {
                                    "name": "app",
                                    "ready": True,
                                    "restartCount": 0,
                                    "state": {"running": {"startedAt": "2026-06-24T00:00:00Z"}},
                                }
                            ],
                        },
                    }
                ],
            }

        # Read a single Pod (describe).
        return {
            "kind": "Pod",
            "metadata": {"name": name, "namespace": namespace},
            "status": {
                "phase": "Running",
                "containerStatuses": [
                    {
                        "name": "app",
                        "ready": True,
                        "restartCount": 0,
                        "state": {"running": {"startedAt": "2026-06-24T00:00:00Z"}},
                        "lastState": {},
                    }
                ],
            },
        }

    def read_qdrant(self, *, query: str, top_k: int) -> RawBackendResponse:
        self._record("qdrant", {"query": query, "top_k": top_k})
        if self.fail_source == "qdrant":
            raise TransportError("qdrant unreachable (fake)")
        if self.backend_error_source == "qdrant":
            return {"error": "qdrant collection missing"}
        # REAL Qdrant search shape: {"result":[{"id","score","payload"}]}.
        n = min(top_k, 3)
        return {
            "result": [
                {
                    "id": i,
                    "score": round(1.0 - (i * 0.1), 2),
                    "payload": {"title": f"playbook {i} for {query}", "source": "demo"},
                }
                for i in range(n)
            ]
        }

    def read_topology(self, *, service: str | None) -> RawBackendResponse:
        svc = service if service is not None else "demo-svc"
        self._record("topology", {"service": svc})
        if self.fail_source == "topology":
            raise TransportError("topology unreachable (fake)")
        if self.backend_error_source == "topology":
            return {"error": "topology empty"}
        return {
            "services": [svc, "downstream"],
            "dependencies": [{"from": svc, "to": "downstream", "type": "calls"}],
        }


__all__ = [
    "FakeReadOnlyTransport",
    "RawBackendResponse",
    "ReadOnlyTransport",
    "TransportError",
]
