"""Story 3.4 — fuzzy_explore (§4.3): fuzzy-aware hypothesis planning — A1 PE-R accommodate, NO ReAct.

Covers the ACs / leader DEEP spotlights (pattern-contract / graph-correctness story):
  - AC1 — A1 LOCK: PE-R only, NO ReAct. AST-exact: no ``while`` loop, no react/thought/observation/
           agent identifier in module LOGIC; docstring documents the A1 decision + the discarded
           "degrade ReAct cho fuzzy" (PRD memlog line 12); no new §3.5 node (delivers a module, not a
           node); node returns exactly ``{"hypotheses": ...}``.
  - AC2 — NO new node / edge / state-key; manifests as hypotheses entries. Spine still 14 keys (no
           fuzzy/explore key added); expansion BOUNDED (no self-recursion / no loop), capped by
           max_hypotheses; AC2 (max-iter→partial) is documented as 3.5+4.x, NOT built here.
  - AC3 — REUSE 3.2 (zero duplication): delegates id-stamping (H01..) + shape + merge to
           build_hypothesis_planner; AST-exact NO redefined _stamp_ids / NO H%02d stamping in this
           module; imports _rule_based_source + build_hypothesis_planner from 3.2.
  - AC4 — detect_fuzzy correctness + determinism: exact-token membership; None/non-str → False
           (never raises); injected fuzzy_set respected; AST-proven NO random/time/datetime/uuid.
  - AC5 — expansion behavior: fuzzy → broader exploratory set (≥2, MORE than non-fuzzy for same
           inputs); non-fuzzy → 3.2's normal set; descriptors id-less (the node stamps); capped.
  - AC6 — graceful degrade (Constraint 5): missing/non-dict trigger / non-str canonical_trigger /
           source raise / malformed state → degrade (normal path or {hypotheses:[]}), NEVER raises.
  - AC7 — AD-4 partial (exactly {hypotheses}); DI seam factory independence; AD-1 one-way (import
           roots ⊆ {__future__, graph, stdlib}; NO tools/adapters/models/routers/services).
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import TYPE_CHECKING, cast

from graph.nodes.fuzzy_explore import (
    _DEFAULT_FUZZY_SET,
    _exploratory_source,
    build_fuzzy_aware_hypothesis_planner,
    detect_fuzzy,
)
from graph.state import (
    InvestigationState,
    JsonValue,
    create_initial_state,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from graph.nodes.hypothesis_planner import HypothesisSource

NODE_FILE = Path(__file__).resolve().parents[1] / "graph" / "nodes" / "fuzzy_explore.py"

_FUZZY = "DNSFailureLogSpike"
_FUZZY2 = "CertificateErrorDetected"
_NON_FUZZY = "CrashLoopBackOff"


# ---------------------------------------------------------------------------
# Fixtures — deterministic injected sources + state helpers
# ---------------------------------------------------------------------------


def _static_source(*descriptors: dict[str, JsonValue]) -> HypothesisSource:
    """A deterministic source that always emits the given descriptors (no id — node stamps)."""
    snapshot = [dict(d) for d in descriptors]

    def _source(
        context: Mapping[str, JsonValue],  # noqa: ARG001
        playbook_hits: Sequence[Mapping[str, JsonValue]],  # noqa: ARG001
        evidence: Sequence[Mapping[str, JsonValue]],  # noqa: ARG001
    ) -> list[dict[str, JsonValue]]:
        return [dict(d) for d in snapshot]

    return _source


def _raising_source() -> HypothesisSource:
    """A source that always raises (AC6: graceful degrade on source failure)."""

    def _source(
        context: Mapping[str, JsonValue],  # noqa: ARG001
        playbook_hits: Sequence[Mapping[str, JsonValue]],  # noqa: ARG001
        evidence: Sequence[Mapping[str, JsonValue]],  # noqa: ARG001
    ) -> list[dict[str, JsonValue]]:
        raise RuntimeError("simulated source failure")

    return _source


def _state(
    *,
    canonical_trigger: JsonValue | None = None,
    with_trigger: bool = True,
    playbook_hits: list[dict[str, JsonValue]] | None = None,
    trigger_obj: dict[str, JsonValue] | None = None,
) -> InvestigationState:
    """A partial state carrying ``trigger`` (for fuzzy detection) + planner inputs.

    ``trigger_obj`` lets a test inject a malformed ``trigger`` (e.g. non-dict) directly.
    """
    state = create_initial_state()
    state["context"] = {"service": "checkout", "namespace": "demo"}
    state["playbook_hits"] = playbook_hits if playbook_hits is not None else []
    state["evidence"] = []
    if with_trigger:
        if trigger_obj is not None:
            state["trigger"] = trigger_obj
        else:
            state["trigger"] = {"canonical_trigger": canonical_trigger}
    return state


def _hypotheses_of(result: dict[str, JsonValue]) -> list[dict[str, JsonValue]]:
    """Narrow ``result["hypotheses"]`` (JsonValue) to a list for assertion (mypy-safe)."""
    hs = result["hypotheses"]
    assert isinstance(hs, list)
    return [h for h in hs if isinstance(h, dict)]


def _descs(*items: dict[str, JsonValue]) -> list[dict[str, JsonValue]]:
    return [dict(i) for i in items]


def _import_roots(src: str) -> set[str]:
    """Collect the top-level import root of every Import / ImportFrom in ``src``."""
    tree = ast.parse(src)
    roots: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for alias in n.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(n, ast.ImportFrom):
            if n.module:
                roots.add(n.module.split(".")[0])
    return roots


def _identifier_names(src: str) -> set[str]:
    """Collect lowercased Name + Attribute identifiers (docstring-immune — AST only)."""
    tree = ast.parse(src)
    names: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Name):
            names.add(n.id.lower())
        elif isinstance(n, ast.Attribute):
            names.add(n.attr.lower())
    return names


# ---------------------------------------------------------------------------
# AC1 — A1 LOCK: PE-R only, NO ReAct
# ---------------------------------------------------------------------------


def test_module_has_no_while_loop_no_react_identifiers_in_logic() -> None:
    """AC1 / spotlight #1: NO ``while`` loop + NO react/thought/observation/agent identifier in the
    module LOGIC (AST — docstring text is NOT scanned, so the docstring's discussion of the discarded
    ReAct design does NOT trip this). A1 = stay in PE-R; the expanded set is just a richer hypotheses
    list fed to the EXISTING loop."""
    src = NODE_FILE.read_text(encoding="utf-8")
    tree = ast.parse(src)
    while_loops = [n for n in ast.walk(tree) if isinstance(n, ast.While)]
    assert while_loops == [], "module must contain NO while-loop (A1 — no outer ReAct loop)"
    names = _identifier_names(src)
    forbidden = {"react", "thought", "observation", "agent"}
    hit = forbidden & names
    assert not hit, f"module must not use ReAct-loop identifiers in logic (A1), found: {hit}"


def test_module_docstring_documents_a1_and_the_discarded_react() -> None:
    """AC1: the module docstring documents the A1 decision AND the discarded 'degrade ReAct' design."""
    doc = ast.get_docstring(ast.parse(NODE_FILE.read_text(encoding="utf-8")))
    assert doc is not None
    assert "A1" in doc
    assert "ReAct" in doc
    assert "degrade ReAct" in doc or "ReAct cho fuzzy" in doc


def test_node_returns_exactly_one_key_hypotheses() -> None:
    """AC1 / AD-4: the node returns EXACTLY ``{"hypotheses": [...]}`` for both fuzzy and non-fuzzy."""
    node = build_fuzzy_aware_hypothesis_planner()
    fuzzy_result = node(_state(canonical_trigger=_FUZZY))
    non_fuzzy_result = node(_state(canonical_trigger=_NON_FUZZY))
    assert set(fuzzy_result) == {"hypotheses"}
    assert set(non_fuzzy_result) == {"hypotheses"}


def test_module_is_not_a_node_and_adds_no_graph_edge() -> None:
    """AC1: 3.4 is a graph-internal module, NOT a §3.5 node. It does NOT call StateGraph/compile/add_node
    /add_edge (graph wiring is 3.5). AST-exact: no such identifiers in module logic."""
    src = NODE_FILE.read_text(encoding="utf-8")
    names = _identifier_names(src)
    forbidden = {"stategraph", "add_node", "add_edge", "add_conditional_edges", "compile"}
    assert not (forbidden & names), (
        f"module must not do graph wiring (3.5's job): {forbidden & names}"
    )


# ---------------------------------------------------------------------------
# AC2 — NO new node / edge / state-key; manifests as hypotheses entries; bounded
# ---------------------------------------------------------------------------


def test_spine_still_has_13_keys_no_fuzzy_explore_key_added() -> None:
    """AC2: the 13-key AD-9 spine is UNCHANGED — NO fuzzy/explore key was added."""
    keys = set(InvestigationState.__annotations__)
    assert len(keys) == 13
    assert "fuzzy" not in keys and "explore" not in keys
    assert "hypotheses" in keys  # the expansion manifests HERE (existing key)


def test_expansion_is_bounded_and_does_not_recurse() -> None:
    """AC2: the expansion is a SINGLE bounded op — AST no ``while`` + no recursive call to the planner
    factory; output capped at max_hypotheses."""
    src = NODE_FILE.read_text(encoding="utf-8")
    tree = ast.parse(src)
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.While)]
    node = build_fuzzy_aware_hypothesis_planner(max_hypotheses=2)
    result = node(_state(canonical_trigger=_FUZZY))
    # Capped at 2 (the expansion POC stub emits 3 candidates; max_hypotheses bounds the node output).
    assert len(_hypotheses_of(result)) <= 2


def test_module_docstring_documents_ac2_boundary() -> None:
    """AC2 honesty: the docstring states max-iter→partial is 3.5 (1-A4) + 4.x, NOT built here."""
    doc = ast.get_docstring(ast.parse(NODE_FILE.read_text(encoding="utf-8")))
    assert doc is not None
    assert "3.5" in doc and "4.x" in doc


# ---------------------------------------------------------------------------
# AC3 — REUSE 3.2 (zero duplication): delegate id-stamping + shape + merge
# ---------------------------------------------------------------------------


def test_module_imports_reusable_seam_from_3_2() -> None:
    """AC3: the module imports build_hypothesis_planner + _rule_based_source from 3.2 (REUSED)."""
    src = NODE_FILE.read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported: set[str] = set()
    imported_from_hp = False
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module == "graph.nodes.hypothesis_planner":
            imported_from_hp = True
            imported = {a.name for a in n.names}
    assert imported_from_hp, "module must import from graph.nodes.hypothesis_planner (reuse 3.2)"
    assert {"build_hypothesis_planner", "_rule_based_source"} <= imported


def test_module_does_not_reimplement_id_stamping() -> None:
    """AC3: the module does NOT redefine _stamp_ids and does NOT stamp H%02d ids itself (delegated
    to 3.2). AST-exact: no FunctionDef named _stamp_ids; no string literal 'H%02d'."""
    src = NODE_FILE.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef):
            assert n.name != "_stamp_ids", "module must NOT redefine _stamp_ids (delegate to 3.2)"
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            assert "H%02d" not in n.value, (
                "module must NOT stamp H%02d ids itself (delegate to 3.2)"
            )


def test_ids_are_stamped_h01_by_3_2_delegation() -> None:
    """AC3: the emitted hypotheses carry 3.2-stamped sequential H01.. ids (delegated, not reinvented)."""
    node = build_fuzzy_aware_hypothesis_planner(max_hypotheses=5)
    hyps = _hypotheses_of(node(_state(canonical_trigger=_FUZZY)))
    assert [h.get("id") for h in hyps] == [f"H{i:02d}" for i in range(1, len(hyps) + 1)]
    for h in hyps:
        assert set(h) == {"id", "priority", "plan", "status"}  # 3.2's exact shape discipline


# ---------------------------------------------------------------------------
# AC4 — detect_fuzzy correctness + determinism
# ---------------------------------------------------------------------------


def test_detect_fuzzy_membership_for_named_fuzzy_examples() -> None:
    """AC4: the spec's named fuzzy examples are fuzzy."""
    assert detect_fuzzy(_FUZZY, fuzzy_set=_DEFAULT_FUZZY_SET) is True
    assert detect_fuzzy(_FUZZY2, fuzzy_set=_DEFAULT_FUZZY_SET) is True


def test_detect_fuzzy_non_member_is_not_fuzzy() -> None:
    """AC4: a non-fuzzy canonical_trigger → False."""
    assert detect_fuzzy(_NON_FUZZY, fuzzy_set=_DEFAULT_FUZZY_SET) is False
    assert detect_fuzzy("PodCrashLooping", fuzzy_set=_DEFAULT_FUZZY_SET) is False


def test_detect_fuzzy_none_and_non_str_never_raises_returns_false() -> None:
    """AC4: None / non-str → False, NEVER raises (mirrors 3.1's defensive canonical_trigger read)."""
    assert detect_fuzzy(None, fuzzy_set=_DEFAULT_FUZZY_SET) is False
    assert detect_fuzzy("", fuzzy_set=_DEFAULT_FUZZY_SET) is False
    bad: object = 123
    assert detect_fuzzy(cast("str | None", bad), fuzzy_set=_DEFAULT_FUZZY_SET) is False
    bad_list: object = ["DNSFailureLogSpike"]
    assert detect_fuzzy(cast("str | None", bad_list), fuzzy_set=_DEFAULT_FUZZY_SET) is False


def test_detect_fuzzy_respects_injected_fuzzy_set() -> None:
    """AC4: an injected fuzzy_set is respected (the SET is a factory param; mechanism locked)."""
    custom = frozenset({"FooBar", "BazQux"})
    assert detect_fuzzy("FooBar", fuzzy_set=custom) is True
    assert detect_fuzzy("BazQux", fuzzy_set=custom) is True
    assert detect_fuzzy(_FUZZY, fuzzy_set=custom) is False  # not in the custom set


def test_detect_fuzzy_is_exact_token_not_substring() -> None:
    """AC4: exact-token membership — a SUPERSTRING of a fuzzy trigger is NOT fuzzy."""
    assert detect_fuzzy("DNSFailureLogSpikeExtra", fuzzy_set=_DEFAULT_FUZZY_SET) is False
    assert detect_fuzzy("my-DNSFailureLogSpike", fuzzy_set=_DEFAULT_FUZZY_SET) is False


def test_module_is_deterministic_no_random_time_datetime_uuid() -> None:
    """AC4: AST-proven NO random/time/datetime/uuid import + NO .now/.choice/.random attribute."""
    src = NODE_FILE.read_text(encoding="utf-8")
    roots = _import_roots(src)
    assert {"random", "time", "datetime", "uuid"}.isdisjoint(roots)
    names = _identifier_names(src)
    # datetime could be referenced as an attribute; assert none of the RNG/clock primitives appear.
    assert "random" not in names and "uuid" not in names


# ---------------------------------------------------------------------------
# AC5 — expansion behavior: fuzzy → broader; non-fuzzy → 3.2 normal; id-less; capped
# ---------------------------------------------------------------------------


def test_fuzzy_trigger_emits_broader_set_than_non_fuzzy_for_same_inputs() -> None:
    """AC5: for the SAME inputs (empty playbook_hits), fuzzy → ≥2 hypotheses (the exploratory
    candidates); non-fuzzy → 3.2's normal set (0 from empty playbooks). Fuzzy is BROADER."""
    node = build_fuzzy_aware_hypothesis_planner()
    fuzzy_hyps = _hypotheses_of(node(_state(canonical_trigger=_FUZZY)))
    non_fuzzy_hyps = _hypotheses_of(node(_state(canonical_trigger=_NON_FUZZY)))
    assert len(fuzzy_hyps) >= 2
    assert len(fuzzy_hyps) > len(non_fuzzy_hyps)


def test_fuzzy_broader_even_when_playbooks_present() -> None:
    """AC5: with playbook hits, base (non-fuzzy) emits one-per-playbook; fuzzy expansion is still
    broader (≥ the exploratory candidates)."""
    node = build_fuzzy_aware_hypothesis_planner()
    hits: list[dict[str, JsonValue]] = [{"id": "pb-1", "score": 0.9, "title": "Playbook 1"}]
    fuzzy_hyps = _hypotheses_of(node(_state(canonical_trigger=_FUZZY, playbook_hits=hits)))
    non_fuzzy_hyps = _hypotheses_of(node(_state(canonical_trigger=_NON_FUZZY, playbook_hits=hits)))
    assert len(non_fuzzy_hyps) == 1  # 3.2's single-path-per-playbook default
    assert len(fuzzy_hyps) > len(non_fuzzy_hyps)


def test_non_fuzzy_uses_3_2_normal_set_referencing_playbook() -> None:
    """AC5: a non-fuzzy trigger selects the base source → 3.2's normal plan referencing the playbook."""
    node = build_fuzzy_aware_hypothesis_planner()
    hits: list[dict[str, JsonValue]] = [{"id": "pb-1", "score": 0.9, "title": "Playbook 1"}]
    hyps = _hypotheses_of(node(_state(canonical_trigger=_NON_FUZZY, playbook_hits=hits)))
    assert len(hyps) == 1
    plan = hyps[0]["plan"]
    assert isinstance(plan, dict)
    assert plan.get("playbook_id") == "pb-1"


def test_exploratory_source_emits_id_less_descriptors() -> None:
    """AC5: the expansion SOURCE emits descriptors WITHOUT id (the node stamps it via 3.2)."""
    descs = _exploratory_source(
        context={"service": "checkout"},
        playbook_hits=[],
        evidence=[],
    )
    assert len(descs) >= 2
    for d in descs:
        assert "id" not in d  # id-less — 3.2 stamps H01..
        assert "plan" in d and "priority" in d and "status" in d


def test_fuzzy_hypotheses_carry_exploratory_plan_content() -> None:
    """AC5: fuzzy hypotheses carry the exploratory candidate-root-cause plan content (POC stub)."""
    node = build_fuzzy_aware_hypothesis_planner()
    hyps = _hypotheses_of(node(_state(canonical_trigger=_FUZZY)))
    assert hyps
    for h in hyps:
        plan = h["plan"]
        assert isinstance(plan, dict)
        assert "candidate_root_cause" in plan


# ---------------------------------------------------------------------------
# AC6 — graceful degrade (Constraint 5); NEVER raises
# ---------------------------------------------------------------------------


def test_missing_trigger_key_degrades_to_normal_path_never_raises() -> None:
    """AC6: no trigger key → not fuzzy → base planner; with empty playbooks → {hypotheses:[]}."""
    node = build_fuzzy_aware_hypothesis_planner()
    state = create_initial_state()  # no trigger key at all
    result = node(state)
    assert set(result) == {"hypotheses"}
    assert _hypotheses_of(result) == []


def test_non_dict_trigger_degrades_never_raises() -> None:
    """AC6: a non-dict trigger (malformed) → not fuzzy → base → degrade, never raises."""
    node = build_fuzzy_aware_hypothesis_planner()
    result = node(_state(trigger_obj={"canonical_trigger": "x"}))  # well-formed, sanity
    assert set(result) == {"hypotheses"}
    # Malformed: trigger is a list (not a dict) → defensive read → None → not fuzzy → degrade.
    state = create_initial_state()
    bad_trigger: JsonValue = ["not", "a", "dict"]
    state["trigger"] = bad_trigger  # type: ignore[typeddict-item]
    result2 = node(state)
    assert set(result2) == {"hypotheses"}


def test_missing_or_non_str_canonical_trigger_is_not_fuzzy() -> None:
    """AC6: missing / None / non-str canonical_trigger → not fuzzy → base (normal) path."""
    node = build_fuzzy_aware_hypothesis_planner()
    for canonical in (None, "", 123):
        result = node(_state(canonical_trigger=canonical))
        assert set(result) == {"hypotheses"}  # never raises


def test_expansion_source_raise_degrades_never_raises() -> None:
    """AC6: a raising expansion_source on a fuzzy trigger → 3.2's defensive wrap → {hypotheses:[]},
    NEVER raises."""
    node = build_fuzzy_aware_hypothesis_planner(expansion_source=_raising_source())
    result = node(_state(canonical_trigger=_FUZZY))
    assert set(result) == {"hypotheses"}
    assert _hypotheses_of(result) == []


def test_base_source_raise_on_non_fuzzy_degrades_never_raises() -> None:
    """AC6: a raising base_source on a non-fuzzy trigger → degrade, NEVER raises."""
    node = build_fuzzy_aware_hypothesis_planner(base_source=_raising_source())
    result = node(_state(canonical_trigger=_NON_FUZZY))
    assert set(result) == {"hypotheses"}
    assert _hypotheses_of(result) == []


# ---------------------------------------------------------------------------
# AC7 — AD-4 partial + DI seam independence + AD-1 one-way
# ---------------------------------------------------------------------------


def test_factory_independence_different_fuzzy_set() -> None:
    """AC7: two factories with different fuzzy_set select differently for the same trigger."""
    node_default = build_fuzzy_aware_hypothesis_planner()  # _FUZZY is fuzzy
    node_other = build_fuzzy_aware_hypothesis_planner(
        fuzzy_set=frozenset({"SomeOtherFuzzy"}),
        base_source=_static_source({"plan": {"base": True}}),
        expansion_source=_static_source({"plan": {"expansion": True}}),
    )
    # _FUZZY is fuzzy under default → expansion; under node_other it is NOT fuzzy → base.
    default_plan = _hypotheses_of(node_default(_state(canonical_trigger=_FUZZY)))[0]["plan"]
    other_plan = _hypotheses_of(node_other(_state(canonical_trigger=_FUZZY)))[0]["plan"]
    assert isinstance(default_plan, dict) and isinstance(other_plan, dict)
    assert "candidate_root_cause" in default_plan  # expansion (default fuzzy_set)
    assert other_plan.get("base") is True  # base (custom fuzzy_set excludes _FUZZY)


def test_factory_independence_different_sources() -> None:
    """AC7: two factories with different expansion sources emit different fuzzy outputs."""
    base = _static_source({"plan": {"base": True}})
    exp_a = _static_source({"plan": {"exp": "a"}})
    exp_b = _static_source({"plan": {"exp": "b"}})
    node_a = build_fuzzy_aware_hypothesis_planner(base_source=base, expansion_source=exp_a)
    node_b = build_fuzzy_aware_hypothesis_planner(base_source=base, expansion_source=exp_b)
    plan_a = _hypotheses_of(node_a(_state(canonical_trigger=_FUZZY)))[0]["plan"]
    plan_b = _hypotheses_of(node_b(_state(canonical_trigger=_FUZZY)))[0]["plan"]
    assert isinstance(plan_a, dict) and isinstance(plan_b, dict)
    assert plan_a.get("exp") == "a"
    assert plan_b.get("exp") == "b"


def test_import_roots_one_way_no_back_edge() -> None:
    """AC7: AD-1 one-way — import roots ⊆ {__future__, graph, stdlib}; NO tools/adapters/models/
    routers/services/ci."""
    src = NODE_FILE.read_text(encoding="utf-8")
    roots = _import_roots(src)
    forbidden = {"tools", "adapters", "models", "routers", "services", "ci"}
    assert not (forbidden & roots), f"forbidden back-edge import roots: {forbidden & roots}"
    allowed = {
        "__future__",
        "graph",
        "collections",
        "typing",
        "json",
        "re",
        "itertools",
        "functools",
    }
    assert roots <= allowed, f"unexpected import roots: {roots - allowed}"
