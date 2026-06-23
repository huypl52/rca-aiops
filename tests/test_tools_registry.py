"""Story 2.1 — read-only tool registry + deny-set + CI #1 (AD-3 BLOCKER / FR-5).

Covers AC1-6 for the read-only tool layer:
  - AC1 — exactly the 10 spec §3.6 tools, names exact, NO deny-verb executor name.
  - AC2 — CI gate #1 HARD-FAILs on deny-set injection (no invented count: len == 10).
  - AC3 — tools only read/collect/summarize → RAW JSON-safe output (NOT Evidence).
  - AC4 — defense-in-depth: register() rejects a deny-verb name (ReadOnlyViolation).
  - AC5 — adapter PORT seam clean (stub default; tools depend on Protocol only).
  - AC6 — gates green (gate#1 PASSes on real tools/; one-way gate#2 KEPT).

AD-9 (JSON-safe), AD-12 (deterministic stub — no wall-clock/random/IO), AD-3 (read-only boundary).
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GATE_SCRIPT = REPO_ROOT / "ci" / "gate1_readonly_registry.py"

# The EXACT spec §3.6 set (7 row / 10 function). Count by the spec TABLE (L2).
EXPECTED_TOOLS: list[str] = [
    "collect_prometheus_metric_evidence",
    "query_prometheus_raw",
    "query_prometheus_histogram_percentile",
    "query_loki_service_logs",
    "k8s_get_pods",
    "k8s_describe_pod",
    "k8s_logs",
    "k8s_get_events",
    "search_playbook",
    "topology_executor",
]

TIME_WINDOW: dict[str, str | None] = {"start": "2026-06-24T00:00:00Z", "end": None}


# ---------------------------------------------------------------------------
# AC1 / AC2 — exactly 10 tools, exact names, no invented / no missing
# ---------------------------------------------------------------------------


def test_registry_holds_exactly_ten_tools() -> None:
    """AC2 (no invented count): the registry must hold EXACTLY 10 tools."""
    import tools

    assert len(tools.registry) == 10


def test_registry_names_match_spec_exactly() -> None:
    """AC1: registry names must equal the spec §3.6 table exactly (no invented/missing)."""
    import tools

    names = set(tools.registry.names())
    assert names == set(EXPECTED_TOOLS)


@pytest.mark.parametrize("name", EXPECTED_TOOLS)
def test_each_spec_tool_is_registered_and_callable(name: str) -> None:
    """AC1: each of the 10 spec tools is registered + callable through the stub adapter."""
    import tools

    assert name in tools.registry
    executor = tools.registry.lookup(name)
    assert callable(executor)


def test_no_executor_name_is_a_deny_verb() -> None:
    """AC1: no registered tool name is a deny-verb (read-only boundary, AD-3)."""
    import tools
    from ci.denyset import WRITE_VERBS

    for name in tools.registry.names():
        assert name not in WRITE_VERBS, f"tool name '{name}' is a deny-verb (AD-3 violation)"


def test_topology_executor_is_not_a_false_positive() -> None:
    """Constraint #4: 'topology_executor' is NOT a gate#1 false positive (exact-match, not
    substring). Confirms the AST gate semantics so nobody 'fixes' it by renaming."""
    from ci.denyset import WRITE_VERBS

    assert "topology_executor" not in WRITE_VERBS  # exact-match gate → safe
    # Exact-match (not substring): "exec" is a verb, but "topology_executor" is a different name.
    assert "exec" in WRITE_VERBS


# ---------------------------------------------------------------------------
# AC4 — defense-in-depth: register() rejects deny-verb names at runtime
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("verb", ["exec", "patch", "delete", "scale", "restart", "remediate"])
def test_register_rejects_deny_verb_name(verb: str) -> None:
    """AC4 (defense-in-depth): register() refuses a deny-verb name → ReadOnlyViolation.

    This is the RUNTIME layer on top of CI gate #1's STATIC AST scan (catches dynamic
    registration the AST can't see).
    """
    from tools import ReadOnlyRegistry, ReadOnlyViolation

    reg = ReadOnlyRegistry()
    with pytest.raises(ReadOnlyViolation, match="read-only boundary"):
        reg.register(verb, lambda **_: {})


def test_register_rejects_write_catchall_verb() -> None:
    """AC4: the catch-all 'write' verb is also rejected."""
    from tools import ReadOnlyRegistry, ReadOnlyViolation

    reg = ReadOnlyRegistry()
    with pytest.raises(ReadOnlyViolation):
        reg.register("write", lambda **_: {})


def test_register_rejects_duplicate_name() -> None:
    """Registry is a 1:1 name→executor map."""
    from tools import ReadOnlyRegistry

    reg = ReadOnlyRegistry()
    reg.register("query_prometheus_raw", lambda **_: {})
    with pytest.raises(ValueError, match="already registered"):
        reg.register("query_prometheus_raw", lambda **_: {})


def test_lookup_unknown_raises() -> None:
    from tools import ReadOnlyRegistry

    reg = ReadOnlyRegistry()
    with pytest.raises(KeyError):
        reg.lookup("does_not_exist")


# ---------------------------------------------------------------------------
# AC3 — tools return RAW JSON-safe output (NOT Evidence); read-only execution
# ---------------------------------------------------------------------------


def _call_all_ten() -> list[tuple[str, dict[str, object]]]:
    """Invoke all 10 executors through the stub adapter; return (name, raw_output) pairs."""
    from tools import StubReadOnlyAdapter, registry

    adapter = StubReadOnlyAdapter()
    tw = TIME_WINDOW
    calls: list[tuple[str, dict[str, object]]] = []

    def go(name: str, **kwargs: object) -> None:
        executor = registry.lookup(name)
        result = executor(adapter, **kwargs)
        assert isinstance(result, dict), f"{name} must return a dict (RAW output)"
        calls.append((name, dict(result)))

    go(
        "collect_prometheus_metric_evidence",
        service="checkout",
        metric="http_requests_total",
        evidence_type="error_rate",
        time_window=tw,
    )
    go("query_prometheus_raw", query="up{service='checkout'}", time_window=tw)
    go(
        "query_prometheus_histogram_percentile",
        metric="http_request_duration_seconds",
        percentile=0.95,
        time_window=tw,
    )
    go("query_loki_service_logs", service="checkout", time_window=tw)
    go("k8s_get_pods", namespace="demo")
    go("k8s_describe_pod", namespace="demo", pod="checkout-0")
    go("k8s_logs", namespace="demo", pod="checkout-0", previous=False)
    go("k8s_get_events", namespace="demo")
    go("search_playbook", query="DependencyTimeout", top_k=3)
    go("topology_executor", service="checkout")
    return calls


def test_all_ten_tools_return_raw_jsonsafe_output() -> None:
    """AC3 / AD-9: every tool returns RAW output that json.dumps round-trips."""
    for name, raw in _call_all_ten():
        encoded = json.dumps(raw)
        decoded = json.loads(encoded)
        assert decoded == raw, f"{name} output is not JSON-safe round-trip (AD-9)"


def test_tools_return_dict_not_evidence() -> None:
    """AC3 / Evidence boundary (= 4.2): tools return plain dicts, NOT Evidence objects."""
    from models.evidence import Evidence
    from tools import StubReadOnlyAdapter, registry

    adapter = StubReadOnlyAdapter()
    result = registry.lookup("query_prometheus_raw")(adapter, query="up", time_window=TIME_WINDOW)
    assert isinstance(result, dict)
    assert not isinstance(result, Evidence)


def test_tools_never_construct_evidence() -> None:
    """AC3: executor source must not import or construct Evidence (boundary held)."""
    import tools.executors as ex

    src = Path(ex.__file__).read_text(encoding="utf-8")
    assert "Evidence(" not in src, "executors must NOT construct Evidence (4.2 boundary)"
    assert "from models" not in src and "import models" not in src, (
        "executors must NOT import models (Evidence = 4.2; AD-1 one-way)"
    )


def test_executors_only_read_through_port() -> None:
    """AC3: executors call ONLY the ReadOnlyAdapterPort read methods (no direct I/O)."""
    import tools.executors as ex

    src = Path(ex.__file__).read_text(encoding="utf-8")
    # No forbidden runtime write primitives in the executor source (defense-in-depth intent).
    for forbidden in ("subprocess", "os.system", "os.exec", "requests.", "open(", "kubectl"):
        assert forbidden not in src, f"executor source contains forbidden token '{forbidden}'"


# ---------------------------------------------------------------------------
# AC5 — adapter PORT seam clean (stub default; tools depend on Protocol only)
# ---------------------------------------------------------------------------


def test_stub_satisfies_port_protocol() -> None:
    """AC5: StubReadOnlyAdapter satisfies ReadOnlyAdapterPort (runtime_checkable)."""
    from tools import ReadOnlyAdapterPort, StubReadOnlyAdapter

    assert isinstance(StubReadOnlyAdapter(), ReadOnlyAdapterPort)


def test_stub_is_deterministic() -> None:
    """AD-12: same args → identical output (no wall-clock/random/IO)."""
    from tools import StubReadOnlyAdapter

    a = StubReadOnlyAdapter()
    out1 = a.query_promql(query="up", time_window=TIME_WINDOW)
    out2 = StubReadOnlyAdapter().query_promql(query="up", time_window=TIME_WINDOW)
    assert out1 == out2


def test_tools_do_not_import_forbidden_layers() -> None:
    """AD-1 one-way: tools/ source must NOT import graph/services/routers/adapters."""
    for mod in ("port.py", "executors.py", "registry.py", "__init__.py"):
        path = REPO_ROOT / "tools" / mod
        src = path.read_text(encoding="utf-8")
        # allow `tools.` (same-layer) and `ci.denyset` (not a contracted layer); forbid back-edges.
        for forbidden in (
            "import graph",
            "from graph",
            "import services",
            "from services",
            "import routers",
            "from routers",
            "import adapters",
            "from adapters",
        ):
            assert forbidden not in src, f"tools/{mod} imports forbidden layer: {forbidden}"


# ---------------------------------------------------------------------------
# AC6 — CI gate #1 PASSes on the real (now non-empty) tools/
# ---------------------------------------------------------------------------


def test_gate1_passes_on_real_tools() -> None:
    """AC6: gate #1 exit 0 — scans the real non-empty tools/ + adapters/, zero violations."""
    result = subprocess.run(
        [sys.executable, str(GATE_SCRIPT), "--root", str(REPO_ROOT)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, (
        f"gate #1 should PASS on real tools/:\n{result.stdout}\n{result.stderr}"
    )
    assert "PASS" in result.stdout


def test_tools_source_is_non_empty_so_gate_is_exercised() -> None:
    """Sanity: the tools/ the gate scans is genuinely non-empty (so a PASS is meaningful)."""
    py_files = sorted((REPO_ROOT / "tools").glob("*.py"))
    assert len(py_files) >= 4  # __init__, port, executors, registry
    # The 10 executor function names must be present as AST defs in tools/.
    all_defs: set[str] = set()
    for pf in py_files:
        tree = ast.parse(pf.read_text(encoding="utf-8"), filename=str(pf))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                all_defs.add(node.name)
    for name in EXPECTED_TOOLS:
        assert name in all_defs, f"executor '{name}' not defined as a function in tools/"


# ---------------------------------------------------------------------------
# Regression — deny-set vocabulary stays locked at 8 (guards AC2 vocabulary)
# ---------------------------------------------------------------------------


def test_write_verbs_still_eight() -> None:
    """Regression: WRITE_VERBS must stay exactly 8 (delegates to the gate#1 self-test's guard)."""
    from ci.denyset import WRITE_VERBS

    assert len(WRITE_VERBS) == 8
