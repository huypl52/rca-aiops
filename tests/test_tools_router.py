"""Story 2.3 — executor_router dispatch logic + dispatch set + dedupe tool_calls.

Covers AC1-3 for the dispatch layer (FR-5 / AD-4 / spec §3.5):
  - AC1 — dispatch via the registry (``ReadOnlyRegistry.lookup``); unknown tool → structured error,
          no crash; the dispatch set is the registered read-only tools (no shadow executor map).
  - AC2 — dispatch-level dedupe by ``(tool, query, timestamp_range)``: a repeated tuple REUSES the
          prior RawOutput WITHOUT re-invoking the executor (``deduped=True``) — deterministic. This
          is DISPATCH-level dedupe; STATE-level ``tool_calls`` dedupe lives in graph/ (Story 0-3) and
          shares the SAME key shape (report to leader — no duplication).
  - AC3 — read-only: the router adds NO write path; only registered read-only tools are dispatched.

AD-3 (read-only boundary), AD-1 (one-way: tools↛graph/services/routers/adapters), AD-9 (JSON-safe),
AD-12 (determinism), 4.2 boundary (RAW dict, NOT Evidence).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from tools import ExecutorRouter
    from tools.port import RawOutput, TimeWindow

REPO_ROOT = Path(__file__).resolve().parents[1]

TIME_WINDOW: dict[str, str | None] = {"start": "2026-06-24T00:00:00Z", "end": None}


def _router() -> ExecutorRouter:
    """A router over the default registry + the deterministic stub adapter (AD-12)."""
    from tools import ExecutorRouter, StubReadOnlyAdapter, registry

    return ExecutorRouter(registry, StubReadOnlyAdapter())


# ---------------------------------------------------------------------------
# AC1 — dispatch via the registry; unknown tool → structured error, no crash
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tool", "kwargs"),
    [
        ("query_prometheus_raw", {"query": "up{service='checkout'}", "time_window": TIME_WINDOW}),
        ("query_loki_service_logs", {"service": "checkout", "time_window": TIME_WINDOW}),
        ("k8s_get_pods", {"namespace": "demo"}),
        ("k8s_describe_pod", {"namespace": "demo", "pod": "checkout-0"}),
        ("search_playbook", {"query": "DependencyTimeout", "top_k": 3}),
        ("topology_executor", {"service": "checkout"}),
    ],
)
def test_dispatch_routes_registered_tool_via_registry(tool: str, kwargs: dict[str, object]) -> None:
    """AC1: a registered tool dispatches through the registry and returns RAW output (dispatched)."""
    router = _router()
    result = router.dispatch(tool=tool, **kwargs)

    assert result.tool == tool
    assert result.dispatched is True
    assert result.deduped is False
    assert isinstance(result.raw, dict)
    # RAW output is JSON-safe (AD-9).
    assert json.loads(json.dumps(result.raw)) == result.raw


def test_dispatch_uses_registry_lookup_not_a_shadow_map() -> None:
    """AC1: dispatch resolves the executor via ReadOnlyRegistry.lookup (no shadow map).

    Proven indirectly + directly: the router is constructed from the registry, and dispatching a
    tool registered ONLY in a bespoke registry routes to THAT registry's executor (not a baked-in
    one)."""
    from tools import ExecutorRouter, ReadOnlyRegistry, StubReadOnlyAdapter

    sentinel = {"source_type": "sentinel", "ok": True}
    bespoke = ReadOnlyRegistry()
    bespoke.register("query_prometheus_raw", lambda adapter, **_: sentinel)  # type: ignore[arg-type]

    router = ExecutorRouter(bespoke, StubReadOnlyAdapter())
    result = router.dispatch(tool="query_prometheus_raw", query="up", time_window=TIME_WINDOW)
    assert result.raw == sentinel  # routed through OUR registry's executor, not the default


def test_unknown_tool_is_structured_not_a_crash() -> None:
    """AC1 / Constraint 5: an unregistered tool name → structured error envelope, NEVER raises."""
    from tools import ExecutorRouter, ReadOnlyRegistry, StubReadOnlyAdapter

    router = ExecutorRouter(ReadOnlyRegistry(), StubReadOnlyAdapter())
    # No registry contains "exec" — and even if it did, the registry would have REJECTED a deny-verb
    # name at registration (2-1). Here it is simply unknown → structured error.
    result = router.dispatch(tool="exec", namespace="demo")

    assert result.dispatched is False
    assert result.deduped is False
    assert isinstance(result.raw, dict)
    err = result.raw["error"]
    assert isinstance(err, dict)
    assert err["code"] == "unknown_tool"
    assert "exec" in str(err["detail"])


def test_unknown_tool_does_not_raise() -> None:
    """Constraint 5: dispatch never raises on a bad tool name (smoke — no exception escapes)."""
    router = _router()
    router.dispatch(tool="this_tool_does_not_exist", x=1)  # must not raise


def test_executor_exception_is_folded_into_envelope() -> None:
    """Constraint 5: an executor that raises on malformed kwargs → structured envelope, no raise."""
    from tools import ExecutorRouter, ReadOnlyRegistry, StubReadOnlyAdapter

    reg = ReadOnlyRegistry()

    def boom(adapter: object, **_: object) -> dict[str, object]:
        raise ValueError("bad kwargs")

    reg.register("kaboom", boom)  # type: ignore[arg-type]
    router = ExecutorRouter(reg, StubReadOnlyAdapter())
    result = router.dispatch(tool="kaboom")

    assert result.dispatched is False
    err = result.raw["error"]
    assert isinstance(err, dict)
    assert err["code"] == "executor_error"
    assert "ValueError" in str(err["detail"])


# ---------------------------------------------------------------------------
# AC2 — dispatch-level dedupe by (tool, query, timestamp_range)
# ---------------------------------------------------------------------------


class _CountingAdapter:
    """Stub-shaped adapter that COUNTS how many times each read method is invoked (dedupe spy).

    Implements ``ReadOnlyAdapterPort`` structurally (exact port signatures) so it type-checks as the
    port AND ``isinstance(_, ReadOnlyAdapterPort)`` holds. Pure/deterministic — fixed returns keyed
    only by the call args; no clock/random/network (AD-12).
    """

    def __init__(self) -> None:
        self.calls = 0

    def query_promql(self, *, query: str, time_window: TimeWindow) -> RawOutput:
        self.calls += 1
        return {"source_type": "prometheus", "query": query, "n": self.calls}

    def query_loki(
        self, *, service: str, time_window: TimeWindow, correlation_id: str | None
    ) -> RawOutput:
        self.calls += 1
        return {"source_type": "loki", "service": service, "n": self.calls}

    def k8s_get(self, *, namespace: str, label_selector: str | None) -> RawOutput:
        self.calls += 1
        return {"source_type": "kubernetes", "namespace": namespace, "n": self.calls}

    def k8s_describe(self, *, namespace: str, pod: str) -> RawOutput:
        self.calls += 1
        return {"source_type": "kubernetes", "pod": pod, "n": self.calls}

    def k8s_logs(self, *, namespace: str, pod: str, previous: bool) -> RawOutput:
        self.calls += 1
        return {"source_type": "kubernetes", "pod": pod, "n": self.calls}

    def k8s_get_events(self, *, namespace: str, field_selector: str | None) -> RawOutput:
        self.calls += 1
        return {"source_type": "kubernetes", "namespace": namespace, "n": self.calls}

    def search_playbook(self, *, query: str, top_k: int) -> RawOutput:
        self.calls += 1
        return {"source_type": "playbook", "query": query, "n": self.calls}

    def topology_read(self, *, service: str | None) -> RawOutput:
        self.calls += 1
        return {"source_type": "topology", "service": service, "n": self.calls}


def test_dedupe_same_tuple_reuses_result_without_reinvoking() -> None:
    """AC2: the SAME (tool, query, timestamp_range) tuple → reuse the prior RawOutput, no re-invoke.

    The executor is invoked EXACTLY ONCE; the second dispatch is a cache hit (deduped=True) and
    returns the SAME object identity (no fresh dispatch)."""
    from tools import ExecutorRouter, registry

    adapter = _CountingAdapter()
    router = ExecutorRouter(registry, adapter)

    r1 = router.dispatch(
        tool="query_prometheus_raw", query="up{service='checkout'}", time_window=TIME_WINDOW
    )
    r2 = router.dispatch(
        tool="query_prometheus_raw", query="up{service='checkout'}", time_window=TIME_WINDOW
    )

    assert adapter.calls == 1, "executor must NOT be re-invoked on a dedupe hit (AC2)"
    assert r1.dispatched is True and r1.deduped is False
    assert r2.dispatched is False and r2.deduped is True
    assert r2.raw == r1.raw  # reuse the SAME result
    assert r1.key == r2.key  # same (tool, query, timestamp_range) tuple


def test_dedupe_different_query_invokes_again() -> None:
    """AC2: a DIFFERENT query (same tool) → distinct key → fresh dispatch (not deduped)."""
    from tools import ExecutorRouter, registry

    adapter = _CountingAdapter()
    router = ExecutorRouter(registry, adapter)

    r1 = router.dispatch(tool="query_prometheus_raw", query="up", time_window=TIME_WINDOW)
    r2 = router.dispatch(tool="query_prometheus_raw", query="go", time_window=TIME_WINDOW)

    assert adapter.calls == 2
    assert r1.deduped is False and r2.deduped is False
    assert r1.key != r2.key


def test_dedupe_different_timestamp_range_invokes_again() -> None:
    """AC2: a DIFFERENT timestamp_range (same tool+query) → distinct key → fresh dispatch."""
    from tools import ExecutorRouter, registry

    adapter = _CountingAdapter()
    router = ExecutorRouter(registry, adapter)
    other_window: dict[str, str | None] = {"start": "2026-06-24T01:00:00Z", "end": None}

    r1 = router.dispatch(tool="query_prometheus_raw", query="up", time_window=TIME_WINDOW)
    r2 = router.dispatch(tool="query_prometheus_raw", query="up", time_window=other_window)

    assert adapter.calls == 2
    assert r1.key[0] == r2.key[0] and r1.key[1] == r2.key[1]  # tool + query equal
    assert r1.key[2] != r2.key[2]  # timestamp_range differs → distinct key


def test_dedupe_different_tool_invokes_again() -> None:
    """AC2: a DIFFERENT tool → distinct key → fresh dispatch (the tool component is part of the key)."""
    from tools import ExecutorRouter, registry

    adapter = _CountingAdapter()
    router = ExecutorRouter(registry, adapter)

    r1 = router.dispatch(tool="query_prometheus_raw", query="up", time_window=TIME_WINDOW)
    r2 = router.dispatch(
        tool="query_loki_service_logs",
        service="checkout",
        query='service="checkout"',
        time_window=TIME_WINDOW,
    )

    assert adapter.calls == 2
    assert r1.key[0] != r2.key[0]


def test_dedupe_key_shape_is_tool_query_timestamp_range() -> None:
    """AC2 / AD-10: the dedupe key is the EXACT tuple shape (tool, query, timestamp_range)."""
    from tools import ExecutorRouter, registry

    router = ExecutorRouter(registry, _CountingAdapter())
    result = router.dispatch(tool="query_prometheus_raw", query="up", time_window=TIME_WINDOW)

    key = result.key
    assert isinstance(key, tuple)
    assert len(key) == 3
    assert key[0] == "query_prometheus_raw"  # tool
    # query + timestamp_range are canonical JSON strings (deterministic, hashable).
    assert isinstance(key[1], str) and isinstance(key[2], str)
    assert json.loads(key[2]) == TIME_WINDOW  # timestamp_range round-trips to the time_window


def test_dedupe_is_deterministic_across_instances() -> None:
    """AD-12: same dispatch sequence → same key, same reused result (no PYTHONHASHSEED drift)."""
    from tools import ExecutorRouter, registry

    a = ExecutorRouter(registry, _CountingAdapter())
    b = ExecutorRouter(registry, _CountingAdapter())
    kwargs = {"query": "up{service='checkout'}", "time_window": TIME_WINDOW}

    ra1 = a.dispatch(tool="query_prometheus_raw", **kwargs)
    rb1 = b.dispatch(tool="query_prometheus_raw", **kwargs)
    ra2 = a.dispatch(tool="query_prometheus_raw", **kwargs)  # dedupe hit on `a`

    assert ra1.key == rb1.key == ra2.key
    assert ra2.raw == ra1.raw and ra2.deduped is True


def test_dedupe_repeated_many_times_invokes_once() -> None:
    """AC2 stress: N identical dispatches → executor invoked exactly once, all hits reuse."""
    from tools import ExecutorRouter, registry

    adapter = _CountingAdapter()
    router = ExecutorRouter(registry, adapter)
    first = router.dispatch(tool="topology_executor", service="checkout")

    for _ in range(5):
        hit = router.dispatch(tool="topology_executor", service="checkout")
        assert hit.deduped is True
        assert hit.raw == first.raw

    assert adapter.calls == 1
    assert router.cache_size() == 1


def test_non_time_windowed_tool_dedupes_without_timestamp_range() -> None:
    """AC2: a tool with no time_window (topology) still dedupes — timestamp_range is None."""
    from tools import ExecutorRouter, registry

    adapter = _CountingAdapter()
    router = ExecutorRouter(registry, adapter)
    r1 = router.dispatch(tool="topology_executor", service="checkout")
    r2 = router.dispatch(tool="topology_executor", service="checkout")
    assert r1.deduped is False and r2.deduped is True
    assert adapter.calls == 1


# ---------------------------------------------------------------------------
# AC3 — read-only: router adds NO write path (only registered read-only tools dispatch)
# ---------------------------------------------------------------------------


def test_router_has_no_write_path_in_source() -> None:
    """AC3 / leader grep: tools/router.py source has no hidden write path / deny-verb def."""
    src = (REPO_ROOT / "tools" / "router.py").read_text(encoding="utf-8")
    for forbidden in (
        "subprocess",
        "os.system",
        "os.exec",
        "requests.",
        "open(",
        "kubectl",
    ):
        assert forbidden not in src, f"tools/router.py contains forbidden token '{forbidden}'"


def test_router_writes_no_evidence() -> None:
    """4.2 boundary: the router forwards RAW dicts; it never constructs/imports Evidence."""
    src = (REPO_ROOT / "tools" / "router.py").read_text(encoding="utf-8")
    assert "Evidence(" not in src
    assert "from models" not in src and "import models" not in src


def test_router_imports_no_forbidden_layers() -> None:
    """AD-1 one-way (gate#2): tools/router.py imports only tools.* + stdlib; no back-edge.

    AST-based (not substring) so explanatory docstring prose mentioning ``graph`` is not a false
    positive — only actual ``import``/``from`` statements are checked. The authoritative gate is
    ``uv run lint-imports`` (gate #2); this is a local belt-and-braces mirror."""
    import ast

    tree = ast.parse((REPO_ROOT / "tools" / "router.py").read_text(encoding="utf-8"))
    forbidden_layers = {"graph", "services", "routers", "adapters", "models"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = {n.name.split(".")[0] for n in node.names}
        elif isinstance(node, ast.ImportFrom):
            modules = {node.module.split(".")[0]} if node.module else set()
        else:
            continue
        assert not (modules & forbidden_layers), (
            f"tools/router.py imports a forbidden layer: {modules & forbidden_layers}"
        )


def test_router_method_names_are_not_deny_verbs() -> None:
    """AC3: no router method/attribute name equals a deny-verb (gate #1 AST exact-match safe)."""
    import ast

    from ci.denyset import WRITE_VERBS

    tree = ast.parse((REPO_ROOT / "tools" / "router.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        name = getattr(node, "name", None) or getattr(node, "attr", None)
        if name is not None:
            assert name not in WRITE_VERBS, f"deny-verb name '{name}' in tools/router.py (AD-3)"


# ---------------------------------------------------------------------------
# Integration — gate #1 still PASSes on tools/ (router adds no read-only violation)
# ---------------------------------------------------------------------------


def test_gate1_passes_on_tools_with_router() -> None:
    """AC3: gate #1 exit 0 — the router module adds NO deny-verb to the now-larger tools/."""
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "ci" / "gate1_readonly_registry.py"),
            "--root",
            str(REPO_ROOT),
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, f"gate #1 must PASS on tools/:\n{result.stdout}\n{result.stderr}"
    assert "PASS" in result.stdout


def test_router_exported_from_tools() -> None:
    """The router + result types are part of the tools package surface (E3 imports them)."""
    from tools import DispatchResult, ExecutorRouter

    assert callable(ExecutorRouter)
    assert DispatchResult.__name__ == "DispatchResult"
