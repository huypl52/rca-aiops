"""GraphRunner PORT — the entry-contract seam between dispatcher (services) and the compiled graph (Story 3-5).

Story 1.4 — AD-2 (entry contract) / AD-10 (async dispatch) / AD-9 (JSON-safe).

AD-2: services call the graph via an **entry contract** (``invoke``/``stream`` +
``investigation_id``), NOT by importing node functions or state internals. The
``GraphRunner`` Protocol below IS that entry contract. The dispatcher (services)
depends on the **port** only; the concrete runner is dependency-injected.

Story 1.4 ships a **minimal** runner that proves the async dispatch loop
end-to-end with real code (the 1-3 ``incident_context_builder`` node runs once →
terminal success). **Story 3-5 swaps this stub for the real compiled graph**
(``StateGraph(...).compile().ainvoke(...)``), implementing the SAME Protocol —
the dispatcher is unchanged. That swap is the load-bearing seam the leader
DEEP-reviews (3-5 plugs the compiled graph WITHOUT touching the dispatcher).

Why this lives in the ``graph`` layer (not ``services``): concrete runners may
import ``graph.state`` + ``graph.nodes`` (same layer) with no back-edge, AND the
Protocol must be importable by both the dispatcher (services, downstream) and the
concrete runners (graph, same layer). The only layer both can import without a
back-edge is ``graph`` itself — so the port lives here.

ONE-WAY (AD-1 / gate #2): imports ``graph.state`` + ``graph.nodes`` (same layer)
+ stdlib only. NEVER imports ``routers``/``services`` (back-edge forbidden).
"""

from __future__ import annotations

from typing import Protocol, TypedDict, runtime_checkable

from graph.nodes.incident_context_builder import incident_context_builder
from graph.state import InvestigationState, JsonValue, create_initial_state

# ONE-WAY (AD-1 / gate #2): graph.state + graph.nodes (same layer) + stdlib only.
# NEVER imports routers/services (back-edge forbidden) — this is the port BOTH
# the dispatcher (services) and the compiled graph (3-5) depend on.


class GraphRunnerResult(TypedDict, total=False):
    """Terminal result of running the graph for one investigation (AD-9 JSON-safe).

    Returned by a ``GraphRunner``. All values JSON-safe
    (str/dict/list/scalar/None). The dispatcher maps ``status`` onto the
    REGISTRY-LEVEL lifecycle status (``running``/``success``/``failed``) — it is
    NOT a key on the 13-key ``InvestigationState`` spine (AD-9 preserved).
    """

    status: str
    """Terminal status: ``"success"`` | ``"failed"`` | ``"partial"`` (``"partial"`` =
    max-iter exhausted / inconclusive — Story 4-3 / AD-10 #5, NOT a binary fail)."""

    state_snapshot: dict[str, JsonValue]
    """JSON-safe projection of the terminal state (AD-9). Bounded subset of the
    13-key spine (context / next_action / counts). No invented keys."""

    report: dict[str, JsonValue] | None
    """RCA report (FR-9); the cited report from the rca_writer node (Story 5-1 —
    AD-6 evidence-sourced), or ``None`` when WRT never ran (a PARTIAL) / on a minimal
    runner. The report is a STATE DICT on the 13-key spine (AD-9 — NO Pydantic model)."""


@runtime_checkable
class GraphRunner(Protocol):
    """PORT — graph entry contract (AD-2).

    The dispatcher calls this; it NEVER imports compiled-graph internals. Story
    1.4 defines the port + a minimal runner; Story 3-5 plugs the real compiled
    graph (same Protocol, dispatcher unchanged). Swap = the seam (AC2).
    """

    async def run(
        self,
        trigger: dict[str, JsonValue],
        investigation_id: str,
        max_iterations: int,
    ) -> GraphRunnerResult:
        """Run the investigation graph for ``investigation_id`` to terminal.

        Args:
            trigger: plain JSON-safe dict (``IncidentTrigger.model_dump()``, AD-9).
                The runner builds the ``InvestigationState`` internally (graph
                layer) — the dispatcher never touches state internals.
            investigation_id: the investigation handle (poll/resume key).
            max_iterations: dispatcher-level lifetime cap (FR-7); the runner
                honors it (exceed → ``status="partial"`` — Story 4-3 / AD-10 #5,
                an honest inconclusive outcome, NOT a binary fail).

        Returns:
            terminal ``GraphRunnerResult``. Raising propagates to the dispatcher,
            which maps it to registry ``status="failed"`` (NOT silent, AD-10 #5).
        """
        ...


def _snapshot_from_state(state: InvestigationState) -> dict[str, JsonValue]:
    """Bounded JSON-safe projection of state for the read-store/registry (AD-9).

    Subset of the 13-key spine: ``context`` + ``next_action`` + counts. No
    invented keys; every value JSON-safe (gate #3 axis). Downstream
    (3-5) may refine the projection — the bounded-no-invent contract holds.
    """
    context = state.get("context")
    next_action = state.get("next_action")
    evidence = state.get("evidence")
    tool_calls = state.get("tool_calls")
    return {
        "context": dict(context) if isinstance(context, dict) else {},
        "next_action": next_action if isinstance(next_action, str) else "",
        "evidence_count": len(evidence) if isinstance(evidence, list) else 0,
        "tool_calls_count": len(tool_calls) if isinstance(tool_calls, list) else 0,
    }


class StubGraphRunner:
    """Minimal stub runner — deterministic terminal success (no real node work).

    Proves the async dispatch loop without exercising any node. Story 3-5
    replaces it with the compiled graph. Useful as a default/fallback and for
    tests that only need the dispatch/store/resume mechanics (AC2 seam proof).
    """

    async def run(
        self,
        trigger: dict[str, JsonValue],
        investigation_id: str,
        max_iterations: int,
    ) -> GraphRunnerResult:
        del trigger, investigation_id, max_iterations  # unused — pure stub
        return GraphRunnerResult(
            status="success",
            state_snapshot={"context": {}},
            report=None,
        )


class ContextBuilderRunner:
    """Minimal REAL runner — runs the 1-3 entry node → terminal success.

    Proves the async dispatch loop end-to-end with real code: it builds the
    initial state from the trigger and runs the ``incident_context_builder`` node
    (Story 1-3), then projects a JSON-safe snapshot. Deterministic (AD-12 — the
    1-3 node is pure/deterministic; same trigger → same snapshot).

    This is the Story-1.4 default concrete runner. Story 3-5 swaps it for the
    full compiled graph (same ``GraphRunner`` Protocol; dispatcher unchanged).

    NOTE: we do NOT compile a graph here (``StateGraph(...).compile()`` = Story
    3-5). We merge the node's partial return by hand to reflect its effect in the
    snapshot — the real compiled graph applies reducers automatically.
    """

    async def run(
        self,
        trigger: dict[str, JsonValue],
        investigation_id: str,
        max_iterations: int,
    ) -> GraphRunnerResult:
        del max_iterations  # single node step — cap honored trivially (1 ≤ cap)
        state = create_initial_state(incident_id=investigation_id, trigger=dict(trigger))
        partial = incident_context_builder(state)
        context = partial.get("context")
        if isinstance(context, dict):
            # Simulate the upsert_context reducer (graph.state) — NOT compiling a
            # graph (that is Story 3-5); we only need the snapshot to reflect the
            # node's effect for the read-store projection.
            state["context"] = {**state.get("context", {}), **context}
        state["next_action"] = "context_built"
        return GraphRunnerResult(
            status="success",
            state_snapshot=_snapshot_from_state(state),
            report=None,
        )


__all__ = [
    "ContextBuilderRunner",
    "GraphRunner",
    "GraphRunnerResult",
    "StubGraphRunner",
]
