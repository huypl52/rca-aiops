"""tests for the §3.5 executor_router (EXR) node — Story 3.5 AC1 (node-wiring) + carry-forward 2-3-A1.

The EXR node is NODE-WIRING ONLY over the 2-3 router (dispatch logic) + 2-1 registry (read-only
backstop). These tests pin: (a) it executes ``state.plan`` via the injected router; (b) it emits a
``tool_calls`` record ONLY on a fresh dispatch (``dispatched=True``) — a 2-3 cache hit / dispatch
error emits NOTHING (carry-forward 2-3-A1, "KHÔNG gọi trùng"); (c) the record fields ALIGN with the
router dedupe key; (d) it NEVER raises (Constraint 5) — missing plan / router raise → graceful
degrade ``{"tool_calls": []}``; (e) it returns AD-4 partial state with EXACTLY one key.

AST-discipline (docstring-immune): assertions are statement-level, not in docstrings.
"""

from __future__ import annotations

from typing import cast

import pytest

from graph.nodes.executor_router import build_executor_router_node
from graph.state import InvestigationState, JsonValue, create_initial_state
from tools.port import StubReadOnlyAdapter
from tools.registry import build_default_registry
from tools.router import DispatchResult, ExecutorRouter

# A dispatchable plan: ``query_prometheus_raw`` (2-1 §3.6 row 2) takes ``query`` + ``time_window``.
# EXR renames ``timestamp_range``→``time_window`` and passes every other field through, so this plan
# yields kwargs ``{query, time_window}`` — exactly the executor's signature (PROVES the rename).
_TOOL_PROMQL = "query_prometheus_raw"
_VALID_PLAN: dict[str, JsonValue] = {
    "tool": _TOOL_PROMQL,
    "query": "up",
    "timestamp_range": {"start": "2026-06-24T00:00:00Z", "end": "2026-06-24T01:00:00Z"},
}


def _router() -> ExecutorRouter:
    return ExecutorRouter(build_default_registry(), StubReadOnlyAdapter())


def _state_with_plan(plan: object) -> InvestigationState:
    state = create_initial_state(incident_id="inv-exr", trigger={"canonical_trigger": "x"})
    state["plan"] = cast(dict[str, JsonValue] | None, plan)
    return state


# ---------------------------------------------------------------------------
# AC1 — executes state.plan via the injected 2-3 router; record emitted only on fresh dispatch
# ---------------------------------------------------------------------------


def test_exr_dispatches_plan_and_emits_aligned_record() -> None:
    """Fresh dispatch → exactly one ``tool_calls`` record whose fields ARE the router dedupe key."""
    router = _router()
    node = build_executor_router_node(router=router)
    record_list = node(_state_with_plan(_VALID_PLAN))["tool_calls"]
    assert isinstance(record_list, list)
    assert len(record_list) == 1
    record = record_list[0]
    assert isinstance(record, dict)
    # The record exposes EXACTLY the dedupe-key fields + raw (AD-4 partial — no invented keys).
    assert set(record.keys()) == {"tool", "query", "timestamp_range", "raw"}
    # 2-3-A1: fields ALIGN with the router's own dedupe key for the same dispatch.
    expected = router.dispatch(
        tool=_TOOL_PROMQL,
        query="up",
        time_window={"start": "2026-06-24T00:00:00Z", "end": "2026-06-24T01:00:00Z"},
    )
    assert record["tool"] == expected.key[0]
    assert record["query"] == expected.key[1]
    assert record["timestamp_range"] == expected.key[2]
    assert record["raw"] == expected.raw


def test_exr_cache_hit_emits_no_new_record() -> None:
    """Carry-forward 2-3-A1: a 2-3 dedupe cache hit (deduped=True, dispatched=False) → NO new record."""
    router = _router()
    node = build_executor_router_node(router=router)
    first = node(_state_with_plan(_VALID_PLAN))["tool_calls"]
    assert isinstance(first, list) and len(first) == 1  # sanity: first call IS a fresh dispatch
    # Second identical dispatch → the router returns a cache hit → EXR emits nothing.
    second = node(_state_with_plan(_VALID_PLAN))["tool_calls"]
    assert second == []


def test_exr_unknown_tool_emits_no_record() -> None:
    """AC3 / Constraint 5: an unknown tool → structured error (dispatched=False) → NO new record."""
    router = _router()
    node = build_executor_router_node(router=router)
    bad_plan: dict[str, JsonValue] = {
        "tool": "not_a_real_tool",
        "query": "x",
        "timestamp_range": {},
    }
    result = node(_state_with_plan(bad_plan))["tool_calls"]
    assert result == []


def test_exr_returns_exactly_one_partial_key() -> None:
    """AD-4: EXR returns PARTIAL state with EXACTLY the ``tool_calls`` key (no evidence/next_action)."""
    node = build_executor_router_node(router=_router())
    partial = node(_state_with_plan(_VALID_PLAN))
    assert isinstance(partial, dict)
    assert set(partial.keys()) == {"tool_calls"}


# ---------------------------------------------------------------------------
# Constraint 5 — never raises; graceful degrade to {"tool_calls": []}
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "plan",
    [
        None,  # no plan
        "not-a-dict",  # wrong type
        {},  # empty — no tool
        {"query": "x", "timestamp_range": {}},  # missing tool
        {"tool": 123, "query": "x", "timestamp_range": {}},  # tool not a str
        {"tool": "", "query": "x", "timestamp_range": {}},  # empty tool string
    ],
)
def test_exr_degrades_on_undispatchable_plan(plan: object) -> None:
    """Missing / malformed / tool-less plan → degrade to ``{"tool_calls": []}``, never raises."""
    node = build_executor_router_node(router=_router())
    partial = node(_state_with_plan(plan))
    assert partial == {"tool_calls": []}


def test_exr_never_raises_when_router_raises() -> None:
    """Constraint 5 belt-and-braces: even if the injected router raises, the node degrades."""

    class _ExplodingRouter:
        def dispatch(self, *, tool: str, **kwargs: object) -> DispatchResult:  # noqa: ARG002
            raise RuntimeError("boom")

    node = build_executor_router_node(router=cast(ExecutorRouter, _ExplodingRouter()))
    partial = node(_state_with_plan(_VALID_PLAN))
    assert partial == {"tool_calls": []}


def test_exr_readonly_backstop_via_registry() -> None:
    """FR-5 / AD-3: EXR dispatches ONLY tools the read-only registry holds — no write path here.

    The registry (2-1, CI #1 HARD-FAIL) IS the dispatch mechanism; EXR adds no write/exec/probe
    path. A read-only-violating verb in a tool name cannot be registered (2-1); here we assert the
    node simply does not invent a tool — an unknown tool degrades (covered above). This test pins
    the INTEGRATION: the real registry + stub adapter route a real read-only query end-to-end.
    """
    router = _router()
    node = build_executor_router_node(router=router)
    partial = node(_state_with_plan(_VALID_PLAN))
    calls = partial["tool_calls"]
    assert isinstance(calls, list) and calls  # one fresh dispatch
    record = calls[0]
    assert isinstance(record, dict)
    tool_name = record["tool"]
    # The dispatched tool is a real read-only §3.6 executor name present in the default registry.
    assert isinstance(tool_name, str) and tool_name in build_default_registry().names()
