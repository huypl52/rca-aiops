"""Story 3.1 — preplanning_playbook_retriever node (§3.5): top-K Qdrant + graceful degrade.

Covers the ACs:
  - AC1 — retrieve top-K playbooks via the injected adapter; forward hits to ``playbook_hits``.
  - AC2 — graceful degrade: empty hits OR adapter error envelope OR missing canonical_trigger OR
          adapter raise → ``{"playbook_hits": []}``, NEVER raises, NEVER blocks the planner.
  - AC3 — retrieve-only: writes ONLY ``playbook_hits`` (no hypothesis / evidence / next_action).
  - AC4 — REUSES ``append_dedupe_playbook_hits`` (0-3); NO node-local dedupe; PARTIAL return.
  - AC5 — DETERMINISTIC (AD-12): same state → same hits; no wall-clock/random/hash; NO timestamp
          in playbook_hits (AST scan of node source).
  - AC6 — DI seam: factory ``build_preplanning_playbook_retriever(adapter, *, top_k)``; the node
          calls ``adapter.search_playbook`` DIRECTLY (NOT executor_router); adapter + top_k injected.
  - AC7 — one-way AD-1 / gate #2: node in graph/, imports graph.state + tools.port (FORWARD) + stdlib
          only; NO routers/services/adapters/models; RAW passthrough (no Evidence construction).
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from graph.nodes.preplanning_playbook_retriever import build_preplanning_playbook_retriever
from graph.state import (
    InvestigationState,
    JsonValue,
    append_dedupe_playbook_hits,
    create_initial_state,
)

if TYPE_CHECKING:
    from tools.port import RawOutput, TimeWindow

NODE_FILE = (
    Path(__file__).resolve().parents[1] / "graph" / "nodes" / "preplanning_playbook_retriever.py"
)


# ---------------------------------------------------------------------------
# Fixtures — a configurable probe adapter implementing ReadOnlyAdapterPort
# ---------------------------------------------------------------------------


class _ProbeAdapter:
    """Configurable read-only adapter implementing ``ReadOnlyAdapterPort`` (AC2 degrade modes).

    ``search_playbook`` behavior is selected by ``mode``:
      - "hits"  → return the configured ``hits`` (success).
      - "empty" → success with ``hits=[]``.
      - "error" → return an adapter ERROR ENVELOPE (transport/backend shape from 2-2).
      - "raise" → raise (simulate an unexpected adapter exception).
    Records the last (query, top_k) so tests assert the node called the adapter with the right args.
    Pure/deterministic except the deliberate "raise" mode. The other 7 port methods are unused stubs.
    """

    def __init__(
        self, *, mode: str = "hits", hits: list[dict[str, JsonValue]] | None = None
    ) -> None:
        self.mode = mode
        self.hits = hits if hits is not None else []
        self.last_query: str | None = None
        self.last_top_k: int | None = None

    def search_playbook(self, *, query: str, top_k: int) -> RawOutput:
        self.last_query = query
        self.last_top_k = top_k
        if self.mode == "raise":
            raise RuntimeError("simulated adapter failure")
        if self.mode == "error":
            return {
                "source_type": "playbook",
                "error": {"code": "transport_error", "detail": "boom"},
            }
        return {"source_type": "playbook", "query": query, "top_k": top_k, "hits": list(self.hits)}

    # --- unused port stubs (satisfy ReadOnlyAdapterPort structurally) ---
    def query_promql(self, *, query: str, time_window: TimeWindow) -> RawOutput:
        return {"source_type": "prometheus"}

    def query_loki(
        self, *, service: str, time_window: TimeWindow, correlation_id: str | None
    ) -> RawOutput:
        return {"source_type": "loki"}

    def k8s_get(self, *, namespace: str, label_selector: str | None) -> RawOutput:
        return {"source_type": "kubernetes"}

    def k8s_describe(self, *, namespace: str, pod: str) -> RawOutput:
        return {"source_type": "kubernetes"}

    def k8s_logs(self, *, namespace: str, pod: str, previous: bool) -> RawOutput:
        return {"source_type": "kubernetes"}

    def k8s_get_events(self, *, namespace: str, field_selector: str | None) -> RawOutput:
        return {"source_type": "kubernetes"}

    def topology_read(self, *, service: str | None) -> RawOutput:
        return {"source_type": "topology"}


def _state(
    *, canonical_trigger: JsonValue = "DependencyTimeout", service: JsonValue = "checkout"
) -> InvestigationState:
    """A partial state with a trigger (canonical_trigger) + context (service)."""
    state = create_initial_state()
    state["trigger"] = {"canonical_trigger": canonical_trigger, "service": service}
    state["context"] = {"service": service, "namespace": "demo"}
    return state


def _hits_of(result: dict[str, JsonValue]) -> list[dict[str, JsonValue]]:
    """Narrow ``result["playbook_hits"]`` (JsonValue) to a list for assertion (mypy-safe).

    Mirrors the ``_context_of`` narrowing pattern in ``test_incident_context_builder.py``.
    """
    hits = result["playbook_hits"]
    assert isinstance(hits, list)
    return [h for h in hits if isinstance(h, dict)]


def _hits(n: int) -> list[dict[str, JsonValue]]:
    return [
        {"id": f"pb-{i}", "score": round(1.0 - i * 0.1, 2), "title": f"Playbook {i}"}
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# AC1 / AC6 — retrieve via the injected adapter; forward hits; call DIRECTLY
# ---------------------------------------------------------------------------


def test_retrieves_and_forwards_hits_to_playbook_hits() -> None:
    """AC1/AC6: success hits → forwarded to playbook_hits as {id,score,title} items."""
    adapter = _ProbeAdapter(mode="hits", hits=_hits(3))
    node = build_preplanning_playbook_retriever(adapter, top_k=3)

    result = node(_state())

    assert set(result.keys()) == {"playbook_hits"}
    forwarded = result["playbook_hits"]
    assert isinstance(forwarded, list)
    assert len(forwarded) == 3
    # Forwarded item = exactly {id, score, title} — NO invented fields.
    assert forwarded[0] == {"id": "pb-0", "score": 1.0, "title": "Playbook 0"}


def test_node_calls_adapter_search_playbook_directly_not_router() -> None:
    """AC6: the node calls adapter.search_playbook DIRECTLY (top_k + query injected)."""
    adapter = _ProbeAdapter(mode="hits", hits=_hits(2))
    node = build_preplanning_playbook_retriever(adapter, top_k=7)

    node(_state())

    assert adapter.last_query is not None
    assert adapter.last_top_k == 7  # injected top_k reaches the adapter
    assert (
        "DependencyTimeout" in adapter.last_query
    )  # canonical_trigger is the primary query signal


def test_factory_closes_over_adapter_and_top_k() -> None:
    """AC6: the factory closes over the adapter + top_k (DI seam); two factories are independent."""
    a = _ProbeAdapter(mode="hits", hits=_hits(1))
    b = _ProbeAdapter(mode="hits", hits=_hits(2))
    node_a = build_preplanning_playbook_retriever(a, top_k=1)
    node_b = build_preplanning_playbook_retriever(b, top_k=2)

    ra = node_a(_state())
    rb = node_b(_state())

    assert len(_hits_of(ra)) == 1
    assert len(_hits_of(rb)) == 2
    assert a.last_top_k == 1 and b.last_top_k == 2


# ---------------------------------------------------------------------------
# AC2 — graceful degrade: empty / error envelope / missing trigger / adapter raise
# ---------------------------------------------------------------------------


def test_empty_hits_degrade_to_empty_playbook_hits() -> None:
    """AC2: success but hits=[] → {"playbook_hits": []} (planner proceeds with evidence only)."""
    adapter = _ProbeAdapter(mode="empty")
    node = build_preplanning_playbook_retriever(adapter)

    result = node(_state())

    assert result == {"playbook_hits": []}


def test_error_envelope_degrades_to_empty_playbook_hits() -> None:
    """AC2: adapter error envelope (transport/backend) → {"playbook_hits": []}, no raise."""
    adapter = _ProbeAdapter(mode="error")
    node = build_preplanning_playbook_retriever(adapter)

    result = node(_state())

    assert result == {"playbook_hits": []}


def test_adapter_raise_degrades_to_empty_playbook_hits() -> None:
    """AC2 / Constraint 5: an adapter exception → {"playbook_hits": []}, NEVER raises into graph."""
    adapter = _ProbeAdapter(mode="raise")
    node = build_preplanning_playbook_retriever(adapter)

    result = node(_state())  # must not raise

    assert result == {"playbook_hits": []}


@pytest.mark.parametrize(
    ("trigger_value", "ctx"),
    [
        (None, {"service": "checkout"}),
        ("", {"service": "checkout"}),
        (123, {"service": "checkout"}),  # non-str
    ],
)
def test_missing_or_bad_canonical_trigger_degrades_without_calling_adapter(
    trigger_value: JsonValue, ctx: dict[str, JsonValue]
) -> None:
    """AC2: missing/None/empty/non-str canonical_trigger → empty hits WITHOUT calling the adapter."""
    adapter = _ProbeAdapter(mode="hits", hits=_hits(5))
    node = build_preplanning_playbook_retriever(adapter)

    state = create_initial_state()
    state["trigger"] = {"canonical_trigger": trigger_value}
    state["context"] = ctx
    result = node(state)

    assert result == {"playbook_hits": []}
    assert adapter.last_query is None  # adapter was NOT called


def test_missing_trigger_key_degrades_to_empty() -> None:
    """AC2 / Constraint 5: no trigger key at all → empty hits, no raise."""
    adapter = _ProbeAdapter(mode="hits", hits=_hits(3))
    node = build_preplanning_playbook_retriever(adapter)

    state = create_initial_state()  # no trigger / no context
    result = node(state)

    assert result == {"playbook_hits": []}
    assert adapter.last_query is None


def test_node_never_raises_on_malformed_state() -> None:
    """Constraint 5 smoke: any malformed partial state → a dict, never an exception."""
    node = build_preplanning_playbook_retriever(_ProbeAdapter(mode="hits", hits=_hits(1)))
    # Deliberately malformed states (wrong-typed trigger/context) — the node must tolerate them
    # at RUNTIME (Constraint 5). Cast for the call; the value is structurally wrong on purpose.
    bad_states: tuple[dict[str, object], ...] = (
        dict(create_initial_state()),
        {**dict(create_initial_state()), "trigger": "not-a-dict"},
        {
            **dict(create_initial_state()),
            "trigger": {"canonical_trigger": "X"},
            "context": "not-a-dict",
        },
    )
    for bad in bad_states:
        assert isinstance(node(cast(InvestigationState, bad)), dict)  # never raises


# ---------------------------------------------------------------------------
# AC3 — retrieve-only scope (writes ONLY playbook_hits)
# ---------------------------------------------------------------------------


def test_node_returns_exactly_one_key_playbook_hits() -> None:
    """AC3: the node returns ONLY {"playbook_hits": ...} — no hypothesis/evidence/next_action/etc."""
    node = build_preplanning_playbook_retriever(_ProbeAdapter(mode="hits", hits=_hits(2)))
    result = node(_state())
    assert set(result.keys()) == {"playbook_hits"}


def test_node_does_not_invent_state_keys() -> None:
    """AC3: no hypothesis / evidence / plan / sufficiency / next_action / report invention."""
    node = build_preplanning_playbook_retriever(_ProbeAdapter(mode="hits", hits=_hits(1)))
    result = node(_state())
    for forbidden in (
        "hypotheses",
        "evidence",
        "plan",
        "sufficiency",
        "next_action",
        "report",
        "tool_calls",
    ):
        assert forbidden not in result, f"node invented forbidden state key '{forbidden}'"


# ---------------------------------------------------------------------------
# AC4 — REUSE the 0-3 reducer; NO node-local dedupe; PARTIAL return
# ---------------------------------------------------------------------------


def test_node_does_not_local_dedupe_relieves_on_reducer() -> None:
    """AC4: the node returns ALL hits (no node-local dedupe) — the 0-3 reducer owns dedupe."""
    # Two identical hits — the node must forward BOTH; the reducer (tested next) drops the dup.
    dup_hits: list[dict[str, JsonValue]] = [
        {"id": "pb-0", "score": 0.9, "title": "Same"},
        {"id": "pb-0", "score": 0.9, "title": "Same"},
    ]
    node = build_preplanning_playbook_retriever(_ProbeAdapter(mode="hits", hits=dup_hits))
    result = node(_state())
    assert len(_hits_of(result)) == 2  # node forwards both; does NOT pre-dedupe


def test_reducer_dedupes_what_the_node_forwards() -> None:
    """AC4: append_dedupe_playbook_hits (0-3, REUSED) dedupes the node's output (whole-item identity)."""
    node = build_preplanning_playbook_retriever(_ProbeAdapter(mode="hits", hits=_hits(3)))
    out = node(_state())
    hits = _hits_of(out)
    # Merge the node's output twice via the REUSED reducer → duplicates dropped.
    merged = append_dedupe_playbook_hits(list(hits), hits)
    assert len(merged) == 3  # whole-item identity dedupe drops the second identical batch


# ---------------------------------------------------------------------------
# AC5 — DETERMINISM (AD-12): no wall-clock/random/hash; NO timestamp in hits
# ---------------------------------------------------------------------------


def test_node_is_deterministic_same_state_same_hits() -> None:
    """AD-12: same state → identical hits (two fresh adapters with the same config)."""
    node_a = build_preplanning_playbook_retriever(_ProbeAdapter(mode="hits", hits=_hits(3)))
    node_b = build_preplanning_playbook_retriever(_ProbeAdapter(mode="hits", hits=_hits(3)))
    state = _state()
    assert node_a(state) == node_b(state)


def test_query_is_deterministic_and_scoped_by_service() -> None:
    """AD-12: the query is a deterministic function of canonical_trigger + service."""
    a = _ProbeAdapter(mode="hits", hits=[])
    b = _ProbeAdapter(mode="hits", hits=[])
    build_preplanning_playbook_retriever(a)(
        _state(canonical_trigger="DependencyTimeout", service="checkout")
    )
    build_preplanning_playbook_retriever(b)(
        _state(canonical_trigger="DependencyTimeout", service="checkout")
    )
    assert a.last_query == b.last_query
    assert a.last_query == "DependencyTimeout service:checkout"


def test_query_without_service_is_just_canonical_trigger() -> None:
    """AD-12: no service in context → query is exactly the canonical_trigger."""
    adapter = _ProbeAdapter(mode="hits", hits=[])
    node = build_preplanning_playbook_retriever(adapter)
    state = create_initial_state()
    state["trigger"] = {"canonical_trigger": "HighErrorRate"}
    state["context"] = {}  # no service
    node(state)
    assert adapter.last_query == "HighErrorRate"


def test_node_source_has_no_wallclock_random_or_hash() -> None:
    """AD-12: node source has no wall-clock / random / hash primitives."""
    src = NODE_FILE.read_text(encoding="utf-8")
    for forbidden in ("datetime.now", "time.time", "time.monotonic", "random.", "uuid.", "hash("):
        assert forbidden not in src, f"node source contains non-deterministic token '{forbidden}'"


def test_playbook_hits_have_no_timestamp() -> None:
    """AD-12 / AC: NO timestamp field (retrieved_at/created_at/ts) in playbook_hits items."""
    node = build_preplanning_playbook_retriever(_ProbeAdapter(mode="hits", hits=_hits(3)))
    result = node(_state())
    # RUNTIME guarantee (the real contract): forwarded items carry no timestamp key.
    for item in _hits_of(result):
        assert isinstance(item, dict)
        for key in item:
            assert key not in ("retrieved_at", "created_at", "ts", "timestamp", "at"), (
                f"playbook_hits item has a forbidden timestamp field '{key}'"
            )
    # SOURCE guarantee (AST-exact, not docstring prose): the node constructs NO dict literal whose
    # key is a timestamp field name. Walks only ``ast.Dict`` keys — docstrings are ignored.
    tree = ast.parse(NODE_FILE.read_text(encoding="utf-8"))
    forbidden_keys = {"retrieved_at", "created_at", "ts", "timestamp", "at"}
    constructed_keys: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Dict):
            for k in n.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    constructed_keys.add(k.value)
    assert not (constructed_keys & forbidden_keys), (
        f"node constructs a dict with a forbidden timestamp key: {constructed_keys & forbidden_keys}"
    )


def test_playbook_hits_are_jsonsafe() -> None:
    """AD-9: forwarded playbook_hits json.dumps round-trip (JSON-safe)."""
    node = build_preplanning_playbook_retriever(_ProbeAdapter(mode="hits", hits=_hits(3)))
    result = node(_state())
    assert json.loads(json.dumps(result)) == result


# ---------------------------------------------------------------------------
# AC7 — one-way AD-1 (gate #2): graph→tools.port FORWARD edge; RAW passthrough
# ---------------------------------------------------------------------------


def test_node_imports_only_allowed_layers() -> None:
    """AD-1 one-way: node imports graph.state + tools.port (forward) + stdlib; no back-edge."""
    tree = ast.parse(NODE_FILE.read_text(encoding="utf-8"))
    forbidden = {"routers", "services", "adapters", "models"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = {n.name.split(".")[0] for n in node.names}
        elif isinstance(node, ast.ImportFrom):
            modules = {node.module.split(".")[0]} if node.module else set()
        else:
            continue
        assert not (modules & forbidden), f"node imports a forbidden layer: {modules & forbidden}"


def test_node_imports_tools_port_forward_edge() -> None:
    """AD-1: the graph→tools.port forward edge IS present (the first graph node to use the port)."""
    tree = ast.parse(NODE_FILE.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {n.name.split(".")[0] for n in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    assert "tools" in modules and "graph" in modules  # graph + tools.port (forward, legal)


def test_node_has_no_write_path_or_evidence() -> None:
    """AD-3 + 4.2 boundary: no hidden write path; no Evidence construction / models import."""
    src = NODE_FILE.read_text(encoding="utf-8")
    for forbidden in ("subprocess", "os.system", "os.exec", "requests.", "open(", "kubectl"):
        assert forbidden not in src, f"node source contains forbidden token '{forbidden}'"
    assert "Evidence(" not in src
    assert "from models" not in src and "import models" not in src


def test_node_does_not_route_through_executor_router() -> None:
    """AC6: the node does NOT import/depend on executor_router / the registry (that is 3.5).

    AST-exact (not docstring prose — the node legitimately DOCUMENTS that it does not use the
    router): the node imports nothing from ``tools.router`` / ``tools.registry`` and binds no name
    ``executor_router`` / ``ExecutorRouter`` / ``ReadOnlyRegistry``.
    """
    tree = ast.parse(NODE_FILE.read_text(encoding="utf-8"))
    forbidden_modules = {"tools.router", "tools.registry"}
    forbidden_names = {"executor_router", "ExecutorRouter", "ReadOnlyRegistry"}
    bound_names: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module in forbidden_modules:
            raise AssertionError(f"node imports forbidden module '{n.module}'")
        if isinstance(n, ast.ImportFrom):
            bound_names |= {a.asname or a.name for a in n.names}
        elif isinstance(n, ast.Import):
            bound_names |= {a.asname or a.name.split(".")[0] for a in n.names}
    assert not (bound_names & forbidden_names), (
        f"node binds a forbidden name: {bound_names & forbidden_names}"
    )


# ---------------------------------------------------------------------------
# top_k default + mechanism vs deferred number
# ---------------------------------------------------------------------------


def test_top_k_default_is_explicitly_deferred_poc() -> None:
    """K is an injected param; the default is explicitly marked DEFER benchmark (D3/SM-4)."""
    src = NODE_FILE.read_text(encoding="utf-8")
    assert "_DEFAULT_TOP_K" in src
    # The number is marked deferred, not presented as a tuned final.
    assert "DEFER" in src or "deferred" in src.lower()
    # top_k is keyword-only in the factory signature.
    import inspect

    sig = inspect.signature(build_preplanning_playbook_retriever)
    assert "top_k" in sig.parameters
    assert sig.parameters["top_k"].kind == inspect.Parameter.KEYWORD_ONLY


def test_top_k_passes_through_to_adapter() -> None:
    """The injected top_k reaches the adapter call verbatim."""
    adapter = _ProbeAdapter(mode="hits", hits=_hits(2))
    build_preplanning_playbook_retriever(adapter, top_k=9)(_state())
    assert adapter.last_top_k == 9
