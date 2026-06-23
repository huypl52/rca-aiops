"""ReadOnlyAdapterPort — the adapter PORT seam between read-only tools and external clients.

Story 2.1 — AD-3 (BLOCKER read-only boundary) / AD-2 (port contract) / AD-12 (determinism) /
AD-9 (JSON-safe).

AD-2 / AD-1: the 10 read-only tools (``tools.executors``) call external sources ONLY through
this **port**. The port is a ``Protocol``; concrete adapter clients (Prometheus / Loki / K8s API
/ Qdrant / topology HTTP clients) are **dependency-injected**. Tools NEVER import a concrete
client — they only know the Protocol.

Story 2.1 ships a **deterministic STUB** adapter (``StubReadOnlyAdapter``) so the 10 tools are
callable + testable now, offline. **Story 2.2 plugs the real clients** — implementing the SAME
``ReadOnlyAdapterPort`` Protocol — **WITHOUT touching ``tools/``**. That swap is the
load-bearing seam the leader DEEP-reviews (2-2 plugs real clients while ``tools/`` is unchanged).
This mirrors the ``GraphRunner`` PORT in ``graph/runner.py`` (Story 1.4), where the port lives in
the graph layer so both the dispatcher and the compiled graph can depend on it without a back-edge.

Why this PORT lives in the ``tools`` layer (NOT ``adapters``): the import-linter ``layers``
contract (pyproject.toml) is the one-way chain
``routers → services → graph → adapters → tools``. ``tools`` is the LAST layer — it MAY NOT import
any earlier layer, **including ``adapters``**. The only layer ``tools`` can depend on is itself, so
the port (which tools must import) lives here. The concrete adapters (2-2) live in ``adapters/``
(index 3) and may import this Protocol from ``tools/`` (later index) with no back-edge.

ONE-WAY (AD-1 / gate #2): imports ``ci.denyset``-free stdlib only here. NEVER imports
``routers``/``services``/``graph``/``adapters`` (back-edge forbidden).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol, runtime_checkable

# JSON-safe recursive value alias — tools-LOCAL (tools CANNOT import ``graph.state.JsonValue``;
# that would be a back-edge under gate #2). Plain ``dict`` of these is a tool's RAW output (AD-9).
type JsonValue = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
type RawOutput = dict[str, JsonValue]
type TimeWindow = Mapping[str, str | None]
"""Evidence time window passed through to adapters as a plain {start, end?} mapping (ISO-8601 UTC).
Reuses the spec §3.6 ``timestamp_range`` shape; tools/adapter do NOT construct ``TimestampRange``
models here — that normalization is Story 4.2 (Evidence boundary held)."""

type ToolExecutor = Callable[..., RawOutput]
"""A read-only executor stored in the registry: callable returning RAW JSON-safe output (AD-9).
``Callable[..., ...]`` because the 10 executors have varied keyword signatures; the registry stores
them by name and ``lookup`` returns the opaque callable for the caller to invoke."""

# ONE-WAY (AD-1 / gate #2): stdlib only here.
# NEVER imports routers/services/graph/adapters (back-edge forbidden) — this is the port BOTH the
# tools (this layer) and the concrete adapters (adapters/, 2-2) depend on.


def _echo_time_window(time_window: TimeWindow) -> dict[str, JsonValue]:
    """Deterministic plain-copy of a time window for JSON-safe stub output (AD-9).

    Pure mapping projection — no clock, no mutation of the input. ``end`` stays ``None`` while the
    incident is still firing (matches the ``TimestampRange.end`` nullable contract). Returns a
    ``JsonValue`` dict so it nests cleanly inside a tool's ``RawOutput``.
    """
    return {
        "start": time_window.get("start"),
        "end": time_window.get("end"),
    }


@runtime_checkable
class ReadOnlyAdapterPort(Protocol):
    """PORT — read-only external adapter methods the 10 tools need (AD-3 / AD-2).

    Story 2.1 ships a deterministic stub (``StubReadOnlyAdapter``); Story 2.2 plugs the real
    clients via the SAME method set — ``tools/`` is UNCHANGED (AC5). Every method is a
    **read/query** only; there is intentionally NO write/exec/patch/delete/scale/rollback/
    restart/remediate method on this port (read-only boundary §3.8, enforced statically by CI
    gate #1). Method NAMES are all read-only — none equals a deny-verb (gate #1 AST exact-match
    safe).
    """

    def query_promql(self, *, query: str, time_window: TimeWindow) -> RawOutput:
        """Run a diagnostic PromQL query (Prometheus). Read-only."""
        ...

    def query_loki(
        self,
        *,
        service: str,
        time_window: TimeWindow,
        correlation_id: str | None,
    ) -> RawOutput:
        """Query Loki logs by service / time window / correlation id. Read-only."""
        ...

    def k8s_get(self, *, namespace: str, label_selector: str | None) -> RawOutput:
        """List pods in a namespace (phase, readiness, restart count, container state). Read-only."""
        ...

    def k8s_describe(self, *, namespace: str, pod: str) -> RawOutput:
        """Describe a pod (termination reason, container state). Read-only."""
        ...

    def k8s_logs(self, *, namespace: str, pod: str, previous: bool) -> RawOutput:
        """Read current/previous pod logs. Read-only."""
        ...

    def k8s_get_events(self, *, namespace: str, field_selector: str | None) -> RawOutput:
        """Read namespace/object events. Read-only."""
        ...

    def search_playbook(self, *, query: str, top_k: int) -> RawOutput:
        """Search playbook/runbook (Qdrant / local Markdown). Read-only."""
        ...

    def topology_read(self, *, service: str | None) -> RawOutput:
        """Read service/dependency relations (topology). Read-only."""
        ...


class StubReadOnlyAdapter:
    """Deterministic default adapter — pure data return (AD-12).

    Implements the ``ReadOnlyAdapterPort`` Protocol structurally with FIXED data seeded ONLY by
    the query args (no wall-clock, no ``random``, no network, no filesystem mutation; NO
    ``hash()`` on strings — PYTHONHASHSEED randomizes it). The output echoes the request so each
    tool's RAW output is reproducible and ``json.dumps`` round-trips (AD-9). This is the
    Story-2.1 default; Story 2.2 swaps it for real clients via the same Protocol (``tools/``
    unchanged).
    """

    def query_promql(self, *, query: str, time_window: TimeWindow) -> RawOutput:
        # Deterministic "value" seeded by the query length only (no random, no clock).
        return {
            "source_type": "prometheus",
            "query": query,
            "time_window": _echo_time_window(time_window),
            "result_type": "vector",
            "result": [{"metric": {"__name__": query}, "value": [0.0, str(len(query))]}],
        }

    def query_loki(
        self,
        *,
        service: str,
        time_window: TimeWindow,
        correlation_id: str | None,
    ) -> RawOutput:
        return {
            "source_type": "loki",
            "source_name": service,
            "time_window": _echo_time_window(time_window),
            "correlation_id": correlation_id,
            "streams": [
                {"labels": {"service": service}, "values": [["0", f"stub log line for {service}"]]}
            ],
        }

    def k8s_get(self, *, namespace: str, label_selector: str | None) -> RawOutput:
        return {
            "source_type": "kubernetes",
            "source_name": namespace,
            "label_selector": label_selector,
            "pods": [
                {
                    "name": f"{namespace}-pod-0",
                    "phase": "Running",
                    "ready": True,
                    "restart_count": 0,
                    "container_state": {"running": {}},
                }
            ],
        }

    def k8s_describe(self, *, namespace: str, pod: str) -> RawOutput:
        return {
            "source_type": "kubernetes",
            "source_name": pod,
            "namespace": namespace,
            "describe": {
                "phase": "Running",
                "termination_reason": None,
                "container_state": {"running": {}},
            },
        }

    def k8s_logs(self, *, namespace: str, pod: str, previous: bool) -> RawOutput:
        return {
            "source_type": "kubernetes",
            "source_name": pod,
            "namespace": namespace,
            "previous": previous,
            "lines": [f"stub log line for {pod} (previous={previous})"],
        }

    def k8s_get_events(self, *, namespace: str, field_selector: str | None) -> RawOutput:
        return {
            "source_type": "kubernetes",
            "source_name": namespace,
            "field_selector": field_selector,
            "events": [
                {
                    "type": "Normal",
                    "reason": "Pulled",
                    "message": f"stub event in {namespace}",
                    "count": 1,
                }
            ],
        }

    def search_playbook(self, *, query: str, top_k: int) -> RawOutput:
        return {
            "source_type": "playbook",
            "query": query,
            "top_k": top_k,
            "hits": [
                {
                    "id": f"playbook-{i}",
                    "score": round(1.0 - (i * 0.1), 2),
                    "title": f"stub playbook {i} for {query}",
                }
                for i in range(min(top_k, 3))
            ],
        }

    def topology_read(self, *, service: str | None) -> RawOutput:
        svc = service if service is not None else "all"
        return {
            "source_type": "topology",
            "service": svc,
            "services": [svc],
            "dependencies": [{"from": svc, "to": "downstream", "type": "calls"}],
        }


__all__ = [
    "JsonValue",
    "ReadOnlyAdapterPort",
    "RawOutput",
    "StubReadOnlyAdapter",
    "TimeWindow",
    "ToolExecutor",
]
