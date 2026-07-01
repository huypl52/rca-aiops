"""compiled — §3.5 compiled-graph ASSEMBLY + CompiledGraphRunner + EXR plug (Story 3.5 — AD-2 / FR-4 / FR-5 / FR-7 / NFR-Determinism).

This is the **compile-time DSL assembler** + the concrete entry-contract runner. It wires the FULL
8-node §3.5 PE-R topology ONCE (immutable per process — AD-2) and provides the runner services call
via the ``GraphRunner`` PORT (``graph/runner.py``). The dispatcher (``services/dispatch.py``) is
UNCHANGED — it already depends on the PORT; 3.5 plugs ``CompiledGraphRunner`` WITHOUT touching it
(the AC2 seam the leader DEEP-reviews).

**3.5 = the ASSEMBLY MECHANISM + the EXR node-wiring + the runner plug. It is NOT yet the full runtime.**
ALL **8 §3.5 nodes now have real content**: ICB (1-3), PBR (3-1), HYP (3-2 + 3-4 fuzzy-aware planner),
VAL (3-3), EXR (3.5 — node-wiring over the 2-3 router), ENV (evidence_normalizer = 4-2), REF (reflector
= 4-3), WRT (rca_writer = 5-1). The EDGES are wired NOW (the contract-critical part); the composition
root wires each real node via the SAME ``build_compiled_graph`` factory param — edges NEVER re-wire (the
4-2/4-3/5-1 swaps touched NO edge). This is the SAME lock-the-MECHANISM / swap-CONTENT discipline as 3.4.

ANTI-DRIFT (do NOT build these here — they steal Epic 5/7 work):
  - **WRT real node content** (5-1) → DELIVERED (``build_rca_writer``, wired at the composition root).
    The DI-default deterministic STUB (§DEFER) is RETAINED as the DI-param default so a report=None WRT
    stays a valid test/composition choice — the swap touched NO wiring (ENV 4-2 / REF 4-3 already swapped
    stub→real the same way, touching NO edge).
  - **Hypothesis-ADVANCE on replan** (try the next untried hypothesis). The POC-default promotion
    re-promotes the SAME top-priority plan (deterministic); a VAL-rejected plan re-rejects, and REF
    fail-closes (empty D3 registry) → ``gather_more`` → bounded by ``max_iterations`` (carry-forward
    1-A4). Honest degenerate loop; ADVANCE is deferred.
  - **partial "chưa đủ" surfacing at the registry/API level.** On cap-exhaustion the RUNNER already
    returns an honest ``status="partial"`` carrying the reflector's ``sufficiency.gap`` (Story 4-3 /
    FR-7 / AD-10 #5); the dispatcher still maps an unknown runner status to registry ``failed``,
    so surfacing ``partial`` (vs ``failed``) at the services layer is deferred Epic 5/6.
  - **No LangGraph checkpointer** → cross-restart durability (SqliteSaver, AD-11) = Story 7-4.

ONE-WAY (AD-1 / gate #2): module-level imports are ``graph.state`` + ``graph.runner`` (same layer) +
``langgraph`` (3rd-party) + stdlib ONLY. This module does NOT import ``tools`` at module level — the
BUILDER receives the EXR node via DI; only ``build_default_compiled_runner`` (the composition root)
lazily imports ``tools`` to assemble the real stack (graph→tools FORWARD — LEGAL). NEVER
``routers``/``services``/``adapters``. lint-imports: 1 contract kept / 0 broken.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Hashable, Mapping
from functools import lru_cache
from typing import TYPE_CHECKING, Any, cast

from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from graph.runner import GraphRunner, GraphRunnerResult, _snapshot_from_state
from graph.state import InvestigationState, JsonValue, create_initial_state

if TYPE_CHECKING:
    # Typing-only (graph→tools FORWARD is LEGAL, but the module surface stays tools-free at runtime per
    # §2.7 / gate#2: build_default_compiled_runner's ``adapter`` seam is typed against the PORT Protocol
    # WITHOUT a module-level tools import — tools is imported LAZILY inside the composition root, as before).
    # ``if TYPE_CHECKING`` is never executed at runtime + is AST-invisible to top-level-import walkers, so
    # the §2.7 "module-level imports = graph + langgraph + stdlib ONLY" contract holds + lint-imports is clean.
    # Story 7-4: ``BaseCheckpointSaver`` types the durable-store DI param (sqlite ↔ postgres swap = AC1);
    # typing-only so the module surface stays langgraph-graph + graph + stdlib at runtime (no checkpoint import).
    from langgraph.checkpoint.base import BaseCheckpointSaver

    from tools.port import ReadOnlyAdapterPort

# ONE-WAY (AD-1 / gate #2): graph.state + graph.runner (same layer) + langgraph (3rd-party) + stdlib
# ONLY at module level. NO tools/routers/services/adapters — the builder takes the EXR node via DI;
# only build_default_compiled_runner (composition root) lazily imports tools.

# ---------------------------------------------------------------------------
# §3.5 node names (the EXACT 8-node topology — wiring locked here)
# ---------------------------------------------------------------------------
N_ICB = "incident_context_builder"
N_PBR = "preplanning_playbook_retriever"
N_HYP = "hypothesis_planner"
N_VAL = "plan_validator"
N_EXR = "executor_router"
N_ENV = "evidence_normalizer"
N_REF = "reflector"
N_WRT = "rca_writer"

# LOCKED next_action routing vocabulary (ARCHITECTURE-SPINE.md:95). VAL uses {proceed, replan};
# REF uses {gather_more, replan, write}. An unknown value routes to a SAFE deterministic default
# (VAL→replan→HYP; REF→write→WRT) — never crashes.
NA_PROCEED = "proceed"
NA_REPLAN = "replan"
NA_GATHER_MORE = "gather_more"
NA_WRITE = "write"

# Deterministic multiplier mapping the dispatcher lifetime cap ``max_iterations`` (FR-7, PE-R loop
# iterations) to LangGraph's ``recursion_limit`` (node supersteps). A full PE-R loop iteration visits
# at most ~6 distinct nodes (HYP→VAL→EXR→ENV→REF→back-to-HYP); 8 is a conservative ceiling (the
# one-time ICB/PBR prefix is amortized across iterations). This GUARANTEES the loop is BOUNDED — no
# infinite loop is possible — and exceeding it → ``status="partial"`` (carry-forward 1-A4 / Story
# 4-3 / AD-10 #5: NOT a silent binary fail). The number is a
# POC choice (deterministic + sane); tuning is deferred.
_NODES_PER_ITERATION: int = 8


# ---------------------------------------------------------------------------
# §DEFER — deterministic DI-default stubs for ENV / REF / WRT (real node in 4.x/5-1)
#
# Each is a pure deterministic node ``(state) -> partial dict``. They are injected as the DEFAULTS of
# ``build_compiled_graph``'s optional params; 4.x/5-1 swap stub→real via the SAME param (edges never
# re-wire). These are PLACEHOLDERS, NOT design decisions — the real nodes own their behavior.
# ---------------------------------------------------------------------------


def _evidence_normalizer_stub(state: InvestigationState) -> dict[str, JsonValue]:
    """DEFERRED — real evidence_normalizer is Story 4-2.

    Pure identity pass-through. The real node normalizes ``tool_calls`` raw → Evidence 9-field
    (AD-6). The stub emits NO keys (evidence stays empty in the POC; snapshot ``evidence_count=0``).
    Deterministic (AD-12).
    """
    del state
    return {}


def _reflector_stub(state: InvestigationState) -> dict[str, JsonValue]:
    """DEFERRED — real reflector is Story 4-3.

    Deterministic "route to WRT": returns ``next_action="write"`` so the REF→WRT edge is exercised.
    The real node does floor_check (AD-12 rule-sàn) + LLM-ceiling (AD-7) + gather_more/replan/write
    routing + max-iter→partial. The stub's "always write" is a deterministic POC default, NOT a
    routing design (4-3 owns routing). The REF→HYP loop-back edge is WIRED + exercisable via a test
    that injects a looping REF. Deterministic (AD-12).
    """
    del state
    return {"next_action": NA_WRITE}


def _rca_writer_stub(state: InvestigationState) -> dict[str, JsonValue]:
    """DI-DEFAULT fallback for tests/composition that exercise the REF→WRT→END edge WITHOUT a report.

    Real ``rca_writer`` is Story 5-1 (DELIVERED — :func:`graph.nodes.rca_writer.build_rca_writer`, wired
    at the composition root :func:`build_default_compiled_runner`). This stub is RETAINED as the
    ``rca_writer`` DI-param default: a no-op ``report=None`` WRT is a valid test/composition choice
    (e.g. the 3-5 happy-path runner that exercises the edge without producing a cited report). The real
    node emits the cited RCA report (FR-9, AD-6 evidence-sourced, no remediation). Deterministic (AD-12).
    """
    del state
    return {"report": None}


# ---------------------------------------------------------------------------
# §2.2 — plan-promotion wrapper (graph composition, NOT a new node)
#
# 3-3's docstring delegates "which hypothesis's plan is promoted to state.plan" to graph wiring
# (3.5). This wrapper composes over a 3-2 planner node: it calls the planner → takes its
# {"hypotheses": [...]} → ALSO sets state.plan = the top-priority hypothesis's plan (deterministic:
# lowest ``priority`` value first; stable tie-break by ``id`` H01..). The wrapped function IS the HYP
# node — the graph still has EXACTLY 8 §3.5 nodes (NO 9th "selector" node).
#
# Hypothesis-ADVANCE on replan is REF (4-3) — DEFERRED. The POC-default promotion always re-promotes
# the top-priority plan; a VAL-rejected plan re-rejects → bounded by max_iterations (1-A4).
# ---------------------------------------------------------------------------

# Sort missing/non-numeric priority LAST so a well-formed hypothesis always wins the promotion.
_PRIORITY_SENTINEL: int = 10**9


def _promotion_sort_key(hypothesis: Mapping[str, object]) -> tuple[int | float, str]:
    """Deterministic sort key for plan promotion: (priority ASC, id ASC).

    Lowest ``priority`` value first (priority 1 outranks 2); stable tie-break by ``id`` (``H01`` <
    ``H02`` < ...). Missing / non-numeric ``priority`` sorts last (sentinel); missing / non-str
    ``id`` sorts as ``""``. Deterministic (AD-12).
    """
    priority_value = hypothesis.get("priority")
    priority: int | float = (
        priority_value if isinstance(priority_value, int | float) else _PRIORITY_SENTINEL
    )
    id_value = hypothesis.get("id")
    id_str = id_value if isinstance(id_value, str) else ""
    return (priority, id_str)


def _canonical_identity_component(value: object) -> str | None:
    """Canonical JSON for deterministic plan/tool-call identity comparison; None when unshaped."""
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    except Exception:
        return None


def _plan_identity(plan: Mapping[str, object]) -> tuple[str, str, str] | None:
    """Plan identity aligned to EXR/router dedupe shape: ``(tool, query, timestamp_range)``."""
    tool = plan.get("tool")
    if not isinstance(tool, str) or not tool:
        return None
    identifying = _canonical_identity_component(
        {key: value for key, value in plan.items() if key not in {"tool", "timestamp_range"}}
    )
    timestamp_range = _canonical_identity_component(plan.get("timestamp_range"))
    if identifying is None or timestamp_range is None:
        return None
    return (tool, identifying, timestamp_range)


def build_plan_promoting_planner(
    planner: Callable[[InvestigationState], dict[str, JsonValue]],
) -> Callable[[InvestigationState], dict[str, JsonValue]]:
    """Wrap a 3-2 hypothesis_planner node so it ALSO promotes the top-priority plan to ``state.plan``.

    Returns a node that calls ``planner(state)`` (→ ``{"hypotheses": [...]}``) and, when there is a
    top-priority hypothesis carrying a ``plan`` dict, returns ``{**planner_result, "plan": <top plan>}``.
    Empty / malformed hypotheses → no ``plan`` set (``state.plan`` stays as-is/None → VAL replans).
    NEVER raises (Constraint 5): an injected planner that raises is folded to ``{}`` (no hypotheses,
    no plan → VAL replans, bounded by max_iterations).

    This is graph COMPOSITION over 3.2 — the SAME reuse discipline 3.4 applied (call 3.2's planner,
    add a deterministic promotion). It is NOT a new §3.5 node (the wrapped function IS HYP).
    """

    def _hypothesis_planner_with_promotion(state: InvestigationState) -> dict[str, JsonValue]:
        try:
            partial = planner(state)
        except Exception:  # noqa: BLE001 — injected planner raised → graceful degrade (never raises)
            return {}
        if not isinstance(partial, dict):
            return {}
        out: dict[str, JsonValue] = dict(partial)
        hypotheses = out.get("hypotheses")
        if isinstance(hypotheses, list):
            eligible = [h for h in hypotheses if isinstance(h, Mapping)]
            if eligible:
                executed: set[tuple[str, str, str]] = set()
                tool_calls = state.get("tool_calls")
                if isinstance(tool_calls, list):
                    for record in tool_calls:
                        if not isinstance(record, Mapping):
                            continue
                        tool = record.get("tool")
                        query = record.get("query")
                        timestamp_range = record.get("timestamp_range")
                        if (
                            isinstance(tool, str)
                            and tool
                            and isinstance(query, str)
                            and query
                            and isinstance(timestamp_range, str)
                            and timestamp_range
                        ):
                            executed.add((tool, query, timestamp_range))

                ranked = sorted(eligible, key=_promotion_sort_key)
                top = ranked[0]
                for hypothesis in ranked:
                    top_plan = hypothesis.get("plan")
                    if isinstance(top_plan, Mapping):
                        identity = _plan_identity(top_plan)
                        if identity is not None and identity not in executed:
                            top = hypothesis
                            break
                top_plan = top.get("plan")
                if isinstance(top_plan, dict):
                    out["plan"] = dict(top_plan)
        return out

    return _hypothesis_planner_with_promotion


# ---------------------------------------------------------------------------
# §2.3 — conditional-edge routing (deterministic; reads state.next_action)
# ---------------------------------------------------------------------------


def _route_from_plan_validator(state: InvestigationState) -> str:
    """VAL routing key: ``proceed``→EXR, ``replan`` (and unknown)→HYP (safe replan)."""
    return NA_PROCEED if state.get("next_action") == NA_PROCEED else NA_REPLAN


def _route_from_reflector(state: InvestigationState) -> str:
    """REF routing key: ``gather_more``/``replan``→HYP, ``write`` (and unknown)→WRT (safe terminal)."""
    next_action = state.get("next_action")
    if next_action in (NA_GATHER_MORE, NA_REPLAN):
        return NA_REPLAN if next_action == NA_REPLAN else NA_GATHER_MORE
    return NA_WRITE


# The conditional-edge path maps (LOCKED next_action vocabulary → target node). Typed
# ``dict[Hashable, str]`` to match LangGraph's ``add_conditional_edges`` path_map contract (the keys
# are routing keys — here ``str`` — but the stub widens them to ``Hashable``).
_VAL_PATHS: dict[Hashable, str] = {NA_PROCEED: N_EXR, NA_REPLAN: N_HYP}
_REF_PATHS: dict[Hashable, str] = {
    NA_GATHER_MORE: N_HYP,
    NA_REPLAN: N_HYP,
    NA_WRITE: N_WRT,
}


@lru_cache(maxsize=1)
def build_compiled_graph(
    *,
    incident_context_builder: Callable[[InvestigationState], dict[str, JsonValue]],
    preplanning_playbook_retriever: Callable[[InvestigationState], dict[str, JsonValue]],
    hypothesis_planner: Callable[[InvestigationState], dict[str, JsonValue]],
    plan_validator: Callable[[InvestigationState], dict[str, JsonValue]],
    executor_router: Callable[[InvestigationState], dict[str, JsonValue]],
    evidence_normalizer: Callable[
        [InvestigationState], dict[str, JsonValue]
    ] = _evidence_normalizer_stub,
    reflector: Callable[[InvestigationState], dict[str, JsonValue]] = _reflector_stub,
    rca_writer: Callable[[InvestigationState], dict[str, JsonValue]] = _rca_writer_stub,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> CompiledStateGraph:  # type: ignore[type-arg]  # langgraph generic params unused here (stub)
    """DI-seam factory: compile the FULL 8-node §3.5 PE-R graph ONCE (immutable per process — AD-2).

    The 5 available nodes are REQUIRED (real content: ICB 1-3, PBR 3-1, HYP 3-2/3-4, VAL 3-3, EXR
    3.5). ENV/REF/WRT are OPTIONAL, defaulting to the deterministic DI-default stubs (4.x/5-1 swap
    stub→real via this same param). Returns the compiled LangGraph
    (``StateGraph(InvestigationState).compile()``).

    Topology (spec ARCHITECTURE-SPINE.md §3.5 — wired NOW; the 3 deferred nodes are stubs)::

        START → ICB → PBR → HYP → VAL ──{ proceed → EXR → ENV → REF ──{ gather_more/replan → HYP,
                                  └──{ replan → HYP }                          └──{ write → WRT → END }

    AD-2 immutable-once: memoized via ``lru_cache(maxsize=1)``. Two calls with the SAME node objects
    return the SAME compiled-graph object (identity); ``CompiledGraphRunner.run()`` reuses it (no
    per-run recompile). Calling with DIFFERENT nodes rebuilds (correct — a different injected graph).

    Args:
        incident_context_builder: the ICB node (1-3).
        preplanning_playbook_retriever: the PBR node (3-1).
        hypothesis_planner: the HYP node — pass the plan-PROMOTION-wrapped 3-2 planner
            (:func:`build_plan_promoting_planner`) so ``state.plan`` is populated; a bare 3-2 planner
            leaves ``state.plan`` empty → VAL replans (degenerate but bounded).
        plan_validator: the VAL node (3-3).
        executor_router: the EXR node (3.5 — :func:`build_executor_router_node`).
        evidence_normalizer: the ENV node (default the 4-2 DEFERRED stub).
        reflector: the REF node (default the 4-3 DEFERRED stub).
        rca_writer: the WRT node (default the DI-default stub — real ``build_rca_writer`` is 5-1,
            wired at the composition root :func:`build_default_compiled_runner`).
        checkpointer: optional durable-store saver (Story 7-4 — AD-11). ``None`` (default) → BARE
            ``graph.compile()`` (byte-identical to pre-7-4; the determinism harness / gate #6 compiles
            here so its agent outputs NEVER change). A non-None saver bakes the checkpointer in at
            compile time (AD-2 immutable-once): ``run`` writes checkpoints as it streams;
            ``resume`` / ``aget_state`` load them (cross-restart durability). Swap sqlite ↔ postgres
            = swap the saver OBJECT (AC1) — this factory + the runner + the dispatcher are unchanged.
            The serializer is the saver's built-in ``JsonPlusSerializer`` (AD-9 — NO custom serde).

    Returns:
        the compiled ``StateGraph(InvestigationState)`` (a ``CompiledStateGraph``), immutable per
        process.
    """
    graph = StateGraph(InvestigationState)
    # NOTE: ``add_node`` carries a deliberate ``# type: ignore[call-overload]`` on EVERY call. The
    # langgraph 1.2.6 stubs type a node as ``_Node[NodeInputT]`` and, under strict mypy, refuse a
    # plain ``Callable[[InvestigationState], dict[str, JsonValue]]`` (recursive-alias / partial-update
    # invariance). This is a STUB limitation only — every node is a valid LangGraph node and the full
    # topology runs end-to-end (tests/test_compiled_graph.py exercises the happy path). Re-checked each
    # story; do NOT "fix" by re-typing the nodes to langgraph internals.
    graph.add_node(N_ICB, incident_context_builder)  # type: ignore[call-overload]
    graph.add_node(N_PBR, preplanning_playbook_retriever)  # type: ignore[call-overload]
    graph.add_node(N_HYP, hypothesis_planner)  # type: ignore[call-overload]
    graph.add_node(N_VAL, plan_validator)  # type: ignore[call-overload]
    graph.add_node(N_EXR, executor_router)  # type: ignore[call-overload]
    graph.add_node(N_ENV, evidence_normalizer)  # type: ignore[call-overload]
    graph.add_node(N_REF, reflector)  # type: ignore[call-overload]
    graph.add_node(N_WRT, rca_writer)  # type: ignore[call-overload]

    # Linear prefix: START → ICB → PBR → HYP → VAL.
    graph.add_edge(START, N_ICB)
    graph.add_edge(N_ICB, N_PBR)
    graph.add_edge(N_PBR, N_HYP)
    graph.add_edge(N_HYP, N_VAL)

    # VAL conditional: proceed → EXR; replan (and unknown) → HYP (loop-back, bounded by max_iterations).
    graph.add_conditional_edges(N_VAL, _route_from_plan_validator, _VAL_PATHS)

    # EXR → ENV → REF (plain edges; EXR needs no routing signal).
    graph.add_edge(N_EXR, N_ENV)
    graph.add_edge(N_ENV, N_REF)

    # REF conditional: gather_more/replan → HYP (loop-back); write (and unknown) → WRT (terminal).
    graph.add_conditional_edges(N_REF, _route_from_reflector, _REF_PATHS)

    # WRT → END.
    graph.add_edge(N_WRT, END)

    if checkpointer is None:
        # Byte-stable determinism path (Story 7-4): NO checkpointer → BARE compile, byte-identical to
        # pre-7-4. The determinism harness (gate #6) + every non-durable caller compiles the graph here
        # → its agent outputs are UNCHANGED (the checkpoint wiring NEVER perturbs the byte-stable blob).
        # Cross-restart durability (AD-11) is OPT-IN via a non-None checkpointer (build_default_compiled_runner
        # / the deployed composition root) — a DIFFERENT compiled-graph object, never the harness's.
        return graph.compile()
    # Durable path (Story 7-4 — AD-11): the checkpointer is baked in at compile time (AD-2 immutable-once).
    # The SAME saver drives the checkpoint WRITE (run/resume stream → persist) + the resume READ
    # (aget_state / astream(None, thread_id) → load). Portable serde = the saver's built-in
    # JsonPlusSerializer (AD-9 — NO custom serializer; the 13-key spine is already JSON-safe, gate #3).
    return graph.compile(checkpointer=checkpointer)


# ---------------------------------------------------------------------------
# §2.4 — CompiledGraphRunner (concrete entry-contract runner; AC3 + carry-forward 1-A4)
# ---------------------------------------------------------------------------


def _partial_snapshot(state: InvestigationState) -> dict[str, JsonValue]:
    """Snapshot for a PARTIAL (max-iter exhausted) outcome — Story 4.3 (FR-7 / AD-10 #5).

    The base :func:`graph.runner._snapshot_from_state` projection PLUS the reflector's last
    ``sufficiency`` verdict (which carries the honest "chưa đủ" ``gap`` on a floor-Fail). AD-10 #5:
    max-iter exhaustion is OBSERVABLE (a PARTIAL carrying the gap), never a silent binary fail. The
    verdict may be empty ``{}`` when the reflector never ran (e.g. the POC-default planner loops at
    HYP↔VAL and never reaches REF) — that empty verdict is still honest (a PARTIAL, not a silent fail).
    """
    snapshot = _snapshot_from_state(state)
    sufficiency = state.get("sufficiency")
    # A PARTIAL ALWAYS carries a ``sufficiency`` key: the reflector's last verdict when REF ran, else an
    # empty ``{}`` (the degenerate POC-default planner loops at HYP↔VAL and never reaches REF — still an
    # observable, honest verdict; AD-10 #5). NEVER silent-omit it.
    snapshot["sufficiency"] = dict(sufficiency) if isinstance(sufficiency, dict) else {}
    return snapshot


class CompiledGraphRunner(GraphRunner):
    """Concrete ``GraphRunner`` running the compiled §3.5 graph (AC2 seam + AC3 entry contract).

    Implements the ``GraphRunner`` Protocol (``graph/runner.py``): the dispatcher calls
    ``run(trigger, investigation_id, max_iterations)``; this builds fresh state, runs the compiled
    graph via ``.ainvoke``, and projects a JSON-safe snapshot. The dispatcher is UNCHANGED — it
    depends on the PORT only; this runner plugs via ``Dispatcher(runner=...)`` (AC2).

    Carry-forward 1-A4 (HARD): ``max_iterations`` is honored — the loop is BOUNDED (no infinite loop
    is possible). ``max_iterations`` maps to LangGraph's ``recursion_limit`` via a deterministic
    multiplier (:data:`_NODES_PER_ITERATION`); exceeding it raises ``GraphRecursionError``, caught here
    → an honest PARTIAL (Story 4-3 / FR-7 / AD-10 #5): the run is streamed (mode ``values``) so the
    last-seen full state — carrying the reflector's most-recent ``sufficiency.gap`` ("chưa đủ — cần thêm
    X") — is projected via :func:`_partial_snapshot`. A PARTIAL is NOT a silent binary ``status="failed"``;
    a genuine infra failure stays ``"failed"``. (The dispatcher currently maps an unknown runner status
    to registry ``failed`` — production wiring of ``partial`` at the registry level is deferred Epic 5/6;
    the runner-level outcome here is the honest signal.)

    ``report`` is produced by the rca_writer node (5-1 — :func:`build_rca_writer`, wired at the
    composition root): a cited RCA report dict on a real ``write`` route, or ``None`` when WRT never ran
    (a PARTIAL) / when the DI-default WRT stub was injected.

    NOTE on the POC default: the loop does NOT converge in the POC — the 3-2 rule-based plans lack the
    tool/query/timestamp_range trio VAL requires (VAL replans), and the reflector's floor registry is
    EMPTY (D3 content deferred) so REF fail-closes → ``gather_more`` while HYP re-promotes the SAME plan
    (hypothesis-ADVANCE on replan is deferred). The loop is HARD-bounded by ``max_iterations`` → on
    cap-exhaustion the honest outcome is ``status="partial"`` (Story 4-3 / FR-7 / AD-10 #5), carrying the
    reflector's last ``sufficiency`` (``{}`` when the degenerate planner never reaches REF — still an
    observable, honest verdict; NEVER a silent binary ``status="failed"``). The MECHANISM (compile-once,
    bounded run, entry contract, reflector + PARTIAL) is complete; convergence CONTENT (a populated floor
    registry + hypothesis-advance) is deferred. Production wiring as the default dispatcher is therefore
    deferred until the graph converges — the dispatcher module default (``ContextBuilderRunner``) is
    UNCHANGED (Story 1-4 tests stay green).
    """

    def __init__(
        self,
        graph: CompiledStateGraph,  # type: ignore[type-arg]  # langgraph generic params unused here
        *,
        nodes_per_iteration: int = _NODES_PER_ITERATION,
        checkpointed: bool = False,
    ) -> None:
        self._graph = graph
        self._nodes_per_iteration = nodes_per_iteration
        # Story 7-4: ``checkpointed`` is True ONLY when the graph was compiled with a durable saver.
        # When False (the determinism-harness / byte-stable default) ``run`` passes NO thread_id → the
        # astream config is EXACTLY ``{"recursion_limit": ...}`` (byte-identical to pre-7-4). The flag
        # is set by the composition root from ``checkpointer is not None`` (never guessed by callers).
        self._checkpointed = checkpointed

    async def run(
        self,
        trigger: dict[str, JsonValue],
        investigation_id: str,
        max_iterations: int,
    ) -> GraphRunnerResult:
        """Run the compiled graph for ``investigation_id`` to terminal (entry contract — AD-2)."""
        # The graph layer owns state (AD-2): the dispatcher never touches internals. Fresh state per
        # run. When ``self._checkpointed`` (Story 7-4 — a durable saver was baked in at compile time)
        # the drive is scoped to ``thread_id=investigation_id`` so each superstep PERSISTS to the
        # durable store (cross-restart durability, AD-11). When NOT checkpointed (the byte-stable
        # determinism default) thread_id is None → the astream config is EXACTLY
        # ``{"recursion_limit": ...}`` (byte-identical to pre-7-4 — gate #6 stays green). The astream +
        # GraphRecursionError→partial drive lives in :meth:`_drive_to_terminal` (shared with the
        # Story-6.2 benchmark sibling :meth:`run_terminal_state` + :meth:`resume` — singular drive,
        # no divergence).
        state = create_initial_state(incident_id=investigation_id, trigger=dict(trigger))
        status, terminal = await self._drive_to_terminal(
            state, max_iterations, thread_id=investigation_id if self._checkpointed else None
        )
        if status == "partial":
            # max_iterations exceeded → BOUNDED → honest PARTIAL carrying the reflector's last
            # sufficiency.gap ("chưa đủ — cần thêm X"). NOT a silent binary status="failed" — a genuine
            # infra failure stays "failed"; cap-exhaustion is observable as a PARTIAL.
            return GraphRunnerResult(
                status="partial",
                state_snapshot=_partial_snapshot(terminal),
                report=None,
            )

        report_value = terminal.get("report")
        report: dict[str, JsonValue] | None = (
            report_value if isinstance(report_value, dict) else None
        )
        return GraphRunnerResult(
            status="success",
            state_snapshot=_snapshot_from_state(terminal),
            report=report,
        )

    async def _drive_to_terminal(
        self,
        state: InvestigationState | None,
        max_iterations: int,
        *,
        thread_id: str | None = None,
    ) -> tuple[str, InvestigationState]:
        """Stream the compiled graph to terminal → ``(status, last_state)`` — the shared drive (AD-2).

        Used by :meth:`run` (the dispatcher PORT — projects an AD-9 BOUNDED snapshot),
        :meth:`run_terminal_state` (the Story-6.2 benchmark sibling — returns the FULL terminal state),
        and :meth:`resume` (Story 7-4 — continues a checkpointed investigation). Extracted so the drive
        logic is SINGULAR: the port / benchmark / resume projections can never diverge (all consume this
        one terminal state).

        Story 7-4 (AD-11 — durable checkpoint): ``state`` is ``None`` for a RESUME (the checkpoint holds
        the state — ``astream(None, config={thread_id})`` loads + continues); a fresh ``run`` /
        ``run_terminal_state`` passes the seeded state. ``thread_id`` scopes the checkpoint to the
        investigation; ``None`` (the byte-stable default) → the astream config is EXACTLY
        ``{"recursion_limit": ...}`` (byte-identical to pre-7-4, gate #6 stays green). On a resume the
        first streamed value is the checkpointed state, so ``last_state`` is always populated (the
        resumer only resumes EXISTING checkpoints); the ``assert state is not None`` guards document
        that unreachable invariant (never silently returns an empty state).

        Story 4-3 (FR-7 / AD-10 #5): STREAM with ``stream_mode="values"`` (NOT the default ``"updates"`` —
        which yields per-node update dicts, not the full state) so the latest FULL state is captured even
        when the recursion cap fires mid-investigation. ``ainvoke`` does not surface a partial state on
        cap-exhaustion, so ``astream`` is required to project the reflector's last sufficiency.gap as an
        honest PARTIAL (NOT a silent binary "failed"). Carry-forward 1-A4 (HARD): the loop is BOUNDED —
        ``max_iterations`` → ``recursion_limit`` via :data:`_NODES_PER_ITERATION`; exceeding it raises
        ``GraphRecursionError``, caught here → an honest PARTIAL.
        """
        recursion_limit = max(max_iterations, 1) * self._nodes_per_iteration
        # Typed ``Any``: astream's ``config`` is langgraph's ``RunnableConfig`` (a ``total=False``
        # TypedDict) — an inline literal matches it, but a ``dict[str, Any]`` variable does not. Building
        # it conditionally (thread_id only when checkpointed) needs a variable, so ``Any`` bridges to the
        # TypedDict param without importing langchain_core's RunnableConfig into this module surface.
        config: Any = {"recursion_limit": recursion_limit}
        if thread_id is not None:
            # Checkpoint-scoped drive (Story 7-4): thread_id → the durable store keys this investigation.
            # state given → fresh write (run / run_terminal_state); state=None → resume (the checkpoint
            # holds it). When thread_id is None (the byte-stable determinism default) config is EXACTLY
            # {"recursion_limit": ...} — byte-identical to pre-7-4 (gate #6 stays green).
            config["configurable"] = {"thread_id": thread_id}
        last_state: InvestigationState | None = None
        try:
            async for chunk in self._graph.astream(state, config=config, stream_mode="values"):
                last_state = cast(InvestigationState, chunk)
        except GraphRecursionError:
            if last_state is not None:
                return ("partial", last_state)
            assert (
                state is not None
            )  # resume over a missing checkpoint recursed before any state (unreachable)
            return ("partial", state)
        if last_state is not None:
            return ("success", last_state)
        assert (
            state is not None
        )  # astream yielded nothing (resume over a missing checkpoint — unreachable)
        return ("success", state)

    # Story 7-4 (AD-11) — resume + checkpoint introspection. Valid ONLY on a CHECKPOINTED runner (the
    # graph was compiled with a durable saver): ``aget_state`` requires a checkpointer. The resumer
    # (:class:`graph.checkpoint.SqliteCheckpointResumer`) calls these to scan + drive; the dispatcher
    # depends on the ``InvestigationResumer`` PORT (:class:`graph.runner.InvestigationResumer`), NEVER
    # on these concrete methods directly (the AC2 seam — swap saver = swap store, not the dispatcher).

    async def checkpoint_state(self, investigation_id: str) -> InvestigationState | None:
        """Read the checkpointed state for ``investigation_id`` (Story 7-4 — AD-11), or ``None``.

        Valid ONLY on a checkpointed runner. The resumer uses it to (a) decide incomplete vs terminal
        (:meth:`checkpoint_is_complete`) and (b) RECOVER the trigger (spine key #3) so the dispatcher
        can re-register the read-store record on restart (``set_terminal`` is a no-op without a record
        — Story 1-4). ``None`` for a thread with no checkpoint (empty channel values).
        """
        snapshot = await self._graph.aget_state({"configurable": {"thread_id": investigation_id}})
        values = snapshot.values
        return cast(InvestigationState, values) if values else None

    async def checkpoint_is_complete(self, investigation_id: str) -> bool:
        """True iff the checkpointed investigation reached graph END (``StateSnapshot.next`` empty).

        Valid ONLY on a checkpointed runner. ``next == ()`` → terminal (do NOT resume); non-empty →
        INCOMPLETE (resume at-least-once). Source of truth for "incomplete" on restart (CS Q2): the
        DURABLE store, NOT the in-process read-store (which is empty on restart).
        """
        snapshot = await self._graph.aget_state({"configurable": {"thread_id": investigation_id}})
        return snapshot.next == ()

    async def resume(self, investigation_id: str, max_iterations: int) -> GraphRunnerResult:
        """Resume a checkpointed investigation to terminal WITHOUT a trigger (Story 7-4 — AD-11).

        The checkpoint holds the state — ``_drive_to_terminal(None, thread_id=investigation_id)``
        loads + continues. Reaching END → ``success`` (+ report if the graph converged); re-exhausting
        the cap → an honest ``partial`` (AD-10 #5). The resumed investigation is STILL non-convergent in
        the POC, so this typically returns ``partial`` / ``report=None`` — the DELIVERABLE is the resume
        MECHANISM (interrupt → checkpoint → restart → resume-from-checkpoint), NOT working RCA. Raising
        propagates to the dispatcher's ``status="failed"`` (NOT silent).

        Precondition: a checkpoint EXISTS for ``investigation_id`` (the resumer only resumes existing
        checkpoints, filtered by :meth:`checkpoint_is_complete`). The projection mirrors :meth:`run`'s
        tail — the dispatcher contract is identical for a fresh run and a resumed one.
        """
        status, terminal = await self._drive_to_terminal(
            None, max_iterations, thread_id=investigation_id
        )
        if status == "partial":
            return GraphRunnerResult(
                status="partial",
                state_snapshot=_partial_snapshot(terminal),
                report=None,
            )
        report_value = terminal.get("report")
        report: dict[str, JsonValue] | None = (
            report_value if isinstance(report_value, dict) else None
        )
        return GraphRunnerResult(
            status="success",
            state_snapshot=_snapshot_from_state(terminal),
            report=report,
        )

    async def run_terminal_state(
        self,
        trigger: dict[str, JsonValue],
        investigation_id: str,
        max_iterations: int,
    ) -> dict[str, JsonValue]:
        """Run to terminal returning the FULL state — Story-6.2 benchmark instrument (sibling of run()).

        ``run()`` is the dispatcher PORT: it projects an AD-9 **BOUNDED** snapshot
        (context / next_action / evidence_count / tool_calls_count) + report — the dispatcher contract
        (AD-9 deliberately exposes COUNTS, not the agent's gathered LISTS). The Story-6.2 binary-conjunction
        evaluator needs the actual ``evidence`` / ``tool_calls`` LISTS (conditions c/d) and the ``report``
        (condition e) — which the bounded port omits. This sibling returns the FULL terminal
        ``InvestigationState`` projection (all spine keys, JSON-safe) + the run ``status``; the benchmark
        reads the agent's OWN terminal outputs.

        This is NOT the dispatcher contract: the dispatcher NEVER calls this (it uses ``run()``); both
        share :meth:`_drive_to_terminal` (no logic divergence). Spine-13 is unchanged (this PROJECTS, it
        never writes a key); the bounded PORT (``run()``) and the dispatcher module default
        (``ContextBuilderRunner``) are byte-identical to pre-6.2. The harness drives the SAME compiled
        graph the dispatcher would (a ScenarioTransport-wired ``CompositeReadOnlyAdapter`` via
        :func:`build_default_compiled_runner`'s ``adapter`` seam) — so it measures the FULL AGENT (the
        agent's OWN tool selection + evidence + report through the compiled graph), NOT a shortcut
        (conjunction forbids bypassing the agent — Story 6.2 R3).
        """
        state = create_initial_state(incident_id=investigation_id, trigger=dict(trigger))
        status, terminal = await self._drive_to_terminal(state, max_iterations)
        return {"status": status, "state": cast(JsonValue, dict(terminal))}


# ---------------------------------------------------------------------------
# §2.6 — composition-root factory (AC2 seam). tools is imported LAZILY here so the module surface
# (build_compiled_graph + CompiledGraphRunner + stubs) stays tools-free (§2.7: the BUILDER receives
# the EXR node via DI; only this factory wires tools — graph→tools FORWARD, LEGAL).
# ---------------------------------------------------------------------------


def build_default_compiled_runner(
    *,
    max_hypotheses: int = 5,
    adapter: ReadOnlyAdapterPort | None = None,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> CompiledGraphRunner:
    """Composition root: assemble the POC-default compiled-graph runner.

    Builds the registry (2-1) + stub adapter (2-1) + router (2-3) + the 5 real nodes + the EXR node
    + the plan-promotion-wrapped HYP, compiles the graph (ONCE — AD-2) with the REAL ENV (4-2) + REAL
    REF (4-3) + the REAL WRT (5-1), and returns a ready ``CompiledGraphRunner``. Deterministic +
    dependency-light for tests.

    Story 7-4 (AD-11): ``checkpointer`` (default ``None``) opt-in bakes a durable saver into the
    compiled graph so ``run``/``resume`` persist + reload investigation state across restart. ``None``
    → BARE compile (byte-stable; the determinism harness / gate #6 compiles here, agent outputs
    UNCHANGED). The returned runner is flagged ``checkpointed`` iff a saver was given — so the
    byte-stable path NEVER emits a ``thread_id`` (gate #6 stays green).

    Production wiring (swapping this in as the default dispatcher) is applied at the composition root
    (``set_default_dispatcher(Dispatcher(runner=build_default_compiled_runner(), ...))``) — it is
    DEFERRED until Epic 5 makes the graph converge (the dispatcher module default stays
    ``ContextBuilderRunner``; Story 1-4 tests stay green). The Story-7-4 durable dispatcher is wired
    env-gated in ``routers/app`` (opt-in), NOT as the unconditional default.
    """
    # LAZY imports (graph→tools FORWARD — LEGAL; graph→graph.* same layer). Kept inside this composition
    # root so build_compiled_graph / CompiledGraphRunner / stubs stay tools-free (§2.7). Story 4-3 adds
    # the floor-registry YAML load (4-A1: ``import yaml`` lives HERE — the composition root that calls
    # load_floor_registry; the reflector NODE itself stays yaml-free / layer-pure).
    from pathlib import Path

    import yaml

    from graph.floor_check import build_floor_check, load_floor_registry
    from graph.hypothesis_sources import build_configured_hypothesis_source
    from graph.nodes.evidence_normalizer import build_evidence_normalizer
    from graph.nodes.executor_router import build_executor_router_node
    from graph.nodes.hypothesis_planner import build_hypothesis_planner
    from graph.nodes.incident_context_builder import incident_context_builder
    from graph.nodes.plan_validator import build_plan_validator
    from graph.nodes.preplanning_playbook_retriever import build_preplanning_playbook_retriever
    from graph.nodes.rca_writer import build_rca_writer
    from graph.nodes.reflector import build_reflector
    from tools.port import StubReadOnlyAdapter
    from tools.registry import build_default_registry
    from tools.router import ExecutorRouter

    # 6.2 seam: the composition-root adapter is INJECTABLE so the Story-6.2 benchmark harness wires a
    # ScenarioTransport-backed CompositeReadOnlyAdapter and drives the FULL agent over each scenario.
    # Default (None) → the StubReadOnlyAdapter — byte-identical to pre-6.2 (the production composition
    # root is UNCHANGED; the dispatcher module default stays ContextBuilderRunner; spine-13 untouched).
    if adapter is None:
        adapter = StubReadOnlyAdapter()
    registry = build_default_registry()
    router = ExecutorRouter(registry, adapter)

    # 4-3: load the deterministic floor registry (config/floor_registry.yaml — the 4-1 LOCKED data
    # location) → build the floor checker → build the REAL reflector. The POC default registry is EMPTY
    # → every trigger fail-closed (the honest degenerate state, D3; mirrors 3.5's honest default
    # planner). The checker is built ONCE + injected (DEC-3: the pure 4.1 mechanism, consumed not
    # modified). ``floors`` is wrapped under the ``floors:`` key (NOT bare top-level).
    floor_yaml_path = Path(__file__).resolve().parent.parent / "config" / "floor_registry.yaml"
    with floor_yaml_path.open(encoding="utf-8") as floor_file:
        floor_doc = yaml.safe_load(floor_file) or {}
    floors_raw = floor_doc.get("floors") if isinstance(floor_doc, Mapping) else {}
    floors = floors_raw if isinstance(floors_raw, Mapping) else {}
    floor_registry = load_floor_registry(floors)
    floor_checker = build_floor_check(registry=floor_registry)
    reflector = build_reflector(floor_checker=floor_checker)

    hypothesis_planner = build_plan_promoting_planner(
        build_hypothesis_planner(
            build_configured_hypothesis_source(), max_hypotheses=max_hypotheses
        )
    )
    graph = build_compiled_graph(
        incident_context_builder=incident_context_builder,
        preplanning_playbook_retriever=build_preplanning_playbook_retriever(adapter),
        hypothesis_planner=hypothesis_planner,
        plan_validator=build_plan_validator(),
        executor_router=build_executor_router_node(router=router),
        # 4-2: the REAL evidence_normalizer (was the 3-5 DEFERRED stub). The stub stays the DI-param
        # default (a no-op ENV is a valid test/composition choice — floor_check-stub discipline).
        evidence_normalizer=build_evidence_normalizer(),
        # 4-3: the REAL reflector (was the 3-5 DEFERRED stub). The stub stays the DI-param default (a
        # no-op "always write" REF is a valid test/composition choice — e.g. the 3-5 happy-path runner).
        reflector=reflector,
        # 5-1: the REAL rca_writer (was the 3-5 DEFERRED stub). The stub stays the DI-param default (a
        # report=None WRT is a valid test/composition choice — e.g. the 3-5 happy-path runner, which
        # exercises the REF→WRT→END edge without producing a cited report).
        rca_writer=build_rca_writer(),
        # 7-4: opt-in durable checkpointer (AD-11). None (default) → bare compile (byte-stable; the
        # determinism harness compiles here). A non-None saver bakes the checkpointer in at compile time
        # so run/resume persist to the store (AC1; swap = swap the saver object, not this factory).
        checkpointer=checkpointer,
    )
    return CompiledGraphRunner(graph, checkpointed=checkpointer is not None)


__all__ = [
    "CompiledGraphRunner",
    "build_compiled_graph",
    "build_default_compiled_runner",
    "build_plan_promoting_planner",
]
