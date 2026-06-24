"""tests for graph.nodes.reflector — Story 4.3 (DEC-3 / AD-7 / AD-12 / FR-7 / AC1-AC4).

Covers the DEEP-review spotlights for the §3.5 REF node:
  - **DEC-3 (decisive / anti-hallucination)**: floor-Fail → gather_more; the ``confidence_assessor``
    is NEVER invoked on floor-Fail (a spy records call-count == 0); ``ceiling_confidence``/
    ``categorical`` are ``None``; NEVER ``write``. No RC without passing the deterministic floor.
  - **AC2 ceiling**: floor-Pass → assessor confidence in ``[0,1]`` (AD-7) + categorical ``{low|med|high}``
    + routing ``write`` (ceiling >= write_threshold) / ``replan`` (ceiling <) — boundary + both sides.
  - **AC3 max-iter→partial**: a gather_more loop to the recursion cap → ``status="partial"`` carrying
    the reflector's last ``sufficiency.gap`` ("chưa đủ") — NOT a silent binary ``status="failed"``
    (FR-7 / AD-10 #5).
  - **AC4 / D4 no-hardcoded-threshold**: ZERO bare numeric literals in any function body (AST-scanned);
    every threshold/band/bound is a named module-level CONSTANT.
  - **AD-12 determinism**: same inputs → identical verdict + next_action, incl. PYTHONHASHSEED
    cross-process (fresh interpreters, several seeds → identical JSON).
  - **Constraint 5 never-raise**: malformed state / non-list evidence / raising assessor / non-float /
    bool / out-of-range / raising mapping → deterministic degrade, NEVER an exception.
  - **AD-1 layer purity (AST)**: imports ⊆ {graph, stdlib, typing}; ZERO forbidden roots; ZERO forbidden
    attr calls (``.now``/``.open``/``.sleep``/``.randint``/...).

AD-1 note: this test file imports ``graph.compiled`` + ``graph.floor_check`` + ``graph.nodes.reflector``
— tests are CONSUMERS (outside ``root_packages``; the import-linter contract governs production modules
only). The reflector NODE itself imports {graph, stdlib, typing} ONLY (AST-asserted below). Read-only
(AD-3) is enforced at CI gate #1; the node has no adapter/tool in scope (proven by the import-purity
test — it cannot call one).

AST-discipline (docstring-immune): assertions are statement-level.
"""

from __future__ import annotations

import ast
import asyncio
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

from graph.compiled import (
    NA_GATHER_MORE,
    NA_PROCEED,
    NA_REPLAN,
    NA_WRITE,
    CompiledGraphRunner,
    build_compiled_graph,
)
from graph.floor_check import (
    FloorChecker,
    FloorResult,
    build_default_floor_check,
    build_floor_check,
    load_floor_registry,
)
from graph.nodes.reflector import (
    DEFAULT_WRITE_THRESHOLD,
    ConfidenceAssessor,
    build_reflector,
    default_categorical_mapping,
    default_deterministic_confidence_assessor,
)
from graph.state import InvestigationState, JsonValue, create_initial_state

# AD-1 note: tests are CONSUMERS (outside root_packages) — importing graph.* is fine. The reflector
# NODE's import surface is AST-asserted below (⊆ {graph, stdlib, typing}).

_REFLECTOR_PATH = Path("graph/nodes/reflector.py")
_REFLECTOR_SRC = _REFLECTOR_PATH.read_text(encoding="utf-8")
_REFLECTOR_TREE = ast.parse(_REFLECTOR_SRC)

# A registry with ONE floor rule: DependencyTimeout PASSES when >=2 prometheus/checkout evidence match.
_REG_CHECKER: FloorChecker = build_floor_check(
    registry=load_floor_registry(
        {
            "DependencyTimeout": {
                "min_count": 2,
                "source_type": "prometheus",
                "matcher": {"field": "source_name", "op": "label-exact", "value": "checkout"},
            }
        }
    )
)

_TRIGGER_DEP: dict[str, JsonValue] = {"canonical_trigger": "DependencyTimeout"}
_TRIGGER_OTHER: dict[str, JsonValue] = {"canonical_trigger": "PodCrashLooping"}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _state(
    *,
    trigger: dict[str, JsonValue] | None = None,
    evidence: list[dict[str, JsonValue]] | None = None,
) -> InvestigationState:
    state = create_initial_state()
    state["trigger"] = trigger if trigger is not None else _TRIGGER_DEP
    if evidence is not None:
        state["evidence"] = evidence
    return state


def _prom_evidence(name: str = "checkout") -> dict[str, JsonValue]:
    """A prometheus/checkout evidence item that MATCHES the registry floor rule."""
    return {"source_type": "prometheus", "source_name": name, "query": "up", "summary": "s"}


def _pass_checker(matched: int = 2, min_count: int = 1, reason: str = "pass") -> FloorChecker:
    def _check(canonical_trigger: str, evidence: Sequence[Mapping[str, object]]) -> FloorResult:
        del canonical_trigger, evidence
        return FloorResult(True, matched, min_count, reason)

    return _check


def _fail_checker(
    matched: int = 0, min_count: int = 1, reason: str = "fail-closed: unknown-trigger"
) -> FloorChecker:
    def _check(canonical_trigger: str, evidence: Sequence[Mapping[str, object]]) -> FloorResult:
        del canonical_trigger, evidence
        return FloorResult(False, matched, min_count, reason)

    return _check


def _assessor(value: float) -> ConfidenceAssessor:
    def _assess(evidence: Sequence[Mapping[str, object]]) -> float:
        del evidence
        return value

    return _assess


class _SpyAssessor:
    """Counts assessor invocations — DEC-3 proof that call-count == 0 on floor-Fail."""

    def __init__(self) -> None:
        self.calls: int = 0

    def __call__(self, evidence: Sequence[Mapping[str, object]]) -> float:
        del evidence
        self.calls += 1
        return 0.9


# ---------------------------------------------------------------------------
# AC1 — DEC-3: floor-Fail → gather_more; ceiling NEVER consulted; NO RC conclusion
# ---------------------------------------------------------------------------


def test_ac1_floor_fail_routes_gather_more() -> None:
    node = build_reflector(floor_checker=_fail_checker())
    out = node(_state())
    assert out["next_action"] == NA_GATHER_MORE == "gather_more"


def test_ac1_floor_fail_ceiling_never_consulted_spy_count_zero() -> None:
    """DEC-3 decisive: the assessor is NOT invoked on floor-Fail (spy call-count == 0)."""
    spy = _SpyAssessor()
    node = build_reflector(floor_checker=_fail_checker(), confidence_assessor=spy)
    node(_state())
    assert spy.calls == 0


def test_ac1_floor_fail_verdict_shape_and_no_write() -> None:
    """floor-Fail verdict: ceiling_confidence/categorical None; gap populated; NEVER write."""
    node = build_reflector(
        floor_checker=_fail_checker(matched=1, min_count=3, reason="fail: matched 1 < min_count 3")
    )
    out = node(_state())
    suff = cast(dict[str, JsonValue], out["sufficiency"])
    assert suff["floor_pass"] is False
    assert suff["ceiling_confidence"] is None  # DEC-3: ceiling NOT consulted
    assert suff["categorical"] is None  # DEC-3: no categorical without a ceiling
    assert suff["matched_count"] == 1
    assert suff["min_count"] == 3
    assert suff["floor_reason"] == "fail: matched 1 < min_count 3"
    gap = suff["gap"]
    assert isinstance(gap, str) and gap  # populated IFF floor-Fail (FR-7 honest)
    assert "chưa đủ" in gap
    assert out["next_action"] != NA_WRITE  # DEC-3: NEVER write on floor-Fail


# ---------------------------------------------------------------------------
# AC2 — ceiling: floor-Pass → confidence + categorical + routing
# ---------------------------------------------------------------------------


def test_ac2_floor_pass_high_confidence_routes_write() -> None:
    node = build_reflector(floor_checker=_pass_checker(), confidence_assessor=_assessor(0.9))
    out = node(_state())
    suff = cast(dict[str, JsonValue], out["sufficiency"])
    assert suff["floor_pass"] is True
    assert suff["ceiling_confidence"] == 0.9
    assert suff["categorical"] == "high"
    assert suff["gap"] is None  # no gap on floor-Pass
    assert out["next_action"] == NA_WRITE


def test_ac2_floor_pass_low_confidence_routes_replan() -> None:
    node = build_reflector(floor_checker=_pass_checker(), confidence_assessor=_assessor(0.2))
    out = node(_state())
    suff = cast(dict[str, JsonValue], out["sufficiency"])
    assert suff["ceiling_confidence"] == 0.2
    assert suff["categorical"] == "low"
    assert out["next_action"] == NA_REPLAN


def test_ac2_write_threshold_boundary_is_inclusive() -> None:
    """ceiling == write_threshold → write (>=); just-below → replan."""
    node_at = build_reflector(
        floor_checker=_pass_checker(), confidence_assessor=_assessor(DEFAULT_WRITE_THRESHOLD)
    )
    assert node_at(_state())["next_action"] == NA_WRITE
    node_below = build_reflector(
        floor_checker=_pass_checker(), confidence_assessor=_assessor(0.69), write_threshold=0.7
    )
    assert node_below(_state())["next_action"] == NA_REPLAN


def test_ac2_custom_write_threshold_from_factory_param() -> None:
    """AC4: write_threshold comes from the factory param (config), NOT a hardcoded literal."""
    node = build_reflector(
        floor_checker=_pass_checker(), confidence_assessor=_assessor(0.5), write_threshold=0.5
    )
    assert node(_state())["next_action"] == NA_WRITE  # 0.5 >= 0.5


# ---------------------------------------------------------------------------
# categorical bands (default mapping) + default assessor (AD-7 / AD-12 / AC4)
# ---------------------------------------------------------------------------


def test_categorical_band_boundaries() -> None:
    assert default_categorical_mapping(0.39) == "low"
    assert default_categorical_mapping(0.4) == "med"  # < 0.4 is low → 0.4 is med
    assert default_categorical_mapping(0.69) == "med"
    assert default_categorical_mapping(0.7) == "high"  # < 0.7 is med → 0.7 is high
    assert default_categorical_mapping(0.99) == "high"


def test_default_assessor_monotonic_bounded_and_saturating() -> None:
    """AD-7/AD-12: default assessor is bounded [0,1], monotonic, saturating (count-based)."""
    assert default_deterministic_confidence_assessor([]) == 0.0
    assert default_deterministic_confidence_assessor([_prom_evidence()]) == 0.25
    four = [_prom_evidence() for _ in range(4)]
    assert default_deterministic_confidence_assessor(four) == 1.0
    ten = [_prom_evidence() for _ in range(10)]
    assert default_deterministic_confidence_assessor(ten) == 1.0  # saturated


# ---------------------------------------------------------------------------
# real floor_check integration — canonical_trigger reading + DEC-3 end-to-end
# ---------------------------------------------------------------------------


def test_real_floor_pass_with_enough_evidence() -> None:
    """2 matching prometheus/checkout evidence → floor PASS → ceiling consulted → write."""
    node = build_reflector(floor_checker=_REG_CHECKER, confidence_assessor=_assessor(0.9))
    out = node(_state(evidence=[_prom_evidence(), _prom_evidence()]))
    suff = cast(dict[str, JsonValue], out["sufficiency"])
    assert suff["floor_pass"] is True
    assert suff["matched_count"] == 2
    assert suff["min_count"] == 2
    assert suff["ceiling_confidence"] == 0.9
    assert out["next_action"] == NA_WRITE


def test_real_floor_fail_insufficient_evidence_routes_gather_more() -> None:
    """1 matching evidence (min 2) → floor FAIL → gather_more; ceiling NEVER consulted (spy==0)."""
    spy = _SpyAssessor()
    node = build_reflector(floor_checker=_REG_CHECKER, confidence_assessor=spy)
    out = node(_state(evidence=[_prom_evidence()]))
    suff = cast(dict[str, JsonValue], out["sufficiency"])
    assert suff["floor_pass"] is False
    assert suff["ceiling_confidence"] is None
    assert suff["matched_count"] == 1
    assert suff["min_count"] == 2
    assert out["next_action"] == NA_GATHER_MORE
    assert spy.calls == 0  # DEC-3: ceiling not consulted on floor-Fail


def test_real_floor_unknown_trigger_fail_closed() -> None:
    """A trigger with no registry entry → fail-closed → gather_more (anti-hallucination)."""
    node = build_reflector(floor_checker=_REG_CHECKER, confidence_assessor=_assessor(0.99))
    out = node(_state(trigger=_TRIGGER_OTHER, evidence=[_prom_evidence(), _prom_evidence()]))
    suff = cast(dict[str, JsonValue], out["sufficiency"])
    assert suff["floor_pass"] is False
    assert "fail-closed" in cast(str, suff["floor_reason"])
    assert out["next_action"] == NA_GATHER_MORE


def test_canonical_trigger_read_defensively_missing_trigger() -> None:
    """missing/empty trigger → canonical_trigger '' → fail-closed (3.1/3.4 precedent)."""
    node = build_reflector(floor_checker=_REG_CHECKER)
    out = node(create_initial_state())  # trigger == {} (empty)
    suff = cast(dict[str, JsonValue], out["sufficiency"])
    assert suff["floor_pass"] is False
    assert "fail-closed" in cast(str, suff["floor_reason"])


def test_canonical_trigger_read_defensively_non_str() -> None:
    """non-str canonical_trigger → '' → fail-closed (defensive; never raises)."""
    state = create_initial_state()
    state["trigger"] = cast(dict[str, JsonValue], {"canonical_trigger": 123})
    node = build_reflector(floor_checker=_REG_CHECKER)
    out = node(state)
    suff = cast(dict[str, JsonValue], out["sufficiency"])
    assert suff["floor_pass"] is False


# ---------------------------------------------------------------------------
# Constraint 5 — never-raise (deterministic degrade)
# ---------------------------------------------------------------------------


def test_constraint5_default_state_does_not_raise() -> None:
    node = build_reflector(floor_checker=_fail_checker())
    out = node(create_initial_state())
    assert isinstance(out, dict)
    assert "next_action" in out and "sufficiency" in out


def test_constraint5_non_list_evidence_does_not_raise() -> None:
    node = build_reflector(floor_checker=_REG_CHECKER)
    # A plain dict (not the TypedDict) so a non-list ``evidence`` is type-clean; cast at the call.
    malformed = dict(create_initial_state(trigger=_TRIGGER_DEP))
    malformed["evidence"] = "not-a-list"  # malformed on purpose
    out = node(cast(InvestigationState, malformed))
    assert isinstance(out["sufficiency"], dict)
    assert out["next_action"] == NA_GATHER_MORE  # fail-closed over no items


def test_constraint5_non_mapping_evidence_items_skipped() -> None:
    node = build_reflector(floor_checker=_REG_CHECKER)
    state = _state(
        evidence=[cast(dict[str, JsonValue], "str-item"), _prom_evidence()]
    )  # 1 valid of min 2
    out = node(state)
    suff = cast(dict[str, JsonValue], out["sufficiency"])
    assert suff["floor_pass"] is False  # only 1 valid item → < 2


def test_constraint5_raising_assessor_degrades_to_floor() -> None:
    def _boom(evidence: Sequence[Mapping[str, object]]) -> float:
        raise RuntimeError("assessor boom")

    node = build_reflector(floor_checker=_pass_checker(), confidence_assessor=_boom)
    out = node(_state())
    suff = cast(dict[str, JsonValue], out["sufficiency"])
    assert suff["ceiling_confidence"] == 0.0  # degraded to the confidence floor
    assert out["next_action"] == NA_REPLAN  # 0.0 < write_threshold


def test_constraint5_non_float_assessor_degrades() -> None:
    def _str(evidence: Sequence[Mapping[str, object]]) -> float:
        return "not-a-float"  # type: ignore[return-value]

    node = build_reflector(floor_checker=_pass_checker(), confidence_assessor=_str)
    suff = cast(dict[str, JsonValue], node(_state())["sufficiency"])
    assert suff["ceiling_confidence"] == 0.0


def test_constraint5_bool_assessor_rejected() -> None:
    """bool is an int subclass — True must NOT silently read as confidence 1.0."""

    def _bool(evidence: Sequence[Mapping[str, object]]) -> float:
        return True  # bool ⊂ int ⊂ float (mypy's numeric tower accepts this); RUNTIME rejects it.

    node = build_reflector(floor_checker=_pass_checker(), confidence_assessor=_bool)
    suff = cast(dict[str, JsonValue], node(_state())["sufficiency"])
    assert suff["ceiling_confidence"] == 0.0  # bool rejected → floor


def test_constraint5_out_of_range_assessor_clamped_high() -> None:
    def _hi(evidence: Sequence[Mapping[str, object]]) -> float:
        return 1.5  # > 1.0 → clamp

    node = build_reflector(floor_checker=_pass_checker(), confidence_assessor=_hi)
    out = node(_state())
    suff = cast(dict[str, JsonValue], out["sufficiency"])
    assert suff["ceiling_confidence"] == 1.0  # clamped to the ceiling
    assert out["next_action"] == NA_WRITE


def test_constraint5_negative_assessor_clamped_to_floor() -> None:
    def _neg(evidence: Sequence[Mapping[str, object]]) -> float:
        return -0.5  # < 0.0 → clamp

    node = build_reflector(floor_checker=_pass_checker(), confidence_assessor=_neg)
    suff = cast(dict[str, JsonValue], node(_state())["sufficiency"])
    assert suff["ceiling_confidence"] == 0.0


def test_constraint5_raising_mapping_degrades_to_unknown() -> None:
    def _boom(confidence: float) -> str:
        raise RuntimeError("mapping boom")

    node = build_reflector(
        floor_checker=_pass_checker(),
        confidence_assessor=_assessor(0.9),
        categorical_mapping=_boom,
    )
    out = node(_state())
    suff = cast(dict[str, JsonValue], out["sufficiency"])
    assert suff["categorical"] == "unknown"  # degraded
    assert out["next_action"] == NA_WRITE  # routing uses the NUMERIC ceiling, not the label


def test_constraint5_non_str_mapping_degrades_to_unknown() -> None:
    def _int(confidence: float) -> str:
        return 42  # type: ignore[return-value]

    node = build_reflector(
        floor_checker=_pass_checker(),
        confidence_assessor=_assessor(0.9),
        categorical_mapping=_int,
    )
    suff = cast(dict[str, JsonValue], node(_state())["sufficiency"])
    assert suff["categorical"] == "unknown"


# ---------------------------------------------------------------------------
# AD-12 determinism
# ---------------------------------------------------------------------------


def test_determinism_same_inputs_identical_verdict_in_process() -> None:
    node = build_reflector(floor_checker=_REG_CHECKER, confidence_assessor=_assessor(0.85))
    state = _state(evidence=[_prom_evidence(), _prom_evidence()])
    assert node(state) == node(state)


def test_determinism_order_independent_evidence() -> None:
    """count-based floor + assessor → the SAME evidence SET in any order → identical verdict."""
    node = build_reflector(
        floor_checker=_REG_CHECKER, confidence_assessor=default_deterministic_confidence_assessor
    )
    ev_a: list[dict[str, JsonValue]] = [
        {"source_type": "prometheus", "source_name": "checkout", "query": "q1"},
        {"source_type": "prometheus", "source_name": "checkout", "query": "q2"},
    ]
    ev_b: list[dict[str, JsonValue]] = list(reversed(ev_a))
    assert node(_state(evidence=ev_a)) == node(_state(evidence=ev_b))


_XPROC_SCRIPT = (
    "import json; "
    "from graph.nodes.reflector import build_reflector; "
    "from graph.floor_check import FloorResult; "
    "fc = lambda t, e: FloorResult(True, 2, 1, 'pass'); "
    "state = {'trigger': {'canonical_trigger': 'DependencyTimeout'}, "
    "'evidence': [{'source_type': 'prometheus'}, {'source_type': 'loki'}]}; "
    "print(json.dumps(build_reflector(floor_checker=fc)(state), sort_keys=True))"
)


def _xproc_output(seed: int) -> str:
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = str(seed)
    proc = subprocess.run(
        [sys.executable, "-c", _XPROC_SCRIPT],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(Path(__file__).resolve().parent.parent),
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, f"xproc seed={seed} failed:\n{proc.stderr}"
    return proc.stdout.strip()


def test_determinism_pythonhashseed_cross_process() -> None:
    """AD-12: identical verdict across fresh interpreters under different PYTHONHASHSEED values."""
    base = _xproc_output(0)
    for seed in (1, 7, 42, 99):
        assert _xproc_output(seed) == base, f"PYTHONHASHSEED drift at seed={seed}"


# ---------------------------------------------------------------------------
# AD-1 layer purity + AC4/D4 no-hardcoded-threshold (AST)
# ---------------------------------------------------------------------------


def test_layer_purity_imports_only_graph_stdlib_typing() -> None:
    """AD-1: reflector imports ⊆ {graph, collections, typing, __future__} — ZERO back-edges/yaml/models."""
    roots: set[str] = set()
    for node in ast.walk(_REFLECTOR_TREE):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                roots.add(node.module.split(".")[0])
    allowed = {"graph", "collections", "typing", "__future__"}
    assert roots <= allowed, f"forbidden import roots in reflector: {roots - allowed}"


def test_layer_purity_no_forbidden_attr_calls() -> None:
    """AD-12: no LLM/clock/random/IO — ZERO forbidden attribute calls in the reflector."""
    forbidden = {
        "now",
        "today",
        "strftime",
        "sleep",
        "random",
        "randint",
        "uniform",
        "uuid4",
        "uuid1",
        "open",
        "read_text",
        "write",
        "loads",
        "dumps",
        "request",
    }
    found: list[tuple[object, str]] = []
    for node in ast.walk(_REFLECTOR_TREE):
        if isinstance(node, ast.Attribute) and node.attr in forbidden:
            found.append((getattr(node, "lineno", "?"), node.attr))
    assert not found, f"forbidden attr calls in reflector: {found}"


def _module_level_numeric_const_ids(tree: ast.Module) -> set[int]:
    """The id() of every numeric (int/float, non-bool) Constant that is the direct value of a
    module-level assignment — i.e. the ALLOWED named constants (the config). Covers BOTH plain
    ``ast.Assign`` (``X = 0.7``) and annotated ``ast.AnnAssign`` (``X: float = 0.7``); the reflector's
    POC-default constants are all annotated, so both forms must be recognized as module-level."""
    allowed: set[int] = set()
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign | ast.AnnAssign) and isinstance(stmt.value, ast.Constant):
            value = stmt.value.value
            if isinstance(value, int | float) and not isinstance(value, bool):
                allowed.add(id(stmt.value))
    return allowed


def test_ac4_no_inline_numeric_threshold_literals() -> None:
    """AC4/D4: ZERO bare numeric (int/float, non-bool) literals inside function bodies — every
    threshold/band/bound is a module-level CONSTANT referenced by name (module-level assigns allowed)."""
    allowed = _module_level_numeric_const_ids(_REFLECTOR_TREE)
    offenders: list[tuple[object, object]] = []
    for node in ast.walk(_REFLECTOR_TREE):
        if isinstance(node, ast.Constant):
            value = node.value
            if (
                isinstance(value, int | float)
                and not isinstance(value, bool)
                and id(node) not in allowed
            ):
                offenders.append((getattr(node, "lineno", "?"), value))
    assert not offenders, (
        f"inline numeric literals in reflector logic (must be named constants): {offenders}"
    )


# ---------------------------------------------------------------------------
# AC3 — max-iter→partial (FR-7 / AD-10 #5): gather_more loop to cap → PARTIAL carrying the gap
# ---------------------------------------------------------------------------


def _noop_node(state: InvestigationState) -> dict[str, JsonValue]:
    del state
    return {}


def _val_proceed_node(state: InvestigationState) -> dict[str, JsonValue]:
    del state
    return {"next_action": NA_PROCEED}


def _looping_reflector_runner() -> CompiledGraphRunner:
    """A runner whose loop ALWAYS reaches REF then gather_more-loops (fail-closed floor) → cap → PARTIAL."""
    reflector = build_reflector(
        floor_checker=build_default_floor_check()
    )  # empty registry → fail-closed
    graph = build_compiled_graph(
        incident_context_builder=_noop_node,
        preplanning_playbook_retriever=_noop_node,
        hypothesis_planner=_noop_node,
        plan_validator=_val_proceed_node,
        executor_router=_noop_node,
        evidence_normalizer=_noop_node,
        reflector=reflector,
        rca_writer=_noop_node,
    )
    return CompiledGraphRunner(graph)


def test_ac3_max_iter_exhaustion_is_partial_carrying_gap() -> None:
    """A gather_more loop to the recursion cap → status="partial" carrying the reflector's last gap
    (NOT a silent binary status="failed" — FR-7 / AD-10 #5)."""
    runner = _looping_reflector_runner()
    result = asyncio.run(runner.run(_TRIGGER_DEP, "inv-ac3", max_iterations=2))
    assert result["status"] == "partial"
    assert result["report"] is None
    snap = result["state_snapshot"]
    suff = snap.get("sufficiency")
    assert isinstance(suff, dict)
    assert suff.get("floor_pass") is False  # the reflector ran + wrote a failing verdict
    assert suff.get("ceiling_confidence") is None  # DEC-3: ceiling not consulted on floor-Fail
    gap = suff.get("gap")
    assert isinstance(gap, str) and gap  # the honest "chưa đủ" gap is CARRIED
    assert "chưa đủ" in gap


# ---------------------------------------------------------------------------
# spine + routing vocabulary — single source of truth
# ---------------------------------------------------------------------------


def test_spine_unchanged_thirteen_keys() -> None:
    """4.3 adds NO spine key — the reflector writes only sufficiency + next_action (both pre-existing)."""
    assert len(InvestigationState.__annotations__) == 13


def test_next_action_vocabulary_imported_from_compiled() -> None:
    """The routing vocabulary {gather_more, replan, write} is IMPORTED from compiled (no drift)."""
    fail = build_reflector(floor_checker=_fail_checker())(_state())
    assert fail["next_action"] == NA_GATHER_MORE == "gather_more"
    write = build_reflector(floor_checker=_pass_checker(), confidence_assessor=_assessor(0.9))(
        _state()
    )
    assert write["next_action"] == NA_WRITE == "write"
    replan = build_reflector(floor_checker=_pass_checker(), confidence_assessor=_assessor(0.2))(
        _state()
    )
    assert replan["next_action"] == NA_REPLAN == "replan"
