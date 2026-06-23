"""executor_router — §3.5 PE-R EXR node: read-only dispatch node-wiring (Story 3.5 — FR-5 / AD-3 / AD-4).

The **fifth** §3.5 node (flow ``ICB→PBR→HYP→VAL→EXR→ENV→REF``). It is **NODE-WIRING ONLY** — the
dispatch LOGIC + the read-only registry live in ``tools/`` (Story 2.3 router + Story 2.1 registry).
This node CALLS them; it reinvents nothing.

Story 3.5 closes the EXR gap. This node is built at the composition root
(``graph.compiled.build_default_compiled_runner``) and INJECTED into ``build_compiled_graph`` via the
``executor_router`` factory param (DI seam — mirrors 1-3/3-1/3-2/3-3/3-4). graph(2)→tools(4) is a
FORWARD edge (LEGAL — precedent ``preplanning_playbook_retriever.py:46 from tools.port``).

LOCKED mechanism (do NOT redesign):
  1. **Input = ``state.plan`` (the current plan; ``dict | None``, replace reducer).** Read DEFENSIVELY:
     missing / None / non-dict / no ``tool`` field → graceful degrade ``{"tool_calls": []}`` (nothing to
     execute; NEVER raises; Constraint 5). The "which plan" SELECTION is graph wiring
     (``build_plan_promoting_planner`` in ``graph.compiled`` — §2.2); this node executes THE plan in
     ``state.plan``.
  2. **Plan → kwargs translation (deterministic; ``timestamp_range`` → ``time_window`` rename ONLY).**
     ``tool = plan["tool"]``; ``time_window = plan.get("timestamp_range")``; every OTHER plan field
     (except ``tool`` and ``timestamp_range``) is passed through as-is as a dispatch kwarg. Which plan
     field NAMES match which executor kwargs (``query``/``service``/``namespace``/``pod``/...) is the
     PLAN-AUTHOR's concern (4.x/LLM) — **DEFERRED**. POC test plans use field names that ARE executor
     kwargs. Lock: the ``timestamp_range``→``time_window`` rename + passthrough; NOTHING else.
  3. **Dispatch via the 2-3 router (AC2):** ``router.dispatch(tool=tool, **kwargs)`` resolves via
     ``registry.lookup`` (2-1), dedupes by ``(tool, query, timestamp_range)``, and NEVER raises
     (unknown tool / executor raise → structured error envelope, ``dispatched=False``).
  4. **Record ``tool_calls`` ONLY when ``result.dispatched is True`` (carry-forward 2-3-A1).** A 2-3
     cache-HIT (``deduped=True``) OR a dispatch error emits NO new ``tool_calls`` record (matches
     AC2 "KHÔNG gọi trùng"). The record fields ALIGN with the router dedupe key — they ARE
     ``result.key``: ``{tool, query, timestamp_range, raw}`` where ``query`` = canonical non-time
     kwargs and ``timestamp_range`` = canonical ``time_window`` (mirror ``tools/router.py:_dedupe_key``
     — the state-level ``append_dedupe_tool_calls`` reducer dedupes on the SAME strings, so the two
     layers stay aligned). ``raw`` = ``result.raw`` (the executor's RAW dict — **NOT Evidence**; the
     evidence_normalizer 4-2 constructs Evidence; 4-2 boundary held).
  5. **Read-only HARD backstop = the registry (2-1, CI #1 HARD-FAIL) reached VIA the router (2-3).**
     This node adds NO write path — it dispatches ONLY what the registry holds, which holds ONLY
     read-only tools. Defense-in-depth: ``plan_validator`` (3-3) already rejected write/exec/probe
     plans BEFORE this node.
  6. **AD-4 partial state — return ``{"tool_calls": [<record>]}`` on a fresh dispatch, else
     ``{"tool_calls": []}``.** NO ``evidence`` (ENV 4-2), NO ``next_action``/``safety_flags``/invented
     keys. In the full topology EXR→ENV is a PLAIN edge (no routing signal needed from EXR).

ONE-WAY (AD-1 / gate #2 HARD-FAIL): imports ``graph.state`` (same layer) + ``tools.router``
(graph→tools FORWARD — LEGAL) + stdlib ONLY. NEVER ``routers``/``services``/``adapters``/``models``
(back-edge forbidden). lint-imports: 1 contract kept / 0 broken.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import cast

from graph.state import InvestigationState, JsonValue
from tools.router import DispatchResult, ExecutorRouter

# ONE-WAY (AD-1 / gate #2): graph.state (same layer) + tools.router (graph→tools FORWARD — LEGAL,
# precedent preplanning_playbook_retriever.py:46) + stdlib ONLY. NO routers/services/adapters/models.

# The two plan fields consumed by the plan→kwargs translation (§2): ``tool`` (the action selector) and
# ``timestamp_range`` (renamed to the executor ``time_window`` kwarg). Every OTHER plan field is passed
# through as a dispatch kwarg unchanged.
_TOOL_FIELD: str = "tool"
_TIMESTAMP_RANGE_FIELD: str = "timestamp_range"
_TIME_WINDOW_KWARG: str = "time_window"


def _plan_to_dispatch(plan: Mapping[str, JsonValue]) -> tuple[str, dict[str, object]] | None:
    """Translate a plan dict to ``(tool, kwargs)`` for ``router.dispatch`` (deterministic).

    ``tool = plan["tool"]`` (must be a non-empty ``str``); ``time_window = plan["timestamp_range"]``
    (the rename — the ONLY field-name transformation); every other plan field is passed through as a
    dispatch kwarg unchanged. Returns ``None`` when the plan is not dispatchable (no/invalid ``tool``)
    → the node degrades to ``{"tool_calls": []}`` (Constraint 5 — never raises).

    The richness of plan-field→executor-kwarg mapping (which plan field is ``query`` / ``service`` /
    ``namespace`` / ``pod`` / ...) is the PLAN-AUTHOR's concern (4.x/LLM) — **DEFERRED**. POC test plans
    use field names that ARE executor kwargs.
    """
    tool_value = plan.get(_TOOL_FIELD)
    if not isinstance(tool_value, str) or not tool_value:
        return None
    kwargs: dict[str, object] = {}
    for key, value in plan.items():
        if key in (_TOOL_FIELD, _TIMESTAMP_RANGE_FIELD):
            continue
        kwargs[key] = value
    kwargs[_TIME_WINDOW_KWARG] = plan.get(_TIMESTAMP_RANGE_FIELD)
    return tool_value, kwargs


def build_executor_router_node(
    *, router: ExecutorRouter
) -> Callable[[InvestigationState], dict[str, JsonValue]]:
    """Factory: build the §3.5 executor_router (EXR) node (DI seam — mirrors 1-3/3-1/3-2/3-3/3-4).

    Returns a node ``(state) -> partial-state-dict`` that:
      - reads ``state["plan"]`` defensively (missing/None/non-dict/no-tool → graceful degrade);
      - translates the plan to ``(tool, kwargs)`` (``timestamp_range``→``time_window`` rename only);
      - dispatches via the injected 2-3 ``router`` (→ 2-1 registry; never raises);
      - appends a ``tool_calls`` record ONLY on a fresh dispatch (``result.dispatched is True``), with
        fields ALIGNED to the router dedupe key (carry-forward 2-3-A1); a 2-3 cache hit / error emits
        NO new record;
      - returns AD-4 partial state ``{"tool_calls": [...]}``; NEVER raises (Constraint 5).

    Args:
        router: the injected ``ExecutorRouter`` (2-3) — built at the composition root from the
            registry (2-1) + adapter (2-2). The node holds NO registry/adapter reference directly.

    Returns:
        a §3.5 node returning PARTIAL state ``{"tool_calls": [...]}`` (AD-4 — exactly one key).
    """

    def executor_router(state: InvestigationState) -> dict[str, JsonValue]:
        # Constraint 5 — never raise: a missing/None/non-dict plan is nothing to execute → degrade.
        plan = state.get("plan")
        if not isinstance(plan, Mapping):
            return {"tool_calls": []}

        parsed = _plan_to_dispatch(plan)
        if parsed is None:
            # No valid ``tool`` → nothing to dispatch → degrade (graph loops back via VAL, bounded
            # by max_iterations FR-7).
            return {"tool_calls": []}
        tool, kwargs = parsed

        # Dispatch via the 2-3 router (→ 2-1 registry; never raises — unknown tool / executor raise
        # → structured error envelope, dispatched=False). Wrapped defensively regardless (Constraint 5).
        try:
            result: DispatchResult = router.dispatch(tool=tool, **kwargs)
        except Exception:  # noqa: BLE001 — the router never raises; defensive belt-and-braces
            return {"tool_calls": []}

        # 2-3-A1: record a NEW tool_calls entry ONLY on a fresh dispatch. A 2-3 cache hit
        # (deduped=True) OR an error (dispatched=False) emits NO new record ("KHÔNG gọi trùng").
        if not result.dispatched:
            return {"tool_calls": []}

        # Record fields ALIGN with the router dedupe key (carry-forward 2-3-A1): they ARE result.key
        # — (tool, query=canonical(identifying kwargs), timestamp_range=canonical(time_window)). The
        # state-level append_dedupe_tool_calls reducer dedupes on the SAME strings → two layers aligned.
        # ``raw`` is the executor's RAW dict (NOT Evidence — the evidence_normalizer 4-2 builds Evidence).
        record: dict[str, JsonValue] = {
            "tool": result.key[0],
            "query": result.key[1],
            "timestamp_range": result.key[2],
            "raw": cast(JsonValue, result.raw),
        }
        return {"tool_calls": [record]}

    return executor_router


__all__ = ["build_executor_router_node"]
