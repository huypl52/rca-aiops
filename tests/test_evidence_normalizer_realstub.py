"""REAL-stub integration regression guard for the ENV node (Story 4.2 — BLOCKER B1).

This is the test that BLOCKER B1 slipped through: it feeds the **8 REAL ``StubReadOnlyAdapter`` outputs**
(``tools/port.py``) through ENV (wrapped as §3.5 EXR tool_call records) and asserts **8/8 produce valid
tiered Evidence**. The 6 non-windowed tools (k8s_get / k8s_describe / k8s_logs / k8s_get_events /
search_playbook / topology_read) carry NO ``raw["time_window"]`` — they survive ONLY via the
``state.context["time_window"]`` incident-window fallback. Before the B1 fix, ENV silently dropped 6/8.

Why a SEPARATE file from ``test_evidence_normalizer.py``: that suite uses SYNTHETIC fixtures (which
masked B1 by hand-injecting time_window). This file builds records from the REAL adapter so a future
change that re-drops a tool type is caught here regardless of what the synthetic-fixture suite assumes.

AD-1 note: importing ``tools.port`` here is fine — tests are CONSUMERS, not a contracted layer (the
import-linter ``layers`` contract governs production modules, not tests; ``tests/`` is outside
``root_packages``). ENV itself imports NO tools (read-only — it normalizes already-collected raw).
"""

from __future__ import annotations

from typing import cast

from graph.nodes.evidence_normalizer import build_evidence_normalizer
from graph.state import InvestigationState, JsonValue, create_initial_state
from models.evidence import Evidence
from tools.port import StubReadOnlyAdapter

# The ICB-built incident window present in EVERY real state (incident_context_builder). This is the
# timestamp_range fallback for the 6 non-windowed tools (BLOCKER B1).
_INCIDENT_WINDOW: dict[str, object] = {
    "start": "2026-06-24T00:00:00Z",
    "end": "2026-06-24T01:00:00Z",
}


def _record(tool: str, raw: dict[str, object]) -> dict[str, object]:
    """Wrap a REAL adapter raw output as a §3.5 EXR tool_call record {tool, query, timestamp_range, raw}.

    ``query`` = a canonical identifying-kwargs string (what EXR records); ``timestamp_range`` = the
    canonical-JSON dedupe string (ENV does NOT use it — it derives the structured window from
    raw["time_window"] / context["time_window"]). Both are non-empty here so the record is well-formed.
    """
    return {"tool": tool, "query": f'{{"tool":"{tool}"}}', "timestamp_range": "tr", "raw": raw}


def _real_adapter_records() -> list[dict[str, object]]:
    """Build tool_call records from ALL 8 REAL StubReadOnlyAdapter outputs."""
    a = StubReadOnlyAdapter()
    win = {"start": "2026-06-24T00:00:00Z", "end": "2026-06-24T01:00:00Z"}
    return [
        _record(
            "query_prometheus_raw",
            dict(a.query_promql(query="rate(http_requests_total[5m])", time_window=win)),
        ),
        _record(
            "query_loki",
            dict(a.query_loki(service="checkout", time_window=win, correlation_id=None)),
        ),
        _record("k8s_get", dict(a.k8s_get(namespace="checkout", label_selector=None))),
        _record("k8s_describe", dict(a.k8s_describe(namespace="checkout", pod="checkout-pod-0"))),
        _record(
            "k8s_logs", dict(a.k8s_logs(namespace="checkout", pod="checkout-pod-0", previous=False))
        ),
        _record(
            "k8s_get_events", dict(a.k8s_get_events(namespace="checkout", field_selector=None))
        ),
        _record("search_playbook", dict(a.search_playbook(query="crashloop", top_k=3))),
        _record("topology_read", dict(a.topology_read(service="checkout"))),
    ]


def _state_with_records(records: list[dict[str, object]]) -> InvestigationState:
    """A state carrying the records + a realistic context (service + incident window)."""
    state = create_initial_state()
    state["tool_calls"] = cast(list[dict[str, JsonValue]], records)
    state["context"] = cast(
        dict[str, JsonValue],
        {"service": "checkout", "time_window": _INCIDENT_WINDOW},
    )
    return state


def test_all_eight_real_stubs_produce_valid_evidence() -> None:
    """BLOCKER B1 regression: ALL 8 real StubReadOnlyAdapter outputs → valid tiered Evidence (was 2/8).

    Asserts the count (8/8), the port round-trip (Evidence.model_validate), non-null required fields, the
    non-null citation, and that every emitted evidence carries a timestamp_range (the field the bug starved).
    """
    records = _real_adapter_records()
    evidence = build_evidence_normalizer()(_state_with_records(records))["evidence"]
    evidence_list = cast(list[dict[str, JsonValue]], evidence)

    assert len(evidence_list) == len(records) == 8, (
        "6/8 non-windowed tools must survive via the fallback"
    )

    seen_source_types: list[str] = []
    for ev in evidence_list:
        Evidence.model_validate(ev)  # port round-trip (AD-9 / extra="forbid")
        # required non-null
        assert isinstance(ev["source_type"], str) and ev["source_type"]
        assert isinstance(ev["source_name"], str) and ev["source_name"]
        assert isinstance(ev["query"], str) and ev["query"]
        assert isinstance(ev["summary"], str) and ev["summary"]
        ts = ev["timestamp_range"]
        assert (
            isinstance(ts, dict) and isinstance(ts.get("start"), str) and ts["start"]
        )  # B1: never starved
        # citation + honest derived
        assert isinstance(ev["raw_excerpt"], str) and ev["raw_excerpt"]
        assert ev["supports"] == []
        assert ev["contradicts"] == []
        assert ev["confidence"] is None
        seen_source_types.append(ev["source_type"])

    # every real source type is represented (prometheus / loki / kubernetes / playbook / topology)
    assert sorted(seen_source_types) == sorted(
        [
            "prometheus",
            "loki",
            "kubernetes",
            "kubernetes",
            "kubernetes",
            "kubernetes",
            "playbook",
            "topology",
        ]
    )


def test_non_windowed_tools_survive_only_via_incident_window_fallback() -> None:
    """BLOCKER B1 root-cause pin: the 6 non-windowed tools survive via context["time_window"]; WITHOUT it
    they are dropped (proving the fallback — not raw["time_window"] — is what saves them)."""
    records = _real_adapter_records()
    windowed = {"query_prometheus_raw", "query_loki"}

    # WITH the incident window → all 8 survive
    with_window = cast(
        list[dict[str, JsonValue]],
        build_evidence_normalizer()(_state_with_records(records))["evidence"],
    )
    assert len(with_window) == 8

    # WITHOUT any context incident window → ONLY the 2 windowed tools survive (raw carries their window)
    state = create_initial_state()
    state["tool_calls"] = cast(list[dict[str, JsonValue]], records)
    state["context"] = cast(dict[str, JsonValue], {"service": "checkout"})  # NO time_window
    without_window = cast(
        list[dict[str, JsonValue]],
        build_evidence_normalizer()(state)["evidence"],
    )
    assert len(without_window) == 2
    assert {cast(str, e["source_type"]) for e in without_window} == {"prometheus", "loki"}
    assert windowed == {"query_prometheus_raw", "query_loki"}  # sanity: the only raw-windowed tools


def test_non_windowed_tools_take_incident_window_not_a_guessed_value() -> None:
    """BLOCKER B1 honesty: the fallback timestamp_range IS the incident window (real, derived) — not a
    fabricated/guessed value. A distinct incident window produces a distinct timestamp_range."""
    records = [r for r in _real_adapter_records() if cast(str, r["tool"]) == "k8s_get"]
    distinct_window = {"start": "2026-06-23T12:00:00Z", "end": "2026-06-23T13:00:00Z"}
    state = create_initial_state()
    state["tool_calls"] = cast(list[dict[str, JsonValue]], records)
    state["context"] = cast(
        dict[str, JsonValue], {"service": "checkout", "time_window": distinct_window}
    )
    ev = cast(list[dict[str, JsonValue]], build_evidence_normalizer()(state)["evidence"])[0]
    assert ev["timestamp_range"] == distinct_window  # echoed the REAL incident window, not a guess
