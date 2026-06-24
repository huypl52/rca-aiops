"""tests for graph.nodes.evidence_normalizer — Story 4.2 ENV node (Evidence tiering / AD-6 / AD-9 / AD-12).

Covers AC1–AC5 + the leader's DEEP-spotlight attack surface:
  - AC1 tiered 9-field Evidence WITH non-null citation (raw_excerpt); extra="forbid" honored.
  - AC2 writes state.evidence via the spine append_dedupe_evidence reducer — idempotent (no growth).
  - AC3 Pydantic model_validate-on-read AT THE PORT; state holds JSON-safe dicts (NOT Pydantic objects).
  - AC4 reject-on-missing-required — a raw missing source_type / unresolvable source_name / missing
    time_window / missing query → that tool_call's evidence is DROPPED, NEVER guessed/filled. NO
    tool-name→source_type mapping table (source_type is echoed verbatim from raw).
  - AC5 honesty — raw_excerpt non-null for dispatched records; supports/contradicts == [] (never null);
    confidence is None.
  - Determinism (AD-12) — same input → byte-identical emitted dicts across calls AND across PYTHONHASHSEED
    (cross-process); order-independent.
  - Constraint 5 never-raise — malformed raw / non-mapping record / a summarizer that raises → drop the
    candidate, return survivors; ENV never propagates an exception.
  - Layer purity (AST) — imports ⊆ {models, graph, stdlib, typing}; ZERO services/routers/adapters/tools/
    pydantic/random/time/datetime/uuid imports; ZERO forbidden attribute calls (now/open/sleep/randint).

AST-discipline (docstring-immune): assertions are statement-level, not in docstrings.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest

from graph.nodes.evidence_normalizer import (
    build_evidence_normalizer,
    default_deterministic_summarizer,
)
from graph.state import (
    InvestigationState,
    JsonValue,
    append_dedupe_evidence,
    create_initial_state,
)
from models.evidence import Evidence

_ENV_SRC = Path("graph/nodes/evidence_normalizer.py").read_text(encoding="utf-8")
_EVIDENCE_FIELDS = frozenset(
    Evidence.model_fields.keys()
)  # the 9 §3.6 fields (spec source of truth)

# The ICB-built incident window — EVERY real state carries context["time_window"] (incident_context_builder).
# Used as the timestamp_range fallback for point-in-time/static tools whose raw carries NO query window
# (leader BLOCKER B1: k8s_*, search_playbook, topology_read must survive via this honest fallback).
_INCIDENT_WINDOW: dict[str, object] = {
    "start": "2026-06-24T00:00:00Z",
    "end": "2026-06-24T01:00:00Z",
}


# ---------------------------------------------------------------------------
# helpers — build a realistic DISPATCHED tool_call record + a state carrying it
# ---------------------------------------------------------------------------


def _raw(**overrides: object) -> dict[str, object]:
    """A prometheus-shaped RawOutput (carries source_type + time_window + a result list)."""
    base: dict[str, object] = {
        "source_type": "prometheus",
        "query": 'rate(http_requests_total{service="checkout"}[5m])',
        "time_window": {"start": "2026-06-24T00:00:00Z", "end": "2026-06-24T01:00:00Z"},
        "result_type": "vector",
        "result": [{"metric": {"__name__": "http_requests_total"}, "value": [0.0, "42"]}],
    }
    base.update(overrides)
    return base


def _record(raw: Mapping[str, object], **overrides: object) -> dict[str, object]:
    """A §3.5 EXR record {tool, query, timestamp_range, raw} (query/timestamp_range = canonical JSON str)."""
    import json

    base: dict[str, object] = {
        "tool": "query_prometheus_raw",
        "query": '{"query": "rate(http_requests_total[5m])"}',
        "timestamp_range": '{"end": "2026-06-24T01:00:00Z", "start": "2026-06-24T00:00:00Z"}',
        "raw": raw,
    }
    base.update(overrides)
    _ = json  # keep import local to the helper (used only for shaping fixtures)
    return base


def _state(
    records: list[dict[str, object]],
    *,
    service: str | None = "checkout",
    context_window: Mapping[str, object] | None = _INCIDENT_WINDOW,
) -> InvestigationState:
    """A state seeded with tool_calls + context.

    The context carries the source_name fallback of last resort (``service``) AND, by default, the ICB-built
    incident window (``time_window``) — the timestamp_range fallback for non-windowed tools (BLOCKER B1). Pass
    ``context_window=None`` to model a context with NO incident window (used to assert the both-absent DROP).
    """
    state = create_initial_state()
    state["tool_calls"] = cast(list[dict[str, JsonValue]], records)
    context: dict[str, object] = {}
    if service is not None:
        context["service"] = service
    if context_window is not None:
        context["time_window"] = context_window
    state["context"] = cast(dict[str, JsonValue], context)
    return state


def _normalize(state: InvestigationState) -> list[dict[str, JsonValue]]:
    out = build_evidence_normalizer()(state)
    return cast(list[dict[str, JsonValue]], out["evidence"])


# ---------------------------------------------------------------------------
# AC1 — tiered 9-field Evidence WITH non-null citation; extra="forbid" honored
# ---------------------------------------------------------------------------


def test_normalizes_dispatched_tool_call_to_tiered_evidence() -> None:
    """AC1: a dispatched promql record → exactly one tiered Evidence dict with a non-null citation."""
    evidence = _normalize(_state([_record(_raw())]))
    assert len(evidence) == 1
    ev = evidence[0]
    assert set(ev.keys()) == _EVIDENCE_FIELDS  # exactly the 9 §3.6 fields (extra="forbid")
    # required (non-null)
    assert ev["source_type"] == "prometheus"
    assert ev["source_name"] == "checkout"  # promql raw has no source_name → context fallback
    assert isinstance(ev["query"], str) and ev["query"]
    assert ev["timestamp_range"] == {"start": "2026-06-24T00:00:00Z", "end": "2026-06-24T01:00:00Z"}
    assert isinstance(ev["summary"], str) and ev["summary"]
    # optional-nullable
    assert ev["raw_excerpt"] is not None  # AC5 / AD-6 citation present
    # derived (never null)
    assert ev["supports"] == []
    assert ev["contradicts"] == []
    assert ev["confidence"] is None


@pytest.mark.parametrize(
    ("raw", "expected_source_name"),
    [
        (
            {
                "source_type": "loki",
                "source_name": "checkout",
                "time_window": {"start": "s"},
                "streams": [{"v": 1}],
            },
            "checkout",
        ),
        (
            {
                "source_type": "kubernetes",
                "source_name": "checkout-pod-0",
                "pods": [{"name": "x"}],
            },
            "checkout-pod-0",
        ),
        (
            {
                "source_type": "topology",
                "service": "billing",
                "services": ["billing"],
            },
            "billing",
        ),  # service precedence
    ],
)
def test_source_name_precedence_chain(raw: dict[str, object], expected_source_name: str) -> None:
    """AC1/§2.3: source_name resolves raw["source_name"] → raw["service"] → context["service"].

    k8s/topology raws carry NO query window (real stubs); they survive the timestamp_range gate via the
    context incident-window fallback (BLOCKER B1) — no synthetic time_window injected here.
    """
    evidence = _normalize(_state([_record(raw)]))
    assert evidence[0]["source_name"] == expected_source_name


# ---------------------------------------------------------------------------
# AC2 — writes state.evidence via the spine reducer; idempotent (no growth)
# ---------------------------------------------------------------------------


def test_evidence_dicts_are_reducer_safe_no_typeerror() -> None:
    """Spotlight #1: ENV-produced dicts (nested-dict timestamp_range) feed append_dedupe_evidence WITHOUT
    raising ``TypeError: unhashable type: 'dict'`` (the reducer serializes the nested dict PYTHONHASHSEED-safe)."""
    evidence = _normalize(_state([_record(_raw())]))
    merged = append_dedupe_evidence([], evidence)  # must not raise
    assert len(merged) == 1


def test_normalize_all_is_idempotent_no_growth() -> None:
    """AC2 / Spotlight #7: call ENV twice on the same state → evidence grows by ZERO on the second pass."""
    state = _state([_record(_raw()), _record(_raw(), query='{"query":"other"}')])
    first = append_dedupe_evidence([], _normalize(state))
    second = append_dedupe_evidence(first, _normalize(state))
    assert len(first) == len(second) == 2


def test_normalize_all_dedupes_identical_records() -> None:
    """AC2: two byte-identical records → one evidence (reducer dedupe by (source_name, query, timestamp_range))."""
    state = _state([_record(_raw()), _record(_raw())])
    merged = append_dedupe_evidence([], _normalize(state))
    assert len(merged) == 1


# ---------------------------------------------------------------------------
# AC3 — Pydantic model_validate-on-read AT THE PORT; state holds JSON-safe dicts
# ---------------------------------------------------------------------------


def test_emits_plain_json_safe_dicts_not_pydantic_objects() -> None:
    """AC3: ENV emits plain dicts (.model_dump()), NOT Evidence instances; JSON-serializable (AD-9)."""
    import json

    evidence = _normalize(_state([_record(_raw())]))
    assert isinstance(evidence[0], dict)
    assert not isinstance(evidence[0], Evidence)
    json.dumps(evidence)  # JSON-safe (AD-9) — must not raise


def test_emitted_dict_round_trips_through_evidence_port() -> None:
    """AC3: each emitted dict re-validates cleanly at the port (model_validate-on-read contract held)."""
    for ev in _normalize(_state([_record(_raw())])):
        Evidence.model_validate(ev)  # must not raise


# ---------------------------------------------------------------------------
# AC4 — reject-on-missing-required (NEVER guess / fill); no tool-name→source_type mapping
# ---------------------------------------------------------------------------


def test_raw_missing_source_type_is_dropped_not_guessed() -> None:
    """AC4 / Spotlight #2,#3: a raw WITHOUT source_type → evidence DROPPED (no guessed default)."""
    raw = _raw()
    del raw["source_type"]
    assert _normalize(_state([_record(raw)])) == []


def test_source_type_is_echoed_verbatim_no_tool_name_mapping() -> None:
    """Spotlight #2: source_type is echoed from raw VERBATIM — NO tool-name→source_type mapping table
    (a raw declaring a non-standard source_type survives unchanged)."""
    raw = _raw(source_type="weird-custom-source")
    evidence = _normalize(_state([_record(raw)]))
    assert evidence[0]["source_type"] == "weird-custom-source"


def test_source_name_unresolvable_is_dropped() -> None:
    """AC4: source_name unresolvable via the §2.3 chain (raw has none, context has none) → DROP."""
    raw = {
        "source_type": "prometheus",
        "time_window": {"start": "s"},
        "result": [],
    }  # no source_name/service
    assert _normalize(_state([_record(raw)], service=None)) == []


def test_no_window_anywhere_is_dropped() -> None:
    """AC4 / BLOCKER B1: a raw WITHOUT its own window AND a context WITHOUT an incident window → DROP.
    (The incident-window fallback is tried first; only when BOTH windows are absent/invalid is the
    candidate dropped — never guessed.)"""
    raw = _raw()
    del raw["time_window"]
    assert _normalize(_state([_record(raw)], context_window=None)) == []


def test_record_missing_query_is_dropped() -> None:
    """AC4: a record without a query → DROP."""
    record = _record(_raw())
    del record["query"]
    assert _normalize(_state([record])) == []


# ---------------------------------------------------------------------------
# timestamp_range precedence (BLOCKER B1) — raw window → incident window → DROP
# ---------------------------------------------------------------------------


def test_raw_own_window_wins_over_incident_window() -> None:
    """BLOCKER B1: when raw carries its OWN window, that (more-precise) window is used — NOT the incident
    window (precedence source #1 wins)."""
    raw = _raw()  # raw time_window = {00:00, 01:00}
    narrower = {"start": "2026-06-24T00:30:00Z", "end": "2026-06-24T00:45:00Z"}
    ev = _normalize(_state([_record(raw)], context_window=narrower))[0]
    assert ev["timestamp_range"] == {
        "start": "2026-06-24T00:00:00Z",
        "end": "2026-06-24T01:00:00Z",
    }  # raw's window, not the context's narrower one


def test_incident_window_fallback_when_raw_has_none() -> None:
    """BLOCKER B1: a raw WITHOUT its own window (k8s_*/playbook/topology) falls back to the ICB incident
    window → SURVIVES (was SILENTLY DROPPED before the fix)."""
    raw = _raw()
    del raw["time_window"]  # simulate a point-in-time/static tool (no query window)
    ev = _normalize(_state([_record(raw)]))[0]
    assert ev["timestamp_range"] == _INCIDENT_WINDOW  # the incident window fallback


def test_incident_window_nullable_end_preserved() -> None:
    """BLOCKER B1: a still-firing incident (end=None) propagates end=None through the fallback honestly."""
    raw = _raw()
    del raw["time_window"]
    ev = _normalize(
        _state([_record(raw)], context_window={"start": "2026-06-24T00:00:00Z", "end": None})
    )[0]
    assert ev["timestamp_range"] == {"start": "2026-06-24T00:00:00Z", "end": None}


def test_invalid_raw_window_falls_back_to_incident_window() -> None:
    """BLOCKER B1: an INVALID raw window (start empty/non-str) is skipped → incident window used (not guessed)."""
    raw = _raw(time_window={"start": "", "end": "2026-06-24T01:00:00Z"})  # empty start → invalid
    ev = _normalize(_state([_record(raw)]))[0]
    assert ev["timestamp_range"] == _INCIDENT_WINDOW  # fallback, not the invalid raw window


@pytest.mark.parametrize("bad_raw", ["a-string", 42, None, ["a", "list"]])
def test_malformed_raw_non_mapping_is_dropped(bad_raw: object) -> None:
    """Constraint 5: a non-mapping raw → record skipped (never raises)."""
    assert (
        _normalize(_state([{"tool": "t", "query": "q", "timestamp_range": "tr", "raw": bad_raw}]))
        == []
    )


def test_non_mapping_record_is_skipped() -> None:
    """Constraint 5: a non-mapping record in tool_calls is skipped; survivors are returned."""
    state = _state(["not-a-record", 42, None, _record(_raw())])  # type: ignore[list-item]
    assert len(_normalize(state)) == 1


def test_no_state_tool_calls_returns_empty() -> None:
    """Constraint 5: a state with no tool_calls key → empty evidence (never raises)."""
    state = create_initial_state()
    assert build_evidence_normalizer()(state) == {"evidence": []}


# ---------------------------------------------------------------------------
# AC5 — honesty: non-null citation; derived lists empty (never null); confidence None
# ---------------------------------------------------------------------------


def test_raw_excerpt_is_non_null_for_dispatched_record() -> None:
    """AC5 / AD-6: every emitted evidence carries a non-null raw_excerpt citation."""
    for ev in _normalize(_state([_record(_raw())])):
        assert isinstance(ev["raw_excerpt"], str) and ev["raw_excerpt"]


def test_raw_excerpt_is_derived_deterministic_serialization_of_raw() -> None:
    """Spotlight #6/#8: raw_excerpt is the deterministic sorted-JSON of raw (DERIVED, not fabricated)."""
    import json

    raw = _raw()
    ev = _normalize(_state([_record(raw)]))[0]
    excerpt: str = ev["raw_excerpt"]  # type: ignore[assignment]
    parsed = json.loads(excerpt)
    assert parsed == json.loads(
        json.dumps(raw, sort_keys=True)
    )  # same content (excerpt is bounded but full here)


def test_supports_contradicts_empty_and_confidence_none() -> None:
    """AC5: supports/contradicts start [] (never null, never fabricated); confidence None until 4-3."""
    for ev in _normalize(_state([_record(_raw())])):
        assert ev["supports"] == []
        assert ev["contradicts"] == []
        assert ev["confidence"] is None


# ---------------------------------------------------------------------------
# Determinism (AD-12) — same input → identical dicts; PYTHONHASHSEED-safe; order-independent
# ---------------------------------------------------------------------------


def test_same_input_identical_output_across_calls() -> None:
    """AD-12: repeated calls on identical input → byte-identical emitted dicts."""
    state = _state([_record(_raw()), _record(_raw(), query='{"query":"b"}')])
    runs = [_normalize(state) for _ in range(5)]
    assert all(run == runs[0] for run in runs)


def test_order_independent_evidence_set() -> None:
    """AD-12: shuffling tool_calls order → the same evidence SET (reducer-dedupe equivalence)."""
    r1, r2 = _record(_raw()), _record(_raw(), query='{"query":"b"}')
    a = append_dedupe_evidence([], _normalize(_state([r1, r2])))
    b = append_dedupe_evidence([], _normalize(_state([r2, r1])))
    assert sorted(map(str, a)) == sorted(map(str, b))


@pytest.mark.parametrize("seed", [0, 1, 7, 42, 99])
def test_pythonhashseed_safe_cross_process(seed: int) -> None:
    """AD-12 / Spotlight #4: identical emitted dicts across fresh interpreters under DIFFERENT hash seeds."""
    code = (
        "from graph.nodes.evidence_normalizer import build_evidence_normalizer\n"
        "from graph.state import create_initial_state\n"
        "env = build_evidence_normalizer()\n"
        "raw = {'source_type':'prometheus','query':'q','time_window':{'start':'s','end':None},"
        "'result_type':'vector','result':[{'metric':{},'value':[0.0,'1']}]}\n"
        "rec = {'tool':'query_prometheus_raw','query':'{\"query\":\"q\"}','timestamp_range':'tr','raw':raw}\n"
        "st = create_initial_state(); st['tool_calls']=[rec]; st['context']={'service':'checkout'}\n"
        "import json; print(json.dumps(env(st)['evidence'], sort_keys=True))"
    )
    env = {**os.environ, "PYTHONHASHSEED": str(seed)}
    out = subprocess.run(
        [sys.executable, "-c", code], check=True, capture_output=True, text=True, env=env, cwd="."
    )
    baseline = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONHASHSEED": "0"},
        cwd=".",
    )
    assert out.stdout == baseline.stdout, f"PYTHONHASHSEED={seed} diverged"


# ---------------------------------------------------------------------------
# Constraint 5 — never raises (malformed inputs / summarizer that raises)
# ---------------------------------------------------------------------------


def test_summarizer_that_raises_drops_candidate_not_env() -> None:
    """Constraint 5: an injected summarizer that raises → that record is dropped, others survive, ENV returns."""

    def boom(raw: Mapping[str, object], source_type: str, query: str) -> str:
        raise RuntimeError("summarizer exploded")

    env = build_evidence_normalizer(summarizer=boom)
    out = env(_state([_record(_raw()), _record(_raw(), query='{"query":"b"}')]))
    assert out == {
        "evidence": []
    }  # both dropped (summarizer raises for every record); ENV never raised


def test_summarizer_that_returns_empty_drops_candidate() -> None:
    """AC4/Constraint 5: a summarizer returning an empty/non-str summary → candidate dropped."""

    def empty(raw: Mapping[str, object], source_type: str, query: str) -> str:
        return ""

    env = build_evidence_normalizer(summarizer=empty)
    assert env(_state([_record(_raw())])) == {"evidence": []}


# ---------------------------------------------------------------------------
# Summarizer seam — default is derived/deterministic (no guessing); custom injectable
# ---------------------------------------------------------------------------


def test_custom_summarizer_is_used() -> None:
    """§2.1: the injected summarizer is the one that populates summary (swap WITHOUT rewiring)."""
    env = build_evidence_normalizer(summarizer=lambda raw, st, q: f"CUSTOM {st}:{len(raw)}")
    out = cast(list[dict[str, JsonValue]], env(_state([_record(_raw())]))["evidence"])
    ev = out[0]
    assert ev["summary"] == "CUSTOM prometheus:5"


def test_default_summarizer_is_deterministic_and_derived() -> None:
    """Spotlight #6: the default summary is a deterministic function of (raw, source_type, query) — no guess."""
    raw = _raw()
    s1 = default_deterministic_summarizer(raw, "prometheus", '{"query":"q"}')
    s2 = default_deterministic_summarizer(raw, "prometheus", '{"query":"q"}')
    assert s1 == s2  # deterministic
    assert "prometheus" in s1  # derived from source_type
    assert "1 record" in s1  # derived from the real result-list count (1 item)
    # input-dependent: a different raw count → a different summary
    raw2 = _raw(result=[{"v": 1}, {"v": 2}, {"v": 3}])
    assert "3 record" in default_deterministic_summarizer(raw2, "prometheus", '{"query":"q"}')


def test_no_hardcoded_fabricated_field_values_in_module() -> None:
    """Spotlight #6 (AST): the candidate dict's source_type/source_name/raw_excerpt values are NOT bare
    string constants — they are derived expressions (Call/Name/Subscript), proving no fabricated literals."""
    tree = ast.parse(_ENV_SRC)
    found_candidate = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        keys: list[str] = []
        for key in node.keys:
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                keys.append(key.value)
        if {"source_type", "source_name", "raw_excerpt"} <= set(keys):
            found_candidate = True
            for key_node, value_node in zip(node.keys, node.values, strict=False):
                if isinstance(key_node, ast.Constant) and key_node.value in {
                    "source_type",
                    "source_name",
                    "raw_excerpt",
                }:
                    assert not isinstance(value_node, ast.Constant), (
                        f"fabricated literal for {key_node.value!r}"
                    )
    assert found_candidate, "the candidate Evidence dict literal was not found (test setup drift)"


# ---------------------------------------------------------------------------
# Layer purity (AD-1 / gate #2) — AST: imports ⊆ {models, graph, stdlib, typing}
# ---------------------------------------------------------------------------


def test_imports_limited_to_models_graph_stdlib() -> None:
    """Spotlight #5 (AST): imports ⊆ {models, graph, stdlib, typing}; ZERO back-edges + forbidden sources."""
    allowed_roots = {
        "models",
        "graph",
        "__future__",
        "json",
        "collections",
        "typing",
        "abc",
        "functools",
    }
    forbidden_roots = {
        "services",
        "routers",
        "adapters",
        "tools",
        "pydantic",
        "random",
        "time",
        "datetime",
        "uuid",
    }
    tree = ast.parse(_ENV_SRC)
    for node in ast.walk(tree):
        roots: set[str] = set()
        if isinstance(node, ast.Import):
            roots = {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            roots = {(node.module or "").split(".")[0]}
        else:
            continue
        assert not (roots & forbidden_roots), f"forbidden import: {roots & forbidden_roots}"
        assert roots <= allowed_roots, f"import outside allowed set: {roots - allowed_roots}"


def test_no_forbidden_attribute_calls() -> None:
    """Spotlight #5 (AST): ZERO forbidden attribute calls (now/open/sleep/randint/...) — no nondeterminism."""
    forbidden_attrs = {"now", "open", "sleep", "randint", "random", "choice", "today", "utcnow"}
    tree = ast.parse(_ENV_SRC)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in forbidden_attrs, f"forbidden call .{node.func.attr}()"


def test_read_only_no_tools_import() -> None:
    """§1 / gate#1: ENV imports NO tools (it normalizes already-collected output — no dispatch/adapter)."""
    assert "import tools" not in _ENV_SRC.replace("\n", " ")
    assert "from tools" not in _ENV_SRC.replace("\n", " ")


def test_spine_unchanged_13_keys() -> None:
    """Scope: InvestigationState spine still EXACTLY 13 keys (ENV adds no spine key; state.py unmodified)."""
    assert len(InvestigationState.__annotations__) == 13
