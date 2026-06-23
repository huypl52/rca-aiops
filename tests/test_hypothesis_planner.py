"""Story 3.2 — hypothesis_planner node (§3.5): deterministic-id hypothesis planning + graceful degrade.

Covers the ACs / leader DEEP spotlights:
  - AC1 — REUSE ``upsert_hypotheses`` (0-3); the node returns a LIST; the reducer merges (replan
           preserves prior hypotheses — the node does NOT reimplement merge/dedupe).
  - AC2 — DETERMINISTIC ids ``H01..`` stamped BY THE NODE by enumeration; AST-proven NO
           random/time/datetime/uuid; same state → same hypotheses + same ids.
  - Shape — each item EXACTLY ``{id, priority, plan, status}``; no timestamp; no invented keys;
           single-key return ``{"hypotheses": [...]}`` (AD-4).
  - Read-only (AD-3) — pure planning node: NO write/exec primitives; NO tools/adapters/models import;
           NO adapter call (unlike 3-1).
  - Constraint 5 — graceful degrade: missing/empty inputs + source-raise + malformed state →
           ``{"hypotheses": []}``, NEVER raises.
  - AD-1 one-way (gate #2) — node imports graph.state + stdlib ONLY; NO tools.port (the CRITICAL
           difference from 3-1); import roots ⊆ {__future__, graph, stdlib}.
  - DI seam — factory ``build_hypothesis_planner(source, *, max_hypotheses)``; two factories
           independent; ``source`` is graph-internal; default is deterministic; ``plan`` is JSON-safe.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import TYPE_CHECKING, cast

from graph.nodes.hypothesis_planner import (
    HypothesisSource,
    build_hypothesis_planner,
)
from graph.state import (
    InvestigationState,
    JsonValue,
    create_initial_state,
    upsert_hypotheses,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

NODE_FILE = Path(__file__).resolve().parents[1] / "graph" / "nodes" / "hypothesis_planner.py"


# ---------------------------------------------------------------------------
# Fixtures — deterministic injected sources + state helpers
# ---------------------------------------------------------------------------


def _static_source(
    *descriptors: dict[str, JsonValue],
) -> HypothesisSource:
    """Build a deterministic source that always emits the given descriptors (no id — node stamps).

    Varargs (annotated ``dict[str, JsonValue]``) give each dict literal bidirectional context so
    mypy infers ``dict[str, JsonValue]`` instead of ``dict[str, object]`` (recursive-JsonValue
    literal-inference workaround).
    """
    snapshot = [dict(d) for d in descriptors]

    def _source(
        context: Mapping[str, JsonValue],  # noqa: ARG001
        playbook_hits: Sequence[Mapping[str, JsonValue]],  # noqa: ARG001
        evidence: Sequence[Mapping[str, JsonValue]],  # noqa: ARG001
    ) -> list[dict[str, JsonValue]]:
        return [dict(d) for d in snapshot]

    return _source


def _raising_source() -> HypothesisSource:
    """A source that always raises (AC: graceful degrade on source failure)."""

    def _source(
        context: Mapping[str, JsonValue],  # noqa: ARG001
        playbook_hits: Sequence[Mapping[str, JsonValue]],  # noqa: ARG001
        evidence: Sequence[Mapping[str, JsonValue]],  # noqa: ARG001
    ) -> list[dict[str, JsonValue]]:
        raise RuntimeError("simulated source failure")

    return _source


def _state(
    *,
    playbook_hits: list[dict[str, JsonValue]] | None = None,
    evidence: list[dict[str, JsonValue]] | None = None,
    context: dict[str, JsonValue] | None = None,
) -> InvestigationState:
    """A partial state with context + playbook_hits + evidence (the planner's three inputs)."""
    state = create_initial_state()
    state["context"] = (
        context if context is not None else {"service": "checkout", "namespace": "demo"}
    )
    state["playbook_hits"] = playbook_hits if playbook_hits is not None else []
    state["evidence"] = evidence if evidence is not None else []
    return state


def _hits(n: int) -> list[dict[str, JsonValue]]:
    return [
        {"id": f"pb-{i}", "score": round(1.0 - i * 0.1, 2), "title": f"Playbook {i}"}
        for i in range(n)
    ]


def _hypotheses_of(result: dict[str, JsonValue]) -> list[dict[str, JsonValue]]:
    """Narrow ``result["hypotheses"]`` (JsonValue) to a list for assertion (mypy-safe)."""
    hs = result["hypotheses"]
    assert isinstance(hs, list)
    return [h for h in hs if isinstance(h, dict)]


def _descs(*items: dict[str, JsonValue]) -> list[dict[str, JsonValue]]:
    """Build a ``list[dict[str, JsonValue]]`` from descriptor literals (mypy-safe).

    The annotated ``*items`` gives each dict literal bidirectional ``dict[str, JsonValue]`` context
    (avoids the recursive-JsonValue dict-literal inference that otherwise yields ``dict[str, object]``).
    """
    return [dict(i) for i in items]


def _plan_of(hyp: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Narrow ``hyp["plan"]`` (JsonValue) to a dict for nested-key assertion (mypy-safe)."""
    plan = hyp["plan"]
    assert isinstance(plan, dict)
    return plan


# ---------------------------------------------------------------------------
# AC1 — REUSE upsert_hypotheses (0-3); node returns a LIST; reducer owns merge
# ---------------------------------------------------------------------------


def test_node_returns_a_list_for_the_reducer() -> None:
    """AC1: the node returns a LIST value (the reducer upserts by id — node does NOT merge)."""
    node = build_hypothesis_planner(
        _static_source({"priority": 1, "plan": {"x": 1}, "status": "proposed"})
    )
    result = node(_state())
    assert set(result.keys()) == {"hypotheses"}
    assert isinstance(result["hypotheses"], list)


def test_reducer_upserts_node_output_replace_in_place() -> None:
    """AC1: upsert_hypotheses (REUSED 0-3) replaces matching id in place; new id appends."""
    node = build_hypothesis_planner(
        _static_source({"priority": 1, "plan": {"v": 2}, "status": "proposed"})
    )
    out = node(_state())
    # Left already has H01 (different content) → reducer replaces H01 in place.
    prior: list[dict[str, JsonValue]] = [
        {"id": "H01", "priority": 9, "plan": {"v": 1}, "status": "old"}
    ]
    merged = upsert_hypotheses(prior, _hypotheses_of(out))
    assert len(merged) == 1  # position stable — NOT appended
    assert merged[0]["plan"] == {"v": 2}  # replaced in place


def test_replan_preserves_prior_hypotheses_via_reducer() -> None:
    """AC1 / leader FLAG: "replan KHÔNG mất hypothesis cũ" — GUARANTEED by the reducer, not the node.

    Pre-seed state.hypotheses with an id the node does NOT re-emit (H99); run the node (emits H01);
    the reducer merge RETAINS H99 (left preserved) and adds H01. The node never read prior state.
    """
    node = build_hypothesis_planner(
        _static_source({"priority": 1, "plan": {"k": 1}, "status": "proposed"})
    )
    out = node(_state())
    prior: list[dict[str, JsonValue]] = [
        {"id": "H99", "priority": 5, "plan": {"legacy": True}, "status": "validated"}
    ]
    merged = upsert_hypotheses(prior, _hypotheses_of(out))
    ids = [m["id"] for m in merged]
    assert "H99" in ids and "H01" in ids  # prior retained + new present
    assert len(merged) == 2


def test_replan_grows_with_new_id_via_reducer() -> None:
    """AC1: a replan that emits an ADDITIONAL hypothesis appends it (new id)."""
    first = build_hypothesis_planner(
        _static_source({"priority": 1, "plan": {"a": 1}, "status": "proposed"})
    )(_state())
    second = build_hypothesis_planner(
        _static_source(
            {"priority": 1, "plan": {"a": 1}, "status": "proposed"},
            {"priority": 2, "plan": {"b": 2}, "status": "proposed"},
        )
    )(_state())
    merged = upsert_hypotheses(_hypotheses_of(first), _hypotheses_of(second))
    assert [m["id"] for m in merged] == ["H01", "H02"]  # H01 replaced, H02 appended


# ---------------------------------------------------------------------------
# AC2 — DETERMINISTIC ids stamped by the node; AST no random/time/datetime/uuid
# ---------------------------------------------------------------------------


def test_ids_are_sequential_zero_padded_h01_h02() -> None:
    """AC2: the node stamps H01, H02, … by enumeration (2-digit zero-padded)."""
    node = build_hypothesis_planner(
        _static_source(
            {"priority": 1, "plan": {"a": 1}, "status": "proposed"},
            {"priority": 2, "plan": {"b": 2}, "status": "proposed"},
            {"priority": 3, "plan": {"c": 3}, "status": "proposed"},
        )
    )
    ids = [h["id"] for h in _hypotheses_of(node(_state()))]
    assert ids == ["H01", "H02", "H03"]


def test_source_emits_no_id_node_stamps_it() -> None:
    """AC2: the source emits descriptors WITHOUT id; only the node adds id."""
    captured: list[list[dict[str, JsonValue]]] = []

    def _spy(
        context: Mapping[str, JsonValue],  # noqa: ARG001
        playbook_hits: Sequence[Mapping[str, JsonValue]],  # noqa: ARG001
        evidence: Sequence[Mapping[str, JsonValue]],  # noqa: ARG001
    ) -> list[dict[str, JsonValue]]:
        out: list[dict[str, JsonValue]] = [{"priority": 1, "plan": {"x": 1}, "status": "proposed"}]
        captured.append([dict(d) for d in out])
        return out

    node = build_hypothesis_planner(_spy)
    result = node(_state())
    # The source's descriptors had NO id …
    assert all("id" not in d for d in captured[0])
    # … but the node's output has ids.
    assert all("id" in h for h in _hypotheses_of(result))


def test_same_state_same_hypotheses_and_ids_deterministic() -> None:
    """AC2/AD-12: same state → identical hypotheses + identical ids (two fresh factories)."""
    descriptors = _descs(
        {"priority": 1, "plan": {"a": 1}, "status": "proposed"},
        {"priority": 2, "plan": {"b": 2}, "status": "proposed"},
    )
    a = build_hypothesis_planner(_static_source(*descriptors))(_state())
    b = build_hypothesis_planner(_static_source(*descriptors))(_state())
    assert a == b


def test_default_source_is_deterministic() -> None:
    """AD-12: the default rule-based source is a pure function → same input, same output + ids."""
    node_a = build_hypothesis_planner()  # default source
    node_b = build_hypothesis_planner()  # default source
    state = _state(playbook_hits=_hits(3))
    assert node_a(state) == node_b(state)


def test_node_source_has_no_random_time_datetime_or_uuid() -> None:
    """AC2/AD-12: AST-proven — no random/time/datetime/uuid primitives in the node module."""
    src = NODE_FILE.read_text(encoding="utf-8")
    tree = ast.parse(src)
    forbidden_modules = {"random", "time", "datetime", "uuid", "secrets"}
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            assert not {a.name.split(".")[0] for a in n.names} & forbidden_modules, (
                f"node imports a non-determinism module: {forbidden_modules}"
            )
        elif isinstance(n, ast.ImportFrom) and n.module:
            assert n.module.split(".")[0] not in forbidden_modules, (
                f"node imports a non-determinism module: {n.module}"
            )
    # Also no hash() / now()/randrange/choice call sites as bare names.
    for forbidden in ("hash(", ".now()", "randrange", ".choice(", ".random()"):
        assert forbidden not in src, f"node source contains non-deterministic token '{forbidden}'"


# ---------------------------------------------------------------------------
# Shape discipline — EXACTLY {id, priority, plan, status}; no timestamp; AD-4 single key
# ---------------------------------------------------------------------------


def test_each_item_has_exactly_four_keys() -> None:
    """Shape: every item is EXACTLY {id, priority, plan, status} — no invented keys, no timestamp."""
    node = build_hypothesis_planner(
        _static_source(
            {"priority": 1, "plan": {"a": 1}, "status": "proposed"},
            {"priority": 2, "plan": {"b": 2}, "status": "proposed"},
        )
    )
    for h in _hypotheses_of(node(_state())):
        assert set(h.keys()) == {"id", "priority", "plan", "status"}


def test_items_have_no_timestamp_field() -> None:
    """AD-12/shape: NO timestamp field in hypothesis items (AST dict-key scan + runtime check)."""
    node = build_hypothesis_planner(
        _static_source({"priority": 1, "plan": {"a": 1}, "status": "proposed"})
    )
    for h in _hypotheses_of(node(_state())):
        for key in h:
            assert key not in ("created_at", "planned_at", "ts", "timestamp", "at", "retrieved_at")
    # AST-exact: the node constructs NO dict-literal whose key is a timestamp field name.
    tree = ast.parse(NODE_FILE.read_text(encoding="utf-8"))
    forbidden_keys = {"created_at", "planned_at", "ts", "timestamp", "at", "retrieved_at"}
    constructed: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Dict):
            for k in n.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    constructed.add(k.value)
    assert not (constructed & forbidden_keys), (
        f"node constructs a dict with a forbidden timestamp key: {constructed & forbidden_keys}"
    )


def test_plan_is_jsonsafe_dict() -> None:
    """Shape/AD-9: plan is a JSON-safe dict (the claim rides inside it; forward-compatible w/ 3.5)."""
    node = build_hypothesis_planner(
        _static_source(
            {"priority": 1, "plan": {"tool": "prom", "query": "up"}, "status": "proposed"}
        )
    )
    for h in _hypotheses_of(node(_state())):
        assert isinstance(h["plan"], dict)
    # Whole hypotheses batch round-trips json.dumps (AD-9 JSON-safe).
    result = node(_state())
    assert json.loads(json.dumps(result)) == result


def test_missing_descriptor_fields_get_deterministic_defaults() -> None:
    """Shape: a descriptor missing priority/plan/status → node fills deterministic defaults (4 keys)."""
    node = build_hypothesis_planner(_static_source({}))  # empty descriptor
    h = _hypotheses_of(node(_state()))[0]
    assert set(h.keys()) == {"id", "priority", "plan", "status"}
    assert h["id"] == "H01"
    assert h["plan"] == {}
    # priority/status are the deterministic POC defaults (values deferred, but stable).
    assert h["priority"] is not None
    assert isinstance(h["status"], str) and h["status"]


def test_descriptor_extra_keys_are_stripped() -> None:
    """Shape: extra descriptor keys (e.g. a stray 'claim'/'timestamp') are NOT forwarded."""
    node = build_hypothesis_planner(
        _static_source(
            {"priority": 1, "plan": {"a": 1}, "status": "proposed", "claim": "x", "junk": 9}
        )
    )
    h = _hypotheses_of(node(_state()))[0]
    assert set(h.keys()) == {"id", "priority", "plan", "status"}
    assert "claim" not in h and "junk" not in h


def test_node_returns_exactly_one_key() -> None:
    """AD-4: PARTIAL return — EXACTLY {"hypotheses": ...} (no evidence/plan/context invention)."""
    node = build_hypothesis_planner(
        _static_source({"priority": 1, "plan": {"a": 1}, "status": "proposed"})
    )
    result = node(_state())
    assert set(result.keys()) == {"hypotheses"}
    for forbidden in (
        "evidence",
        "playbook_hits",
        "context",
        "tool_calls",
        "report",
        "next_action",
    ):
        assert forbidden not in result


# ---------------------------------------------------------------------------
# Constraint 5 — graceful degrade: never raises
# ---------------------------------------------------------------------------


def test_empty_inputs_yield_empty_hypotheses() -> None:
    """Constraint 5: no playbook_hits/evidence/context → default source emits [] → never raises."""
    node = build_hypothesis_planner()  # default source: [] when no playbook hits
    result = node(_state(playbook_hits=[], evidence=[], context={}))
    assert result == {"hypotheses": []}


def test_source_raise_degrades_to_empty() -> None:
    """Constraint 5: an injected source that raises → {"hypotheses": []}, NEVER raises into graph."""
    node = build_hypothesis_planner(_raising_source())
    result = node(_state())  # must not raise
    assert result == {"hypotheses": []}


def test_source_returning_non_list_degrades_to_empty() -> None:
    """Constraint 5: a source returning a non-list → {"hypotheses": []} (no crash)."""

    def _bad(
        context: Mapping[str, JsonValue],  # noqa: ARG001
        playbook_hits: Sequence[Mapping[str, JsonValue]],  # noqa: ARG001
        evidence: Sequence[Mapping[str, JsonValue]],  # noqa: ARG001
    ) -> list[dict[str, JsonValue]]:
        return cast(list[dict[str, JsonValue]], "not-a-list")

    node = build_hypothesis_planner(_bad)
    assert node(_state()) == {"hypotheses": []}


def test_missing_state_keys_degrade_without_raising() -> None:
    """Constraint 5: missing context/playbook_hits/evidence keys → empty hypotheses, no raise."""
    node = build_hypothesis_planner()  # default source
    state = create_initial_state()  # no context / playbook_hits / evidence at all
    assert node(state) == {"hypotheses": []}


def test_malformed_state_never_raises() -> None:
    """Constraint 5 smoke: wrong-typed context/playbook_hits/evidence → a dict, never an exception."""
    node = build_hypothesis_planner()
    bad_states: tuple[dict[str, object], ...] = (
        {**dict(create_initial_state()), "context": "not-a-dict"},
        {**dict(create_initial_state()), "playbook_hits": "not-a-list"},
        {**dict(create_initial_state()), "evidence": 123},
    )
    for bad in bad_states:
        out = node(cast(InvestigationState, bad))
        assert isinstance(out, dict) and set(out.keys()) == {"hypotheses"}


# ---------------------------------------------------------------------------
# Read-only (AD-3) — pure planning node (NO tools/adapters/models; NO adapter call)
# ---------------------------------------------------------------------------


def test_node_imports_only_graph_and_stdlib_no_tools_port() -> None:
    """AD-1 (CRITICAL vs 3-1): node imports graph.state + stdlib ONLY; NO tools.port forward edge."""
    tree = ast.parse(NODE_FILE.read_text(encoding="utf-8"))
    forbidden = {"routers", "services", "adapters", "models", "tools"}
    roots: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods = {a.name.split(".")[0] for a in n.names}
            roots |= mods
            assert not (mods & forbidden), f"node imports a forbidden layer: {mods & forbidden}"
        elif isinstance(n, ast.ImportFrom) and n.module:
            root = n.module.split(".")[0]
            roots.add(root)
            assert root not in forbidden, f"node imports a forbidden layer: {root}"
    assert "graph" in roots  # graph.state (same layer)
    assert "tools" not in roots  # CRITICAL difference from 3-1: NO tools.port forward edge


def test_node_import_roots_subset_future_graph_stdlib() -> None:
    """AD-1: every import root is in {__future__, graph, stdlib} (typing, collections.abc)."""
    tree = ast.parse(NODE_FILE.read_text(encoding="utf-8"))
    allowed = {"__future__", "graph", "typing", "collections"}
    roots: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            roots |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            roots.add(n.module.split(".")[0])
    assert roots <= allowed, f"node has disallowed import roots: {roots - allowed}"


def test_node_has_no_write_path_or_evidence_or_router() -> None:
    """AD-3 + 4.x boundary: no write/exec primitives; no Evidence; no executor_router/registry."""
    src = NODE_FILE.read_text(encoding="utf-8")
    for forbidden in ("subprocess", "os.system", "os.exec", "requests.", "open(", "kubectl"):
        assert forbidden not in src, f"node source contains forbidden token '{forbidden}'"
    assert "Evidence(" not in src
    tree = ast.parse(src)
    forbidden_modules = {"tools.router", "tools.registry", "tools.port", "adapters"}
    forbidden_names = {
        "executor_router",
        "ExecutorRouter",
        "ReadOnlyRegistry",
        "ReadOnlyAdapterPort",
    }
    bound: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module in forbidden_modules:
            raise AssertionError(f"node imports forbidden module '{n.module}'")
        if isinstance(n, ast.ImportFrom):
            bound |= {a.asname or a.name for a in n.names}
        elif isinstance(n, ast.Import):
            bound |= {a.asname or a.name.split(".")[0] for a in n.names}
    assert not (bound & forbidden_names), f"node binds a forbidden name: {bound & forbidden_names}"


# ---------------------------------------------------------------------------
# DI seam — factory closes over source + max_hypotheses; two factories independent
# ---------------------------------------------------------------------------


def test_factory_closes_over_source_two_factories_independent() -> None:
    """DI seam: two factories with different sources are independent."""
    a = build_hypothesis_planner(
        _static_source({"priority": 1, "plan": {"a": 1}, "status": "proposed"})
    )
    b = build_hypothesis_planner(
        _static_source({"priority": 1, "plan": {"b": 2}, "status": "proposed"})
    )
    ra = _hypotheses_of(a(_state()))
    rb = _hypotheses_of(b(_state()))
    assert ra[0]["plan"] == {"a": 1}
    assert rb[0]["plan"] == {"b": 2}
    assert ra[0]["id"] == "H01" and rb[0]["id"] == "H01"  # ids are per-node-enumeration


def test_max_hypotheses_caps_output() -> None:
    """DI seam: max_hypotheses caps the emitted list (mechanism locked; number deferred)."""
    descriptors: list[dict[str, JsonValue]] = [
        {"priority": i, "plan": {"i": i}, "status": "proposed"} for i in range(10)
    ]
    node = build_hypothesis_planner(_static_source(*descriptors), max_hypotheses=3)
    hs = _hypotheses_of(node(_state()))
    assert [h["id"] for h in hs] == ["H01", "H02", "H03"]


def test_default_source_derives_one_hypothesis_per_playbook_hit() -> None:
    """Default deterministic source: each playbook hint → one hypothesis (FR-3 hints → plans)."""
    node = build_hypothesis_planner()  # default rule-based source
    hs = _hypotheses_of(node(_state(playbook_hits=_hits(2))))
    assert len(hs) == 2
    assert hs[0]["id"] == "H01" and hs[1]["id"] == "H02"
    # The plan references the playbook (non-inventing — forwards the retriever's hit only).
    assert _plan_of(hs[0])["playbook_id"] == "pb-0"
    assert hs[0]["status"] == "proposed"


def test_default_source_ignores_non_mapping_hits() -> None:
    """Default source is defensive: non-Mapping playbook hits contribute nothing (no crash)."""
    node = build_hypothesis_planner()
    state = _state(playbook_hits=[{"id": "pb-0", "title": "T"}, "not-a-dict", 123])  # type: ignore[list-item]
    hs = _hypotheses_of(node(state))
    assert len(hs) == 1  # only the one valid Mapping hit
    assert _plan_of(hs[0])["playbook_id"] == "pb-0"
