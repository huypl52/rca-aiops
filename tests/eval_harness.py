"""tests/eval_harness — inject → Evidence pipeline for the Story-6.1 benchmark (NOT a pytest test).

This module has NO ``test_`` prefix → pytest does NOT collect it. It is the ONE place that imports
``adapters`` + ``graph`` for the eval benchmark: it drives a scenario's canned inject through a REAL
:class:`~adapters.readonly.CompositeReadOnlyAdapter` (the real 8-method adapter, holding the 5 real
source adapters) → ``RawOutput`` s → the REAL :func:`~graph.nodes.evidence_normalizer.build_evidence_normalizer`
→ tiered ``Evidence`` (9 §3.6 fields, Pydantic-validated AT THE PORT — AD-9). NO synthesized
evidence — the Epic-4 K2 / B1 real-stub discipline: the canned inject models the REAL backend wire
shapes and the real normalization is genuinely exercised offline.

Why this lives in ``tests/`` (NOT ``eval/``): ``eval/`` is import-restricted to ``ci.contract_schema``
+ stdlib (it is pure DATA). Routing the inject through the real adapter + normalizer REQUIRES
importing ``adapters`` + ``graph`` — so that orchestration lives here, where any import is allowed.

Used by:
  - ``tests/test_eval_benchmark_scenarios.py`` (in-process: AC1 routability + gate#5 contract +
    AC2 marking).
  - ``tests/ci/test_gate6_benchmark_determinism.py`` (the decisive cross-``PYTHONHASHSEED`` test —
    spawns this module via ``python -m tests.eval_harness`` under several hash seeds and asserts the
    emitted symptom blob is byte-identical; the ``EVAL_GATE6_NEGATIVE`` env hook deliberately makes
    the blob hash-seed-dependent so the negative test proves the assertion has teeth).

Deterministic (AD-12 / NFR-Determinism): no wall-clock, no ``random``, no network, no filesystem
mutation, no ``hash()`` on strings. The symptom is canonical JSON (``sort_keys=True``) → same inject
→ byte-identical symptom regardless of ``PYTHONHASHSEED``.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, cast

from adapters.readonly import CompositeReadOnlyAdapter
from adapters.transport import ReadOnlyTransport
from eval.scenarios import BENCHMARK_SCENARIOS
from eval.schema import Scenario
from graph.nodes.evidence_normalizer import build_evidence_normalizer
from graph.state import InvestigationState

# This module intentionally imports adapters + graph (the eval→adapter routing the eval/ data layer
# is forbidden from doing). eval/ stays import-pure (ci.contract_schema + stdlib).


# The incident window every scenario's non-windowed evidence (k8s) falls back to (context["time_window"]
# — the evidence_normalizer's LOCKED precedence). Fixed ISO-8601 UTC strings (AD-12: no wall-clock).
_TIME_WINDOW: dict[str, str] = {"start": "2026-06-24T10:00:00Z", "end": "2026-06-24T10:05:00Z"}


class ScenarioTransport:
    """Canned ``ReadOnlyTransport`` — returns a scenario's inject responses at the wire seam.

    Implements the 5 ``read_*`` methods (structurally satisfies ``ReadOnlyTransport``) by indexing the
    scenario's inject: prometheus / loki / qdrant / topology by source; kubernetes by the
    ``(kind, name, subresource)`` triple (the SAME branch logic ``FakeReadOnlyTransport.read_k8s``
    uses — list pods / read a pod / read a pod log / list events). The harness casts this to
    ``ReadOnlyTransport`` when wiring the real ``CompositeReadOnlyAdapter`` (honest cast: it
    structurally conforms; the canned responses are plain JSON-safe dicts — AD-9).
    """

    def __init__(self, inject: Any) -> None:
        self._prom: Any = None
        self._loki: Any = None
        self._qdrant: Any = None
        self._topo: Any = None
        self._k8s: dict[tuple[str, Any, Any], Any] = {}
        for call in inject:
            method = call.adapter_method
            if method == "query_promql":
                self._prom = call.response
            elif method == "query_loki":
                self._loki = call.response
            elif method == "search_playbook":
                self._qdrant = call.response
            elif method == "topology_read":
                self._topo = call.response
            elif method == "k8s_get":
                self._k8s[("pods", None, None)] = call.response
            elif method == "k8s_get_events":
                self._k8s[("events", None, None)] = call.response
            elif method == "k8s_describe":
                self._k8s[("pods", call.kwargs.get("pod"), None)] = call.response
            elif method == "k8s_logs":
                self._k8s[("pods", call.kwargs.get("pod"), "log")] = call.response

    def read_prometheus(self, *, query: str, time_window: Any) -> Any:
        del query, time_window
        return self._prom

    def read_loki(self, *, service: str, time_window: Any, correlation_id: Any) -> Any:
        del service, time_window, correlation_id
        return self._loki

    def read_k8s(
        self,
        *,
        namespace: str,
        kind: str,
        name: Any,
        subresource: Any,
        label_selector: Any,
        field_selector: Any,
        previous: bool,
    ) -> Any:
        del namespace, label_selector, field_selector, previous
        return self._k8s.get((kind, name, subresource))

    def read_qdrant(self, *, query: str, top_k: int) -> Any:
        del query, top_k
        return self._qdrant

    def read_topology(self, *, service: Any) -> Any:
        del service
        return self._topo


def build_adapter(scenario: Scenario) -> CompositeReadOnlyAdapter:
    """Wire the real composite adapter over a ``ScenarioTransport`` seeded by ``scenario.inject``."""
    transport = ScenarioTransport(scenario.inject)
    return CompositeReadOnlyAdapter(cast("ReadOnlyTransport", transport))


def _record_query(adapter_method: str, kwargs: Any) -> str:
    """The canonical 'what was asked' string for a tool_call record (the evidence_normalizer ``query``).

    ``query`` MUST be a non-empty str or the normalizer DROPS the candidate (AC4). PromQL carries a
    real ``query``; the non-PromQL tools fall back to their identifying kwargs (service / namespace /
    pod). Always derived from the inject kwargs — deterministic (AD-12).
    """
    query = kwargs.get("query")
    if isinstance(query, str) and query:
        return query
    service = kwargs.get("service")
    if isinstance(service, str) and service:
        return f"{adapter_method}:{service}"
    namespace = kwargs.get("namespace")
    if isinstance(namespace, str) and namespace:
        return f"{adapter_method}:{namespace}"
    return adapter_method


def drive_raws(scenario: Scenario) -> list[dict[str, object]]:
    """Drive the scenario's inject through the REAL adapter → the ``RawOutput`` per call (Epic-4 K2)."""
    adapter = build_adapter(scenario)
    raws: list[dict[str, object]] = []
    for call in scenario.inject:
        method = getattr(adapter, call.adapter_method)
        raw = method(**dict(call.kwargs))
        raws.append(dict(raw))
    return raws


def drive_evidence(scenario: Scenario) -> list[dict[str, object]]:
    """Drive the inject → REAL adapter → REAL evidence_normalizer → tiered ``Evidence`` dicts.

    Builds the minimal ``InvestigationState`` the normalizer reads: ``context`` (``service`` for the
    prometheus source-name fallback + ``time_window`` for the non-windowed k8s tools) +
    ``tool_calls`` (one record per inject call: ``{tool, query, raw}``). The normalizer validates each
    candidate AT THE PORT (``Evidence.model_validate`` — AD-9; ``extra="forbid"``) + drops any record
    missing a REQUIRED field (AC4 — never guesses). Returns the surviving ``Evidence.model_dump``
    dicts (9 §3.6 fields each, non-null ``raw_excerpt`` — AD-6).
    """
    raws = drive_raws(scenario)
    tool_calls: list[dict[str, object]] = []
    for call, raw in zip(scenario.inject, raws, strict=True):
        tool_calls.append(
            {
                "tool": call.adapter_method,
                "query": _record_query(call.adapter_method, call.kwargs),
                "timestamp_range": "dedupe",  # canonical-JSON dedupe string (the normalizer ignores it)
                "raw": raw,
            }
        )
    state = cast(
        InvestigationState,
        {
            "context": {"service": scenario.service, "time_window": dict(_TIME_WINDOW)},
            "tool_calls": tool_calls,
        },
    )
    node = build_evidence_normalizer()
    out = node(state)
    evidence = out.get("evidence")
    if not isinstance(evidence, list):
        return []
    # Each survivor is an Evidence.model_dump() dict (the normalizer appends only validated dicts);
    # cast narrows JsonValue → dict[str, object] so the invariance of dict-value types holds under
    # strict mypy (dict[str, JsonValue] is not assignable to dict[str, object] without the cast).
    return [dict(cast("dict[str, object]", e)) for e in evidence]


def scenario_symptom(scenario: Scenario) -> str:
    """Canonical-JSON symptom of a scenario's routable Evidence (gate#6 determinism unit).

    Deterministic + PYTHONHASHSEED-safe: canonical JSON (``sort_keys=True``) over the Evidence list
    (the normalizer's dedupe key is canonical-JSON, so the survivor set + order are hash-seed-stable).
    Same inject → byte-identical symptom (AD-12 / NFR-Determinism).
    """
    evidence = drive_evidence(scenario)
    return json.dumps(evidence, sort_keys=True, separators=(",", ":"), default=str)


def symptom_blob() -> str:
    """Canonical-JSON ``{scenario_name: symptom}`` for ALL 11 scenarios (the gate#6 subprocess output)."""
    blob: dict[str, str] = {s.name: scenario_symptom(s) for s in BENCHMARK_SCENARIOS}
    if os.environ.get("EVAL_GATE6_NEGATIVE"):
        # DELIBERATELY non-deterministic: set-iteration order varies by PYTHONHASHSEED → the blob
        # differs across seeds. The gate#6 negative test asserts this DIFFERS (proving the
        # determinism assertion has teeth — it is not a tautological always-pass).
        blob["__set_order__"] = ",".join(set(s.name for s in BENCHMARK_SCENARIOS))
    return json.dumps(blob, sort_keys=True, separators=(",", ":"))


def _main() -> int:
    """CLI entry (``python -m tests.eval_harness``): print the symptom blob to stdout."""
    sys.stdout.write(symptom_blob())
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
