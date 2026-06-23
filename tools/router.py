"""executor_router — dispatch logic + dispatch-level dedupe (Story 2.3 / FR-5 / AD-4).

The **thin dispatch layer on top of the read-only registry** (Story 2.1). It is NOT a new tool,
a new adapter, or a new contract — the registry IS the dispatch mechanism. The router does three
things only:

  1. **Dispatch via the registry (AC1).** ``ExecutorRouter.dispatch(tool, **kwargs)`` resolves the
     requested tool to its executor through ``ReadOnlyRegistry.lookup(name)`` (Story 2.1) and invokes
     ``executor(adapter, **kwargs)``. It holds NO shadow executor map. The dispatch set is exactly
     the registered read-only tools (the spec's ``{Prometheus, Loki, K8s, playbook, topology}`` is
     the conceptual source coverage the 10 tools span); the router dispatches at the **tool** level,
     which is registry-native and keeps plan-translation in E3.

  2. **Dispatch-level dedupe by ``(tool, query, timestamp_range)`` (AC2 / AD-4).** A repeated call
     with the same tuple REUSES the prior ``RawOutput`` WITHOUT re-invoking the executor (and signals
     ``deduped=True`` so the graph node in E3 does NOT emit a new ``tool_calls`` record).

  3. **Never crash on bad input (Constraint 5).** Unknown / unregistered tool, or an executor that
     raises on malformed kwargs → a STRUCTURED error ``RawOutput``, never an exception.

**Dedupe layer ownership (report to leader):** the GRAPH layer already owns **state-level**
``tool_calls`` dedupe — ``graph.state.append_dedupe_tool_calls`` keyed on
``(tool, query, timestamp_range)`` (Story 0-3, AD-10). The router owns **dispatch-level** dedupe
only (don't RE-INVOKE; reuse the ``RawOutput``). The two share the SAME key shape
``(tool, query, timestamp_range)`` — the router does NOT reimplement the reducer's job and does NOT
touch ``state.tool_calls`` (graph's concern, node-wired in E3).

**Read-only (AC3 / AD-3):** the router only dispatches registered read-only tools. The registry
already rejects deny-verb names at registration (2-1 defense-in-depth), so a write/exec/probe tool
can never be registered and therefore never dispatched. The router adds NO write path of its own.
(``plan_validator`` in E3 blocks write/exec/probe plans BEFORE the router — that is E3's job; the
router's own guarantee is "I only dispatch what's registered, and nothing registered is a write".)

**RAW passthrough (4.2 boundary held):** the router forwards the executor's RAW dict; it does NOT
construct ``Evidence``. NO ``models`` import here.

ONE-WAY (AD-1 / gate #2): imports ``tools.port`` + ``tools.registry`` (same layer) + stdlib only.
NEVER imports ``routers``/``services``/``graph``/``adapters`` (back-edge forbidden). The dedupe key
shape is defined LOCALLY here (NOT imported from ``graph.state``) to keep the one-way boundary.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass

from tools.port import JsonValue, RawOutput, ReadOnlyAdapterPort
from tools.registry import ReadOnlyRegistry

# ONE-WAY (AD-1 / gate #2): tools.port + tools.registry (same layer) + stdlib only.
# NEVER imports routers/services/graph/adapters (back-edge forbidden).
# The dedupe key shape is DEFINED HERE (not imported from graph.state) — see _dedupe_key.

# The dispatch-level dedupe identity tuple (AC2 / AD-4). Matches the state-level reducer's key
# shape ``(_dedupe_key_tool_calls)`` in graph/state.py (Story 0-3): (tool, query, timestamp_range).
# Kept as a plain tuple[str, str, str] — all string components so it is hashable + deterministic
# (sorted JSON keys; no wall-clock/random/hash() on strings stored in output — AD-12).
type DedupeKey = tuple[str, str, str]


@dataclass(frozen=True)
class DispatchResult:
    """Outcome of a single ``executor_router`` dispatch.

    Attributes:
        tool: the requested tool name.
        raw: the executor's RAW JSON-safe output (forwarded, NOT Evidence — 4.2 boundary held).
            On an error (unknown tool / executor raise) this is a STRUCTURED error envelope, never
            absent — the router never raises into the caller (Constraint 5).
        deduped: True iff this tuple was a cache HIT — the executor was NOT re-invoked and the prior
            ``raw`` was reused. The graph node (E3) uses this to SKIP appending a new ``tool_calls``
            record (AC2: "KHÔNG tạo tool_calls mới").
        dispatched: True iff the executor was actually invoked this call (fresh dispatch). False on
            a cache hit OR an error (unknown tool / raise before invocation).
        key: the ``(tool, query, timestamp_range)`` dedupe key used (AC2 / AD-10 shape).
    """

    tool: str
    raw: RawOutput
    deduped: bool
    dispatched: bool
    key: DedupeKey


def _canonical(value: object) -> str:
    """Deterministic JSON serialization of a request component for the dedupe key (AD-12).

    Sorted keys + ``ensure_ascii=False`` so the same logical value ALWAYS serializes identically.
    No ``hash()`` on strings (PYTHONHASHSEED randomizes it) — the string IS the key. ``default=str``
    is a safety net only; request args are JSON-safe per AD-9 (the executors take JSON-safe kwargs).
    """
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


def _dedupe_key(tool: str, kwargs: Mapping[str, object]) -> DedupeKey:
    """The dispatch-level dedupe identity ``(tool, query, timestamp_range)`` (AC2 / AD-10).

    Same SHAPE as the state-level reducer key in ``graph.state._dedupe_key_tool_calls`` — the router
    does NOT import that (one-way boundary) but mirrors the tuple so the two layers stay aligned.

    - ``tool``: the requested tool name.
    - ``query``: the canonical JSON of the request's IDENTIFYING kwargs — everything EXCEPT
      ``time_window`` (the ``time_window`` kwarg IS the ``timestamp_range`` component). This
      generalizes the spec's "query" to every tool's identifying arguments (executors have varied
      kwargs — ``query`` / ``service`` / ``namespace`` / ``pod`` / ``metric`` / ... — only
      ``query_prometheus_raw`` has a literal ``query`` param; canonicalizing all non-time kwargs is
      the registry-native, deterministic identity).
    - ``timestamp_range``: the canonical JSON of the ``time_window`` kwarg (``None`` when the tool
      is not time-windowed, e.g. ``topology_executor`` / ``search_playbook``).
    """
    timestamp_range = kwargs.get("time_window")
    identifying = {k: v for k, v in kwargs.items() if k != "time_window"}
    return (tool, _canonical(identifying), _canonical(timestamp_range))


def _error_envelope(tool: str, code: str, detail: str) -> RawOutput:
    """Structured RAW error envelope for a dispatch failure (never raises — Constraint 5).

    Mirrors the adapter error-envelope shape from Story 2.2 (``{"source_type", "error": {...}}``)
    so the downstream normalizer (4.2) treats router failures uniformly with source failures. The
    router returns this as the ``raw`` of a ``DispatchResult`` instead of raising into the caller.
    """
    error: dict[str, JsonValue] = {"code": code, "detail": detail, "tool": tool}
    return {"source_type": "router", "error": error}


class ExecutorRouter:
    """Dispatch read-only tool calls through the registry + reuse on dedupe (AC1 / AC2 / AC3).

    Holds a reference to a ``ReadOnlyRegistry`` (the dispatch mechanism — NO shadow executor map)
    and a ``ReadOnlyAdapterPort`` (the same dependency the executors take). The dedupe cache maps
    a ``(tool, query, timestamp_range)`` key → the executor's cached ``RawOutput``; a repeated key
    is a cache HIT (no re-invoke, ``deduped=True``).

    The cache is per-router-instance (per investigation run in E3). It is deterministic: same
    sequence of dispatches → same sequence of results, regardless of ``PYTHONHASHSEED`` (dict lookup
    is by equality; no ``hash()`` values are stored in output — AD-12).
    """

    def __init__(self, registry: ReadOnlyRegistry, adapter: ReadOnlyAdapterPort) -> None:
        self._registry = registry
        self._adapter = adapter
        self._cache: dict[DedupeKey, RawOutput] = {}

    def dispatch(self, *, tool: str, **kwargs: object) -> DispatchResult:
        """Dispatch ``tool`` with ``kwargs`` through the registry; reuse on dedupe (AC1 / AC2).

        AC1: resolves the executor via ``registry.lookup(tool)`` and invokes
        ``executor(adapter, **kwargs)`` — the registry IS the dispatch mechanism (no shadow map).
        AC2: a repeated ``(tool, query, timestamp_range)`` tuple is a cache HIT — the executor is
        NOT re-invoked, the prior ``RawOutput`` is reused, and ``deduped=True`` (so E3 skips the
        new ``tool_calls`` record).
        AC3 / Constraint 5: unknown tool, or an executor that raises on malformed kwargs → a
        STRUCTURED error ``RawOutput`` (``dispatched=False``), never an exception.
        """
        key = _dedupe_key(tool, kwargs)

        # AC2 — cache hit: reuse the prior RawOutput, do NOT re-invoke, no new tool_call.
        cached = self._cache.get(key)
        if cached is not None:
            return DispatchResult(tool=tool, raw=cached, deduped=True, dispatched=False, key=key)

        # AC1 — dispatch via the registry (no shadow map). Unknown tool → structured error, no crash.
        if tool not in self._registry:
            return DispatchResult(
                tool=tool,
                raw=_error_envelope(tool, "unknown_tool", f"tool '{tool}' is not registered."),
                deduped=False,
                dispatched=False,
                key=key,
            )
        executor = self._registry.lookup(tool)

        # Constraint 5 — never raise into the caller: an executor that throws on bad kwargs is
        # folded into a structured error envelope (defensive; executors normally return dicts).
        try:
            raw = executor(self._adapter, **kwargs)
        except Exception as exc:  # noqa: BLE001 — fold ANY executor failure into an envelope
            return DispatchResult(
                tool=tool,
                raw=_error_envelope(tool, "executor_error", f"{type(exc).__name__}: {exc}"),
                deduped=False,
                dispatched=False,
                key=key,
            )

        # Cache the fresh dispatch result so an identical later call reuses it (AC2).
        self._cache[key] = raw
        return DispatchResult(tool=tool, raw=raw, deduped=False, dispatched=True, key=key)

    def cache_size(self) -> int:
        """Number of distinct dispatched tuples currently cached (test/observability only)."""
        return len(self._cache)


__all__ = [
    "DedupeKey",
    "DispatchResult",
    "ExecutorRouter",
]
