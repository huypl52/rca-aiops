"""CI gate #3 — type-coherence 2-tier round-trip (Story 0.3 — AC3/AC4/T4).

AD-13 #3 / AD-9: the `InvestigationState` TypedDict (graph layer) must stay
type-coherent with the Pydantic port contract (`models.IncidentTrigger` §3.4,
`models.Evidence` §3.6 — Story 0.2). Two assertions, BOTH must pass to merge:

  (a) Type-coherence SHAPE (2-tier AD-9):
        - nested `state["trigger"]` keys ⊆ IncidentTrigger port field-set
          (18 §3.4 + incident_id)
        - every `state["evidence"]` item keys ⊆ Evidence port field-set (9 §3.6)
      Source-of-truth field-set = `ci.contract_schema` (spec-derived, NOT
      derived from the TypedDict — a gate that derives its expected-set from the
      object it checks is tautological and catches nothing; lesson gate #5).

  (b) ROUND-TRIP deep-equal:
        state → JsonPlusSerializer.dumps_typed → loads_typed → assert == state
      (AD-9: serializer = LangGraph built-in, NO custom serializer). Covers
      list-dedupe, scalar replace, hypothesis upsert, nested dict/list/None/
      str/int/float/bool.

JSON-safe invariant (AD-9 rule 1 "plain JSON-safe dicts") is asserted via
stdlib `json.dumps` — NOT JsonPlusSerializer. Why: JsonPlusSerializer
(ormsgpack + extensions) actually round-trips `datetime` and `set`, so it would
NOT trip on a non-JSON-safe value; the AD-9 "plain JSON-safe" invariant wants
those rejected, and stdlib `json.dumps` is what rejects them. Injecting a
`datetime`/`set` therefore fails `json.dumps` (TypeError) — proving the state
MUST be plain-JSON-safe on the axis the invariant cares about (`datetime`/`set`/
custom objects).

Caveat (a DEEP review probes this): the relation is NOT a strict superset. For
>64-bit ints, `json.dumps` succeeds but `JsonPlusSerializer.dumps_typed` raises
("Integer exceeds 64-bit range"). So `json.dumps` is stricter on the
`datetime`/`set` axis and looser on the big-int axis. We use `json.dumps` for the
JSON-safe invariant because the AD-9 invariant's operative axis is
`datetime`/`set`/custom-object rejection (the values a buggy node would leak),
and `json.dumps` enforces exactly that.

Negatives prove the gate cannot silently pass:
  - non-JSON-safe value (datetime / set) in state  → json.dumps raises TypeError
  - shape-drift (trigger key ∉ §3.4, evidence key ∉ §3.6) → (a) raises AssertionError
  - schema_version mismatch → assert_schema_version raises ValueError
"""

from __future__ import annotations

import datetime
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import pytest
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph

from ci.contract_schema import (
    INCIDENT_TRIGGER_GROUPING_FIELDS,
    SPEC_EVIDENCE_FIELDS,
    SPEC_INCIDENT_TRIGGER_FIELDS,
)
from graph.checkpoint import build_durable_store
from graph.state import (
    SCHEMA_VERSION,
    InvestigationState,
    JsonValue,
    append_dedupe_evidence,
    append_dedupe_playbook_hits,
    append_dedupe_tool_calls,
    append_safety_flags,
    assert_schema_version,
    create_initial_state,
    upsert_context,
    upsert_hypotheses,
)

# Spec-derived field-sets (single source of truth — spec tables, NOT the models
# and NOT the TypedDict; avoids a tautological drift gate).
TRIGGER_PORT_FIELDS: frozenset[str] = frozenset(SPEC_INCIDENT_TRIGGER_FIELDS) | frozenset(
    INCIDENT_TRIGGER_GROUPING_FIELDS
)
EVIDENCE_PORT_FIELDS: frozenset[str] = frozenset(SPEC_EVIDENCE_FIELDS)

_SERDE = JsonPlusSerializer()


# ---------------------------------------------------------------------------
# helpers shared by positive + negative assertions
# ---------------------------------------------------------------------------


def _assert_trigger_subset(trigger: Mapping[str, object]) -> None:
    """Raise AssertionError unless every ``trigger`` key is a §3.4 port field."""
    extra = set(trigger) - TRIGGER_PORT_FIELDS
    assert not extra, (
        f"type-coherence drift: state.trigger has keys outside IncidentTrigger "
        f"§3.4 port contract:\n  extra ({len(extra)}): {sorted(extra)}"
    )


def _assert_evidence_subset(item: Mapping[str, object]) -> None:
    """Raise AssertionError unless every evidence item key is a §3.6 port field."""
    extra = set(item) - EVIDENCE_PORT_FIELDS
    assert not extra, (
        f"type-coherence drift: state.evidence item has keys outside Evidence "
        f"§3.6 port contract:\n  extra ({len(extra)}): {sorted(extra)}"
    )


def _assert_shape_coherent(state: InvestigationState) -> None:
    """Assertion (a): nested trigger + every evidence item ⊆ port contract."""
    trigger = state.get("trigger")
    if isinstance(trigger, dict):
        _assert_trigger_subset(trigger)
    for item in state.get("evidence", []) or []:
        if isinstance(item, dict):
            _assert_evidence_subset(item)


def _assert_json_safe(state: InvestigationState) -> None:
    """AD-9 JSON-safe invariant: stdlib json must be able to serialize the state."""
    json.dumps(state)  # raises TypeError on datetime/set/custom object


def _roundtrip(state: InvestigationState) -> InvestigationState:
    """Serialize via LangGraph built-in JsonPlusSerializer, deserialize back."""
    type_str, blob = _SERDE.dumps_typed(state)
    loaded = _SERDE.loads_typed((type_str, blob))
    assert isinstance(loaded, dict), f"round-trip must yield a dict, got {type(loaded)}"
    return loaded  # type: ignore[return-value]


def _identity_node(_state: InvestigationState) -> dict[str, JsonValue]:
    """No-op node: returns no updates so the checkpoint persists the input state verbatim.

    Vehicle for :func:`_real_checkpoint_roundtrip` — a minimal IDENTITY graph over
    ``InvestigationState`` drives the checkpointer WITHOUT node logic, so the persisted state
    IS the input state (the comparison is serializer+backend fidelity, not node correctness).
    """
    return {}


def _real_checkpoint_roundtrip(state: InvestigationState, db_path: Path) -> InvestigationState:
    """Persist ``state`` to a REAL ``AsyncSqliteSaver`` checkpoint + reload it (CS Q4 / Story 7-4 AC1).

    The on-disk analog of :func:`_roundtrip`: where ``_roundtrip`` proves the in-memory
    JsonPlusSerializer round-trips the state, this proves the REAL sqlite backend (Story 7-4
    AD-11) round-trips the full 13-key spine byte-equal — the BUILT-IN serializer (NO custom
    serializer — AC1) survives a real persist→load. The sqlite ↔ postgres swap needs no custom
    serde (AC1) precisely because the built-in serializer is portable, which this asserts.
    """
    import asyncio

    async def _drive() -> InvestigationState:
        saver, conn = await build_durable_store(str(db_path))
        graph = StateGraph(InvestigationState)
        graph.add_node("identity", _identity_node)  # type: ignore[call-overload]
        graph.add_edge(START, "identity")
        graph.add_edge("identity", END)
        compiled = graph.compile(checkpointer=saver)
        config: Any = {
            "configurable": {"thread_id": "gate3-real-checkpoint"},
            "recursion_limit": 5,
        }
        await compiled.ainvoke(state, config=config)
        loaded = (await compiled.aget_state(config)).values
        await conn.close()
        assert isinstance(loaded, dict)
        return cast(InvestigationState, loaded)

    return asyncio.run(_drive())


def _sample_trigger() -> dict[str, JsonValue]:
    """A §3.4-shaped trigger dict (subset of IncidentTrigger.model_dump())."""
    return {
        "trigger_id": "trg-1",
        "source": "prometheus_alertmanager",
        "signal_type": "metric",
        "canonical_trigger": "DependencyTimeout",
        "alert_name": "HighLatency",
        "severity": "critical",
        "title": "Order latency",
        "description": "p99 latency spike",
        "service": "order",
        "affected_services": ["order", "payment"],
        "symptom": "latency",
        "namespace": "demo",
        "started_at": "2026-06-24T00:00:00Z",
        "ends_at": None,
        "labels": {"service": "order"},
        "annotations": {"summary": "spike"},
        "raw_payload": {"foo": "bar"},
        "raw_payload_ref": None,  # §3.4 row 18, None POC
        "incident_id": "inv-1",
    }


def _sample_evidence(source_name: str = "prometheus") -> dict[str, JsonValue]:
    """A §3.6-shaped evidence dict (subset of Evidence.model_dump())."""
    return {
        "source_type": "prometheus",
        "source_name": source_name,
        "query": "rate(http_requests[5m])",
        "timestamp_range": {"start": "2026-06-24T00:00:00Z", "end": None},
        "summary": "error rate up",
        "raw_excerpt": "0.42",
        "confidence": 0.8,
        "supports": ["H01"],
        "contradicts": [],
    }


def _sample_state() -> InvestigationState:
    """A representative state exercising dedupe / upsert / replace / nesting."""
    state = create_initial_state(incident_id="inv-1", trigger=_sample_trigger())
    # Reducer-managed collections: append + dedupe (duplicate evidence → kept once)
    state["evidence"] = append_dedupe_evidence(
        [], [_sample_evidence("prometheus"), _sample_evidence("prometheus")]
    )
    state["evidence"] = append_dedupe_evidence(state["evidence"], [_sample_evidence("loki")])
    state["tool_calls"] = append_dedupe_tool_calls(
        [],
        [{"tool": "prometheus", "query": "q", "timestamp_range": {"start": "s", "end": None}}],
    )
    # Hypothesis upsert: H01 replaced in place, H02 appended
    state["hypotheses"] = upsert_hypotheses(
        [{"id": "H01", "priority": 1, "status": "open"}],
        [
            {"id": "H01", "priority": 2, "status": "open"},
            {"id": "H02", "priority": 1, "status": "open"},
        ],
    )
    # Scalar replace
    state["next_action"] = "gather_more"
    state["sufficiency"] = {"floor_pass": False, "ceiling": 0.4}
    state["plan"] = {"steps": ["collect_prometheus_metric_evidence"]}
    return state


# ===========================================================================
# AC1 — InvestigationState has EXACTLY 14 top-level keys (comparison artifact added)
# ===========================================================================

EXPECTED_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "incident_id",
        "trigger",
        "context",
        "playbook_hits",
        "hypotheses",
        "plan",
        "tool_calls",
        "evidence",
        "sufficiency",
        "safety_flags",
        "next_action",
        "report",
    }
)


def test_state_has_exactly_13_keys() -> None:
    """AD-9 spine = exactly 14 top-level keys (leader DEEP counts independently)."""
    actual = set(InvestigationState.__annotations__)
    assert actual == EXPECTED_KEYS, (
        f"InvestigationState key-set drift:\n"
        f"  missing : {sorted(EXPECTED_KEYS - actual)}\n"
        f"  extra   : {sorted(actual - EXPECTED_KEYS)}"
    )
    assert len(actual) == 13


def test_schema_version_is_int_and_guard_fail_fast() -> None:
    """schema_version is int; mismatch raises (AD-9 rule 4 — no silent POC migration)."""
    state = create_initial_state()
    assert isinstance(state["schema_version"], int)
    assert state["schema_version"] == SCHEMA_VERSION
    # Mismatch must raise.
    with pytest.raises(ValueError):
        assert_schema_version({"schema_version": SCHEMA_VERSION + 1})


# ===========================================================================
# AC2 — reducer semantics (AD-4 / AD-10)
# ===========================================================================


def test_reducer_evidence_append_dedupe() -> None:
    """evidence = append + dedupe (source_name, query, timestamp_range)."""
    out = append_dedupe_evidence([], [_sample_evidence("p"), _sample_evidence("p")])
    assert len(out) == 1
    out = append_dedupe_evidence(out, [_sample_evidence("p"), _sample_evidence("l")])
    assert len(out) == 2  # dup dropped, loki kept


def test_reducer_tool_calls_append_dedupe_ad10() -> None:
    """tool_calls = append + dedupe (tool, query, timestamp_range) — AD-10."""
    tc: dict[str, JsonValue] = {
        "tool": "prometheus",
        "query": "q",
        "timestamp_range": {"start": "s", "end": None},
    }
    out = append_dedupe_tool_calls([], [tc, tc])
    assert len(out) == 1


def test_reducer_hypotheses_upsert_by_id() -> None:
    """hypotheses = upsert by id (replace in place, new id appended)."""
    out = upsert_hypotheses(
        [{"id": "H01", "priority": 1}],
        [{"id": "H01", "priority": 9}, {"id": "H02", "priority": 1}],
    )
    assert [h["id"] for h in out] == ["H01", "H02"]
    assert out[0]["priority"] == 9  # replaced in place


def test_reducers_are_pure_non_mutating() -> None:
    """All 6 reducers must not mutate their inputs (AD-12 purity spirit).

    Covers the full reducer set, not just one: each is exercised against a
    snapshot of its inputs and asserted to leave them untouched.
    """
    # --- list reducers (append+dedupe / upsert-by-id) ---
    e_left: list[dict[str, JsonValue]] = [_sample_evidence("p")]
    e_right: list[dict[str, JsonValue]] = [_sample_evidence("l")]
    snap_e_left, snap_e_right = [dict(x) for x in e_left], [dict(x) for x in e_right]
    append_dedupe_evidence(e_left, e_right)
    assert e_left == snap_e_left and e_right == snap_e_right

    tc_left: list[dict[str, JsonValue]] = [
        {"tool": "prometheus", "query": "q", "timestamp_range": {"start": "s", "end": None}}
    ]
    tc_right: list[dict[str, JsonValue]] = [
        {"tool": "loki", "query": "q", "timestamp_range": {"start": "s", "end": None}}
    ]
    snap_tc_left, snap_tc_right = [dict(x) for x in tc_left], [dict(x) for x in tc_right]
    append_dedupe_tool_calls(tc_left, tc_right)
    assert tc_left == snap_tc_left and tc_right == snap_tc_right

    pb_left: list[dict[str, JsonValue]] = [{"playbook": "A"}]
    pb_right: list[dict[str, JsonValue]] = [{"playbook": "B"}]
    snap_pb_left, snap_pb_right = [dict(x) for x in pb_left], [dict(x) for x in pb_right]
    append_dedupe_playbook_hits(pb_left, pb_right)
    assert pb_left == snap_pb_left and pb_right == snap_pb_right

    h_base: list[dict[str, JsonValue]] = [{"id": "H01", "priority": 1}]
    h_incoming: list[dict[str, JsonValue]] = [{"id": "H01", "priority": 9}]
    snap_h_base = [dict(x) for x in h_base]
    snap_h_in = [dict(x) for x in h_incoming]
    upsert_hypotheses(h_base, h_incoming)
    assert h_base == snap_h_base and h_incoming == snap_h_in

    # --- dict reducers (merge) ---
    ctx_left: dict[str, JsonValue] = {"a": 1}
    ctx_right: dict[str, JsonValue] = {"b": 2}
    upsert_context(ctx_left, ctx_right)
    assert ctx_left == {"a": 1} and ctx_right == {"b": 2}

    sf_left: dict[str, JsonValue] = {"x": 1}
    sf_right: dict[str, JsonValue] = {"y": 2}
    append_safety_flags(sf_left, sf_right)
    assert sf_left == {"x": 1} and sf_right == {"y": 2}


# ===========================================================================
# AC3 — gate #3 assertion (a) shape ⊆ port contract  +  (b) round-trip equal
# ===========================================================================


def test_gate3a_shape_subset_port_contract() -> None:
    """(a) nested trigger + evidence items ⊆ Pydantic port field-set."""
    state = _sample_state()
    _assert_shape_coherent(state)  # must not raise


def test_gate3b_roundtrip_deep_equal() -> None:
    """(b) serialize → deserialize → deep-equal (LangGraph built-in serializer)."""
    state = _sample_state()
    loaded = _roundtrip(state)
    assert loaded == state, (
        f"round-trip deep-equality failed:\n  expected: {state}\n  loaded  : {loaded}"
    )


def test_gate3b_roundtrip_covers_scalar_replace_and_nesting() -> None:
    """Round-trip preserves scalar-replace values + nested dict/list/None/scalars."""
    state = create_initial_state()
    state["next_action"] = "write"
    state["sufficiency"] = {"floor_pass": True, "ceiling": 0.91}
    state["report"] = {"root_cause": "x", "refs": [1, 2, 3], "nested": {"a": [True, None, 1.5]}}
    assert _roundtrip(state) == state


def test_gate3c_real_checkpoint_persist_load_equal(tmp_path: Path) -> None:
    """CS Q4 (Story 7-4): a REAL ``AsyncSqliteSaver`` checkpoint round-trips the 13-key state.

    The on-disk companion to :func:`test_gate3b_roundtrip_deep_equal`: the same sample state
    that survives the in-memory JsonPlusSerializer round-trip ALSO survives a real sqlite
    persist→load byte-equal. The serializer's correctness was already gate #3's domain; this
    asserts the durable BACKEND (AD-11, wired Story 7-4) does NOT corrupt it — the spine is
    checkpoint-stable with the built-in serializer (NO custom serializer — AC1). This is the
    natural home for the assertion: gate #3 owns type-coherence + serializer stability.
    """
    state = _sample_state()
    loaded = _real_checkpoint_roundtrip(state, tmp_path / "gate3-checkpoint.db")
    assert loaded == state, (
        f"real-checkpoint round-trip deep-equality failed:\n  expected: {state}\n  loaded  : {loaded}"
    )


# ===========================================================================
# AC4 — JSON-safe invariant (positive) + negatives (drift / non-JSON-safe)
# ===========================================================================


def test_json_safe_invariant_positive() -> None:
    """A clean state is plain-JSON-safe (stdlib json serializes it)."""
    _assert_json_safe(_sample_state())  # must not raise


def test_negative_non_json_safe_datetime() -> None:
    """Injecting a datetime breaks the JSON-safe invariant (AD-9).

    Deliberately planted via ``cast`` — the gate must trip at runtime even though
    we bypass the static JSON-safe type to simulate a buggy node return.
    """
    state = _sample_state()
    bad_context = cast(
        "dict[str, JsonValue]", {"fired_at": datetime.datetime(2026, 6, 24, 0, 0, 0)}
    )
    state["context"] = bad_context
    with pytest.raises(TypeError):
        _assert_json_safe(state)


def test_negative_non_json_safe_set() -> None:
    """Injecting a set breaks the JSON-safe invariant (AD-9)."""
    state = _sample_state()
    bad_context = cast("dict[str, JsonValue]", {"tags": {"a", "b"}})
    state["context"] = bad_context
    with pytest.raises(TypeError):
        _assert_json_safe(state)


def test_negative_shape_drift_trigger() -> None:
    """A trigger key outside §3.4 must fail assertion (a) — drift caught."""
    state = _sample_state()
    state["trigger"] = {**_sample_trigger(), "invented_field": "no"}
    with pytest.raises(AssertionError):
        _assert_shape_coherent(state)


def test_negative_shape_drift_evidence() -> None:
    """An evidence item key outside §3.6 must fail assertion (a) — drift caught."""
    state = _sample_state()
    drifted = {**_sample_evidence(), "invented_field": "no"}
    state["evidence"] = [drifted]
    with pytest.raises(AssertionError):
        _assert_shape_coherent(state)


def test_source_of_truth_not_tautological() -> None:
    """Guard against a tautological gate: expected-set comes from spec-derived
    `ci.contract_schema`, NOT from the TypedDict annotations."""
    typed_keys = set(InvestigationState.__annotations__)
    # trigger port field-set must NOT equal a state top-level key (different layers)
    assert TRIGGER_PORT_FIELDS != typed_keys
    assert EVIDENCE_PORT_FIELDS != typed_keys
    # And the spec-derived sets carry their expected cardinality (18+1 / 9).
    assert len(TRIGGER_PORT_FIELDS) == 19  # 18 §3.4 + incident_id
    assert len(EVIDENCE_PORT_FIELDS) == 9
