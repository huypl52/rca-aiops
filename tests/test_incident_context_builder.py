"""Story 1.3 — incident_context_builder node (§3.5 entry node): context seed.

Covers the ACs:
  - AC1 — context spine-exact: service / namespace / time_window{start,end} /
    labels / topology_seed (§3.5 / AD-9 shape table).
  - AC2 — namespace defaults to "demo" when missing/empty-string (§3.4).
  - AC3 — ends_at missing (firing) → time_window.end = None, DETERMINISTIC,
    NO now-marker (AD-12).
  - AC4 — PARTIAL return {"context": {...}}; merge via REUSED upsert_context
    (0-3, NOT redefined); input state unchanged (pure).
  - AC5 — pure/deterministic (AD-12): N calls → identical; no wall-clock/random/
    side-effect/I/O (AST scan of node source).
  - AC6 — JSON-safe context (AD-9): json.dumps no raise + round-trip deep-equal.
  - AC7 — one-way AD-1 / gate #2: node in graph/, NO routers/services import.
"""

from __future__ import annotations

import ast
import copy
import json
from pathlib import Path

import pytest

from graph.nodes.incident_context_builder import (
    build_incident_context,
    incident_context_builder,
)
from graph.state import InvestigationState, JsonValue, create_initial_state, upsert_context
from models import IncidentTrigger, Severity, SignalType, TriggerSource

NODE_FILE = Path(__file__).resolve().parents[1] / "graph" / "nodes" / "incident_context_builder.py"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _trigger(
    *,
    service: JsonValue = "payment",
    namespace: JsonValue | None = "demo",
    started_at: JsonValue = "2026-06-24T10:00:00Z",
    ends_at: JsonValue | None = "2026-06-24T10:05:00Z",
    labels: JsonValue | None = None,
    affected_services: JsonValue | None = None,
) -> dict[str, JsonValue]:
    """Build a plain-dict trigger (shape ⊆ IncidentTrigger.model_dump(), AD-9)."""
    if labels is None:
        labels = {"severity": "critical", "scenario": "dep-timeout"}
    if affected_services is None:
        affected_services = ["payment", "order", "inventory"]
    trigger: dict[str, JsonValue] = {
        "service": service,
        "started_at": started_at,
        "ends_at": ends_at,
        "labels": labels,
        "affected_services": affected_services,
    }
    if namespace is not None:
        trigger["namespace"] = namespace
    return trigger


def _state(trigger: dict[str, JsonValue]) -> InvestigationState:
    return create_initial_state(trigger=trigger)


def _context_of(result: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Narrow result["context"] (JsonValue) to a dict for assertion (mypy-safe)."""
    context = result["context"]
    assert isinstance(context, dict)
    return context


def _time_window(context: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Narrow context["time_window"] to a dict for assertion (mypy-safe)."""
    tw = context["time_window"]
    assert isinstance(tw, dict)
    return tw


# ---------------------------------------------------------------------------
# AC1 — context spine-exact (§3.5 / AD-9 shape table)
# ---------------------------------------------------------------------------


def test_ac1_context_spine_exact() -> None:
    """Full happy path: 6 context fields spine-exact from trigger."""
    trigger = _trigger()
    result = incident_context_builder(_state(trigger))

    # AD-4: PARTIAL return — exactly ONE top-level key "context".
    assert list(result.keys()) == ["context"], "node must return partial {context: ...} (AD-4)"
    context = _context_of(result)

    assert context["service"] == "payment"
    assert context["namespace"] == "demo"  # pass-through when present
    assert context["time_window"] == {
        "start": "2026-06-24T10:00:00Z",
        "end": "2026-06-24T10:05:00Z",
    }
    assert context["labels"] == {"severity": "critical", "scenario": "dep-timeout"}
    # topology_seed: non-inventing — just the affected_services list, no edges.
    assert context["topology_seed"] == {"services": ["payment", "order", "inventory"]}


def test_ac1_trigger_from_port_model_dump() -> None:
    """Trigger shape ⊆ IncidentTrigger.model_dump() (port boundary, AD-9) works."""
    trigger: dict[str, JsonValue] = IncidentTrigger(
        trigger_id="t-1",
        source=TriggerSource.PROMETHEUS_ALERTMANAGER,
        signal_type=SignalType.METRIC,
        canonical_trigger="DependencyTimeout",
        alert_name="DependencyTimeout",
        severity=Severity.CRITICAL,
        title="Payment dep timeout",
        description="payment -> order timing out",
        service="payment",
        affected_services=["payment", "order"],
        symptom="timeout",
        namespace="demo",
        started_at="2026-06-24T10:00:00Z",
        ends_at="2026-06-24T10:05:00Z",
        labels={"service": "payment"},
        annotations={"summary": "timeout"},
        raw_payload={"foo": "bar"},
    ).model_dump()

    context = build_incident_context(trigger)
    assert context["service"] == "payment"
    assert context["namespace"] == "demo"
    assert _time_window(context)["end"] == "2026-06-24T10:05:00Z"
    assert context["topology_seed"] == {"services": ["payment", "order"]}


# ---------------------------------------------------------------------------
# AC2 — namespace default "demo" when missing/empty-string (§3.4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("missing", ["absent", "empty"])
def test_ac2_namespace_defaults_to_demo(missing: str) -> None:
    """namespace absent or empty-string → "demo" (§3.4 default; graceful, no crash)."""
    trigger = _trigger(namespace="" if missing == "empty" else None)
    context = build_incident_context(trigger)
    assert context["namespace"] == "demo"


def test_ac2_namespace_passthrough_when_present() -> None:
    """namespace present → pass-through (no coercion)."""
    trigger = _trigger(namespace="prod")
    context = build_incident_context(trigger)
    assert context["namespace"] == "prod"


@pytest.mark.parametrize("falsy_nonstring", [0, False, []])
def test_ac2_namespace_does_not_coerce_falsy_nonstring_to_demo(
    falsy_nonstring: JsonValue,
) -> None:
    """AC2 no-coercion clause (leader Constrain #4): a present falsy NON-STRING
    value (0 / False / []) must NOT be silently turned into "demo".

    Only ``absent`` (None) or empty-string "" defaults to "demo"; the node must
    NOT use a lazy ``or "demo"`` that swallows falsy values. In practice the port
    guarantees namespace is a str, but the defensive guard must still be correct.
    """
    trigger = _trigger(namespace=falsy_nonstring)
    context = build_incident_context(trigger)
    assert context["namespace"] != "demo", (
        f"must not coerce falsy non-string {falsy_nonstring!r} into 'demo'"
    )
    assert context["namespace"] == falsy_nonstring


# ---------------------------------------------------------------------------
# AC3 — ends_at missing (firing) → time_window.end = None, DETERMINISTIC (AD-12)
# ---------------------------------------------------------------------------


def test_ac3_ends_at_none_value_end_is_none() -> None:
    """ends_at = None (firing) → time_window.end = None (deterministic lock)."""
    trigger = _trigger(ends_at=None)
    context = build_incident_context(trigger)
    tw = _time_window(context)
    assert tw["end"] is None
    assert tw["start"] == "2026-06-24T10:00:00Z"


def test_ac3_ends_at_absent_key_end_is_none() -> None:
    """ends_at key entirely absent → time_window.end = None (graceful, no KeyError)."""
    trigger = _trigger()
    trigger.pop("ends_at")
    context = build_incident_context(trigger)
    assert _time_window(context)["end"] is None


def test_ac3_no_now_marker_deterministic() -> None:
    """Firing trigger → end=None every call (NO now-marker drift across calls)."""
    trigger = _trigger(ends_at=None)
    ends = [_time_window(build_incident_context(trigger))["end"] for _ in range(5)]
    assert all(e is None for e in ends)


# ---------------------------------------------------------------------------
# AC4 — PARTIAL return via REUSED upsert_context (AD-4); pure (input unchanged)
# ---------------------------------------------------------------------------


def test_ac4_partial_return_single_key() -> None:
    """Node returns exactly {"context": {...}} — NOT the 13-key state."""
    result = incident_context_builder(_state(_trigger()))
    assert set(result.keys()) == {"context"}


def test_ac4_merge_via_reused_reducer() -> None:
    """Merge into state.context via REUSED upsert_context (0-3), {**left, **right}."""
    state = create_initial_state(trigger=_trigger())
    partial = incident_context_builder(state)
    # Reducer imported from graph.state (REUSE — not redefined locally).
    partial_context = _context_of(partial)
    merged_context = upsert_context(state["context"], partial_context)
    assert merged_context == partial["context"]  # left was {} (factory seed)
    assert set(merged_context.keys()) == {
        "service",
        "namespace",
        "time_window",
        "labels",
        "topology_seed",
    }


def test_ac4_does_not_mutate_input() -> None:
    """Pure: input state/trigger dict unchanged after the call."""
    trigger = _trigger()
    trigger_before = copy.deepcopy(trigger)
    state = _state(trigger)
    state_before = copy.deepcopy(state)

    incident_context_builder(state)

    assert trigger == trigger_before, "node must NOT mutate the input trigger"
    assert state == state_before, "node must NOT mutate the input state"


def test_ac4_merge_overwrites_left_and_keeps_left_only_keys() -> None:
    """upsert_context = {**left, **right} with a NON-empty left: right WINS on
    shared keys (overwrite), left-only keys are PRESERVED. Proves the reducer is
    a true merge (not overwrite-whole, not whole-state replace)."""
    # Simulate a prior partial that already wrote some context keys.
    left: dict[str, JsonValue] = {
        "service": "OLD-service",
        "namespace": "OLD-ns",
        "plan": ["h1", "h2"],  # a key only `left` has — must survive the merge
    }
    partial = incident_context_builder(_state(_trigger(namespace="prod")))
    merged = upsert_context(left, _context_of(partial))

    # Right (this node) wins on shared keys.
    assert merged["service"] == "payment"
    assert merged["namespace"] == "prod"
    # Left-only key is preserved — the reducer merges, it does not replace whole.
    assert merged["plan"] == ["h1", "h2"]
    assert set(merged.keys()) >= {
        "service",
        "namespace",
        "time_window",
        "labels",
        "topology_seed",
        "plan",
    }


# ---------------------------------------------------------------------------
# AC5 — pure/deterministic (AD-12): same input → same output; static purity scan
# ---------------------------------------------------------------------------


def test_ac5_deterministic_identical_output() -> None:
    """N calls with the same input → bit-identical output (AD-12 determinism)."""
    state = _state(_trigger())
    out1 = incident_context_builder(state)
    out2 = incident_context_builder(state)
    out3 = incident_context_builder(state)
    assert out1 == out2 == out3


# Modules whose presence would break AD-12 purity (wall-clock / randomness /
# env / fs / network). The node must not import any of them.
_PURITY_FORBIDDEN_MODULES = {"datetime", "time", "random", "secrets", "os", "sys", "socket"}

# Attribute / name tokens that, if CALLED or REFERENCED, break purity. AST-only
# (never raw-source) so the module docstring — which documents the forbidden
# tokens — is not a false positive.
_PURITY_FORBIDDEN_ATTRS = {
    # wall-clock
    "now",
    "utcnow",
    "time",
    "monotonic",
    "localtime",
    "gmtime",
    "perf_counter",
    # randomness
    "random",
    "choice",
    "randint",
    "randrange",
    "uniform",
    "uuid4",
    "uuid1",
    "urandom",
    "token_hex",
    # I/O / side-effect
    "open",
    "input",
    # dynamic dispatch / code-gen escape hatches that defeat the static scan
    # (a pure node has no reason to ever touch these).
    "eval",
    "exec",
    "compile",
    "__import__",
}


def test_ac5_source_has_no_wallclock_random_io() -> None:
    """AST scan: node source has NO wall-clock/random/I/O import or call (AD-12 pure).

    AST-only (not raw text) so the docstring — which legitimately documents the
    forbidden tokens — does not trip the scan.
    """
    tree = ast.parse(NODE_FILE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        # No forbidden module imports (the only route to wall-clock/random/fs).
        if isinstance(node, ast.Import):
            roots = {alias.name.split(".")[0] for alias in node.names}
            assert not (roots & _PURITY_FORBIDDEN_MODULES), (
                f"forbidden import for pure node (AD-12): {roots & _PURITY_FORBIDDEN_MODULES}"
            )
        if isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".")[0]
            assert root not in _PURITY_FORBIDDEN_MODULES, (
                f"forbidden import for pure node (AD-12): {node.module}"
            )
        # No forbidden attribute access (datetime.now / time.time / ... / open).
        if isinstance(node, ast.Attribute):
            assert node.attr not in _PURITY_FORBIDDEN_ATTRS, (
                f"forbidden attribute for pure node (AD-12): {node.attr}"
            )
        # No forbidden bare-name call (open / input).
        if isinstance(node, ast.Name):
            assert node.id not in _PURITY_FORBIDDEN_ATTRS, (
                f"forbidden name for pure node (AD-12): {node.id}"
            )


# ---------------------------------------------------------------------------
# AC6 — JSON-safe context (AD-9): json.dumps no raise + round-trip deep-equal
# ---------------------------------------------------------------------------


def test_ac6_context_is_json_safe() -> None:
    """Every context value is JSON-safe (AD-9); time_window = ISO strings, not datetime."""
    context = build_incident_context(_trigger())
    serialized = json.dumps(context)  # stdlib axis (gate #3) — TypeError if non-JSON-safe
    assert json.loads(serialized) == context  # round-trip deep-equal
    # Sanity: time_window holds plain strings/None, never datetime objects.
    tw = _time_window(context)
    assert tw["start"] is None or isinstance(tw["start"], str)
    assert tw["end"] is None or isinstance(tw["end"], str)


def test_ac6_context_json_safe_when_firing() -> None:
    """Firing trigger (end=None) context still JSON-safe (None is JSON-safe)."""
    context = build_incident_context(_trigger(ends_at=None))
    assert json.loads(json.dumps(context)) == context


# ---------------------------------------------------------------------------
# AC7 — one-way AD-1 / gate #2: node in graph/, NO routers/services import
# ---------------------------------------------------------------------------


def test_ac7_no_back_edge_imports() -> None:
    """Node imports graph.state + stdlib only — NO routers/services back-edge (AD-1)."""
    tree = ast.parse(NODE_FILE.read_text(encoding="utf-8"))
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])
    # No back-edge to routers/services (gate #2 HARD-FAIL boundary).
    assert "routers" not in imported_roots, "graph node must not import routers (AD-1)"
    assert "services" not in imported_roots, "graph node must not import services (AD-1)"
    # Must reuse graph.state (same layer) — confirms the reducer is REUSED.
    assert "graph" in imported_roots, "node must import graph.state (same layer)"


def test_ac7_reducer_reused_not_redefined() -> None:
    """upsert_context is imported from graph.state (0-3), NOT redefined here."""
    # The node module must not define its own upsert_context.
    tree = ast.parse(NODE_FILE.read_text(encoding="utf-8"))
    defined = {
        n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    assert "upsert_context" not in defined, (
        "must REUSE upsert_context from graph.state, not redefine"
    )


# ---------------------------------------------------------------------------
# Edge cases — defensive branches must be exercised (graceful, never crash).
# ---------------------------------------------------------------------------


def test_empty_trigger_dict_is_graceful() -> None:
    """A near-empty trigger `{}` must NOT crash — every field degrades safely.

    Proves the node never KeyErrors / TypeErrors on a minimal trigger: namespace
    → "demo" default, time_window bounds → None, labels → {}, topology_seed → [].
    """
    context = build_incident_context({})
    assert context["namespace"] == "demo"
    assert context["service"] is None
    tw = _time_window(context)
    assert tw == {"start": None, "end": None}
    assert context["labels"] == {}
    assert context["topology_seed"] == {"services": []}
    # Still JSON-safe end-to-end.
    assert json.loads(json.dumps(context)) == context


def test_non_dict_labels_defaults_to_empty() -> None:
    """labels that is not a dict (e.g. a stray list/str/None) → {} (graceful)."""
    bad_labels: tuple[JsonValue, ...] = (None, "critical", ["severity", "critical"], 42)
    for bad in bad_labels:
        # Spread the base trigger then OVERRIDE labels (bypasses _trigger's
        # None-default-substitution so `bad` — including None — passes literally).
        trigger: dict[str, JsonValue] = {**_trigger(), "labels": bad}
        context = build_incident_context(trigger)
        assert context["labels"] == {}


def test_affected_services_filters_non_string_items() -> None:
    """topology_seed.services keeps only str items; non-str items are dropped
    (keeps the seed JSON-safe + non-inventing; never crashes on junk entries)."""
    trigger: dict[str, JsonValue] = {
        **_trigger(),
        "affected_services": ["payment", 0, None, "order", [], "inventory"],
    }
    context = build_incident_context(trigger)
    assert context["topology_seed"] == {"services": ["payment", "order", "inventory"]}


def test_non_list_affected_services_defaults_to_empty() -> None:
    """affected_services that is not a list (str/None/dict) → [] (graceful)."""
    bad_services: tuple[JsonValue, ...] = (None, "payment", {"service": "payment"})
    for bad in bad_services:
        trigger = {**_trigger(), "affected_services": bad}
        context = build_incident_context(trigger)
        assert context["topology_seed"] == {"services": []}
