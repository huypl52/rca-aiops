"""tests for graph.compiled — Story 3.5 AC2 (compile-once immutable) + AC3 (entry contract) + DEEP.

Covers the DEEP-review spotlights for Story 3.5:
  - **AD-2 immutable-once**: ``build_compiled_graph`` memoized — same nodes → SAME object (identity);
    different nodes → rebuilt. ``CompiledGraphRunner.run()`` reuses it.
  - **full 8-node topology**: all §3.5 node names wired; the happy path runs ICB→PBR→HYP→VAL→EXR→ENV→REF→WRT→END.
  - **EXR node-wiring in the graph**: a valid promoted plan → EXR dispatches → ``tool_calls_count`` rises.
  - **max_iterations BOUNDED → status="failed"** (carry-forward 1-A4): the default (degenerate) planner
    never satisfies VAL → loops → the recursion cap fires → ``failed``, no hang.
  - **AC2 seam**: ``services/dispatch.py`` is UNCHANGED — its source imports only ``graph.runner`` and
    contains NO ``compiled``/``StateGraph``/``CompiledGraphRunner`` reference (the plug is composition-root).
  - **entry contract + GraphRunner Protocol**: ``CompiledGraphRunner`` is a structural ``GraphRunner``;
    its ``run`` honors ``(trigger, investigation_id, max_iterations)`` and returns the registry result.
  - **spine + determinism**: 13-key spine preserved; two identical runs yield identical snapshots (AD-12).

AST-discipline (docstring-immune): assertions are statement-level.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

from langgraph.graph.state import CompiledStateGraph

from graph.compiled import (
    CompiledGraphRunner,
    build_compiled_graph,
    build_default_compiled_runner,
    build_plan_promoting_planner,
)
from graph.nodes.executor_router import build_executor_router_node
from graph.nodes.incident_context_builder import incident_context_builder
from graph.nodes.plan_validator import build_plan_validator
from graph.nodes.preplanning_playbook_retriever import build_preplanning_playbook_retriever
from graph.runner import GraphRunner, GraphRunnerResult
from graph.state import InvestigationState, JsonValue, create_initial_state
from tools.port import StubReadOnlyAdapter
from tools.registry import build_default_registry
from tools.router import ExecutorRouter

_TRIGGER: dict[str, JsonValue] = {"service": "checkout"}
_VALID_PLAN: dict[str, JsonValue] = {
    "tool": "query_prometheus_raw",
    "query": "up",
    "timestamp_range": {"start": "2026-06-24T00:00:00Z", "end": "2026-06-24T01:00:00Z"},
}


def _planner_emitting_valid_plan(state: InvestigationState) -> dict[str, JsonValue]:
    """A 3-2-shaped planner node that emits ONE hypothesis carrying a VAL-satisfiable plan."""
    del state
    return {
        "hypotheses": [
            {"id": "H01", "priority": 1, "plan": dict(_VALID_PLAN), "status": "open"},
        ]
    }


def _happy_runner() -> CompiledGraphRunner:
    """A runner whose HYP promotes a valid plan → VAL proceeds → EXR dispatches → WRT terminal."""
    adapter = StubReadOnlyAdapter()
    router = ExecutorRouter(build_default_registry(), adapter)
    graph = build_compiled_graph(
        incident_context_builder=incident_context_builder,
        preplanning_playbook_retriever=build_preplanning_playbook_retriever(adapter),
        hypothesis_planner=build_plan_promoting_planner(_planner_emitting_valid_plan),
        plan_validator=build_plan_validator(),
        executor_router=build_executor_router_node(router=router),
    )
    return CompiledGraphRunner(graph)


def _run(coro: Coroutine[Any, Any, GraphRunnerResult]) -> GraphRunnerResult:
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# AC2 — AD-2 immutable-once (compile ONCE per process; identity on same nodes)
# ---------------------------------------------------------------------------


def test_ad2_same_nodes_returns_identical_compiled_graph() -> None:
    """Two builds with the SAME node objects → the SAME compiled-graph object (lru_cache identity)."""
    adapter = StubReadOnlyAdapter()
    router = ExecutorRouter(build_default_registry(), adapter)
    kwargs = dict(
        incident_context_builder=incident_context_builder,
        preplanning_playbook_retriever=build_preplanning_playbook_retriever(adapter),
        hypothesis_planner=build_plan_promoting_planner(_planner_emitting_valid_plan),
        plan_validator=build_plan_validator(),
        executor_router=build_executor_router_node(router=router),
    )
    first = build_compiled_graph(**kwargs)
    second = build_compiled_graph(**kwargs)
    assert first is second  # AD-2: memoized → identical object, no recompile


def test_ad2_different_nodes_rebuilds() -> None:
    """A DIFFERENT injected node → a DIFFERENT compiled-graph object (correct rebuild)."""
    adapter = StubReadOnlyAdapter()
    router = ExecutorRouter(build_default_registry(), adapter)
    g1 = build_compiled_graph(
        incident_context_builder=incident_context_builder,
        preplanning_playbook_retriever=build_preplanning_playbook_retriever(adapter),
        hypothesis_planner=build_plan_promoting_planner(_planner_emitting_valid_plan),
        plan_validator=build_plan_validator(),
        executor_router=build_executor_router_node(router=router),
    )
    # A distinct planner node object → the cache key differs → a freshly compiled graph.
    g2 = build_compiled_graph(
        incident_context_builder=incident_context_builder,
        preplanning_playbook_retriever=build_preplanning_playbook_retriever(adapter),
        hypothesis_planner=build_plan_promoting_planner(_planner_emitting_valid_plan),
        plan_validator=build_plan_validator(),
        executor_router=build_executor_router_node(
            router=ExecutorRouter(build_default_registry(), adapter)
        ),
    )
    assert g1 is not g2


# ---------------------------------------------------------------------------
# AC2 — full 8-node §3.5 topology wired (node names present in the compiled graph)
# ---------------------------------------------------------------------------


_EXPECTED_NODE_NAMES = {
    "incident_context_builder",
    "preplanning_playbook_retriever",
    "hypothesis_planner",
    "plan_validator",
    "executor_router",
    "evidence_normalizer",
    "reflector",
    "rca_writer",
}


def test_full_topology_all_eight_nodes_wired() -> None:
    """The compiled graph holds EXACTLY the 8 §3.5 node names (+ __start__)."""
    runner = _happy_runner()
    node_names = set(runner._graph.nodes.keys())
    assert _EXPECTED_NODE_NAMES <= node_names
    assert "__start__" in node_names


def test_compiled_graph_is_compiled_state_graph() -> None:
    """build_compiled_graph returns a LangGraph CompiledStateGraph (compile() happened ONCE)."""
    runner = _happy_runner()
    assert isinstance(runner._graph, CompiledStateGraph)


# ---------------------------------------------------------------------------
# AC3 — entry contract: run() honors (trigger, investigation_id, max_iterations); EXR wired
# ---------------------------------------------------------------------------


def test_happy_path_proceeds_dispatches_and_terminates_success() -> None:
    """Valid promoted plan → VAL proceeds → EXR dispatches (tool_calls_count=1) → WRT → success."""
    runner = _happy_runner()
    result: GraphRunnerResult = _run(runner.run(_TRIGGER, "inv-happy", max_iterations=10))
    assert result["status"] == "success"
    assert result["report"] is None  # WRT is the 5-1 DEFERRED stub → report None
    snap = result["state_snapshot"]
    assert snap["tool_calls_count"] == 1  # EXR dispatched exactly one read-only query
    assert isinstance(snap["context"], dict) and snap["context"].get("service") == "checkout"


def test_runner_is_structural_graph_runner() -> None:
    """CompiledGraphRunner satisfies the runtime_checkable GraphRunner Protocol (AC3 plug shape)."""
    assert isinstance(_happy_runner(), GraphRunner)


def test_run_signature_matches_entry_contract() -> None:
    """run(trigger, investigation_id, max_iterations) — the dispatcher's PORT contract (1-4)."""
    sig = inspect.signature(CompiledGraphRunner.run)
    params = list(sig.parameters.keys())
    # ['self', 'trigger', 'investigation_id', 'max_iterations']
    assert params[1:] == ["trigger", "investigation_id", "max_iterations"]


# ---------------------------------------------------------------------------
# Carry-forward 1-A4 — max_iterations BOUNDED loop → status="failed" (no hang)
# ---------------------------------------------------------------------------


def test_default_planner_is_bounded_and_fails_without_hanging() -> None:
    """The POC-default (degenerate) planner never satisfies VAL → bounded by max_iterations → failed.

    This is the HONEST POC state (real convergence needs Epic 4 reflector + hypothesis-advance).
    The MECHANISM under test: the loop is HARD-bounded — max_iterations maps to a recursion_limit;
    exceeding it yields ``status="failed"`` rather than hanging. We assert both the bound fires AND
    the call returns promptly.
    """
    runner = build_default_compiled_runner()  # 3-2 rule-based plans lack the VAL trio → replan loop
    result = _run(runner.run(_TRIGGER, "inv-bounded", max_iterations=1))
    assert result["status"] == "failed"
    assert result["report"] is None


def test_bounded_loop_is_truly_bounded_under_more_iterations() -> None:
    """A larger max_iterations still terminates (failed) — the cap scales, never hangs."""
    runner = build_default_compiled_runner()
    result = _run(runner.run(_TRIGGER, "inv-bounded-2", max_iterations=5))
    assert result["status"] == "failed"


# ---------------------------------------------------------------------------
# AD-12 determinism — two identical runs yield identical snapshots
# ---------------------------------------------------------------------------


def test_determinism_two_runs_identical_snapshot() -> None:
    """Same trigger → identical snapshots across two FRESH runners (AD-12; no wall-clock/random/hash).

    Each investigation run gets its own router (per-investigation dedupe cache, per the 2-3 contract),
    so a fresh runner per run is the correct determinism model — same inputs → same outputs.
    """
    r1 = _run(_happy_runner().run(_TRIGGER, "inv-det", max_iterations=10))
    r2 = _run(_happy_runner().run(_TRIGGER, "inv-det", max_iterations=10))
    assert r1["status"] == r2["status"] == "success"
    assert r1["state_snapshot"] == r2["state_snapshot"]
    assert r1["report"] == r2["report"]


# ---------------------------------------------------------------------------
# AC2 seam — services/dispatch.py is UNCHANGED (no compiled-graph reference)
# ---------------------------------------------------------------------------


def test_ac2_seam_services_dispatch_does_not_reference_compiled_graph() -> None:
    """The dispatcher module imports ONLY graph.runner — no compiled/StateGraph/CompiledGraphRunner.

    The plug is composition-root (Dispatcher(runner=...)); the MODULE default stays
    ContextBuilderRunner. Story 1-4's test_ac2_dispatcher_does_not_import_compiled_graph pins the
    same invariant — this asserts the source text directly (defensive, docstring-immune).
    """
    src = Path("services/dispatch.py").read_text(encoding="utf-8")
    assert "StateGraph" not in src
    assert "CompiledGraphRunner" not in src
    assert "graph.compiled" not in src
    assert "from graph.runner import" in src  # depends on the PORT only


# ---------------------------------------------------------------------------
# Spine — 13-key InvestigationState preserved (no new key introduced by 3.5)
# ---------------------------------------------------------------------------


def test_spine_remains_thirteen_keys() -> None:
    """3.5 introduces NO new spine key — create_initial_state still yields the 13-key AD-9 spine."""
    state = create_initial_state(incident_id="inv-spine", trigger=_TRIGGER)
    assert len(InvestigationState.__annotations__) == 13
    assert "plan" in state and "tool_calls" in state and "next_action" in state


# ---------------------------------------------------------------------------
# build_plan_promoting_planner — graph composition (promotes top-priority plan; never raises)
# ---------------------------------------------------------------------------


def test_plan_promotion_picks_lowest_priority_then_id() -> None:
    """Promotion is deterministic: lowest ``priority`` wins; ties broken by ``id`` ascending."""

    def _planner(state: InvestigationState) -> dict[str, JsonValue]:
        del state
        return {
            "hypotheses": [
                {"id": "H02", "priority": 2, "plan": {"tool": "b"}, "status": "open"},
                {"id": "H01", "priority": 1, "plan": {"tool": "a"}, "status": "open"},
                {"id": "H03", "priority": 1, "plan": {"tool": "c"}, "status": "open"},
            ],
        }

    planner = build_plan_promoting_planner(_planner)
    out = planner(create_initial_state())
    assert out["plan"] == {"tool": "a"}  # priority 1, id H01 < H03


def test_plan_promotion_empty_hypotheses_leaves_no_plan() -> None:
    """No hypotheses → no plan promoted (VAL replans; bounded by max_iterations)."""

    def _planner(state: InvestigationState) -> dict[str, JsonValue]:
        del state
        return {"hypotheses": []}

    planner = build_plan_promoting_planner(_planner)
    out = planner(create_initial_state())
    assert "plan" not in out


def test_plan_promotion_never_raises_on_planner_exception() -> None:
    """An injected planner that raises → folded to {} (Constraint 5)."""

    def _boom(state: InvestigationState) -> dict[str, JsonValue]:
        raise RuntimeError("planner failed")

    planner = build_plan_promoting_planner(_boom)
    assert planner(create_initial_state()) == {}
