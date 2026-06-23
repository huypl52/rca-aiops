"""Story 2.2 — read-only adapter clients (prometheus, loki, k8s, qdrant, topology).

Covers AC1-6 for the adapter layer:
  - AC1 — the 8 ReadOnlyAdapterPort methods are covered across the 5 source adapters; the composite a
          tool receives satisfies ReadOnlyAdapterPort (runtime_checkable isinstance). tools/ is
          UNCHANGED — the 10 executors run unchanged against the composite (AC5 seam from 2-1 held).
  - AC2 — CI gate #1 PASSes on the REAL non-empty adapters/ (exit 0); no deny-verb.
  - AC3 — time_window reaches the transport + is echoed (prom/loki); a source failure (transport
          error OR backend error response) → structured RawOutput error envelope, NEVER raises.
  - AC4 — AD-1 one-way (gate#2 KEPT): adapters/ imports only tools (forward) + stdlib; no
          graph/services/routers.
  - AC5 — RAW dict, NOT Evidence (boundary = 4.2); no models import in adapters/.
  - AC6 — offline deterministic fake transport (AD-12); all 7 gates green.

AD-3 (read-only boundary, no hidden write path), AD-9 (JSON-safe), AD-12 (determinism).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from adapters.readonly import CompositeReadOnlyAdapter

REPO_ROOT = Path(__file__).resolve().parents[1]
GATE_SCRIPT = REPO_ROOT / "ci" / "gate1_readonly_registry.py"

TIME_WINDOW: dict[str, str | None] = {"start": "2026-06-24T00:00:00Z", "end": None}

# The 8 ReadOnlyAdapterPort methods, mapped to the call each composite method routes to.
PORT_METHOD_ARGS: list[tuple[str, dict[str, object]]] = [
    ("query_promql", {"query": "up{service='checkout'}", "time_window": TIME_WINDOW}),
    (
        "query_loki",
        {"service": "checkout", "time_window": TIME_WINDOW, "correlation_id": "abc-123"},
    ),
    ("k8s_get", {"namespace": "demo", "label_selector": "app=checkout"}),
    ("k8s_describe", {"namespace": "demo", "pod": "checkout-0"}),
    ("k8s_logs", {"namespace": "demo", "pod": "checkout-0", "previous": False}),
    ("k8s_get_events", {"namespace": "demo", "field_selector": "type=Warning"}),
    ("search_playbook", {"query": "DependencyTimeout", "top_k": 3}),
    ("topology_read", {"service": "checkout"}),
]


def _composite(
    *,
    fail_source: str | None = None,
    backend_error_source: str | None = None,
) -> CompositeReadOnlyAdapter:
    from adapters.readonly import CompositeReadOnlyAdapter
    from adapters.transport import FakeReadOnlyTransport

    return CompositeReadOnlyAdapter(
        FakeReadOnlyTransport(fail_source=fail_source, backend_error_source=backend_error_source)
    )


# ---------------------------------------------------------------------------
# AC1 — 8 methods covered across 5 sources; composite satisfies the PORT
# ---------------------------------------------------------------------------


def test_composite_satisfies_port_protocol() -> None:
    """AC1: CompositeReadOnlyAdapter satisfies ReadOnlyAdapterPort (runtime_checkable)."""
    from tools.port import ReadOnlyAdapterPort

    assert isinstance(_composite(), ReadOnlyAdapterPort)


def test_each_source_adapter_constructed_from_one_transport() -> None:
    """AC1: the composite wires the 5 source adapters over a single injectable transport."""
    from adapters.readonly import CompositeReadOnlyAdapter
    from adapters.transport import FakeReadOnlyTransport

    transport = FakeReadOnlyTransport()
    composite = CompositeReadOnlyAdapter(transport)
    # Each delegate shares the injected transport (the I/O seam).
    for delegate in (
        composite._prometheus,
        composite._loki,
        composite._k8s,
        composite._qdrant,
        composite._topology,
    ):
        assert delegate._transport is transport


@pytest.mark.parametrize("method, kwargs", PORT_METHOD_ARGS)
def test_each_port_method_returns_raw_jsonsafe_dict(method: str, kwargs: dict[str, object]) -> None:
    """AC1/AD-9: each of the 8 port methods returns a RAW JSON-safe dict (round-trips json.dumps)."""
    composite = _composite()
    result = getattr(composite, method)(**kwargs)
    assert isinstance(result, dict), f"{method} must return a dict (RAW output)"
    encoded = json.dumps(result)
    assert json.loads(encoded) == result, f"{method} output is not JSON-safe round-trip (AD-9)"


def test_prometheus_normalizes_real_backend_shape() -> None:
    """AC1: prometheus adapter normalizes the real Prometheus HTTP API shape into RawOutput."""
    result = _composite().query_promql(query="up", time_window=TIME_WINDOW)
    assert result["source_type"] == "prometheus"
    assert result["result_type"] == "vector"
    assert isinstance(result["result"], list) and result["result"]
    # stub-aligned fields present
    assert result["query"] == "up"
    assert result["time_window"] == {"start": TIME_WINDOW["start"], "end": None}


def test_k8s_get_normalizes_pod_list() -> None:
    """AC1: k8s_get normalizes the real PodList shape into the stub-aligned pod summary."""
    result = _composite().k8s_get(namespace="demo", label_selector=None)
    assert result["source_type"] == "kubernetes"
    pods = result["pods"]
    assert isinstance(pods, list) and pods
    pod = pods[0]
    assert isinstance(pod, dict)
    assert pod["name"] == "demo-pod-0"
    assert pod["phase"] == "Running"
    assert pod["ready"] is True
    assert pod["restart_count"] == 0


def test_k8s_describe_normalizes_pod() -> None:
    """AC1: k8s_describe normalizes the real Pod object (termination_reason defaults None)."""
    result = _composite().k8s_describe(namespace="demo", pod="checkout-0")
    assert result["source_type"] == "kubernetes"
    describe = result["describe"]
    assert isinstance(describe, dict)
    assert describe["phase"] == "Running"
    assert describe["termination_reason"] is None
    assert "container_state" in describe


def test_qdrant_normalizes_search_hits() -> None:
    """AC1: search_playbook normalizes the real Qdrant result hits (id/score/title)."""
    result = _composite().search_playbook(query="DependencyTimeout", top_k=3)
    assert result["source_type"] == "playbook"
    hits = result["hits"]
    assert isinstance(hits, list) and len(hits) == 3
    first = hits[0]
    assert isinstance(first, dict)
    assert first["title"] == "playbook 0 for DependencyTimeout"
    assert first["score"] == 1.0


def test_ac5_seam_ten_executors_run_unchanged_against_composite() -> None:
    """AC5 (seam from 2-1 held): the 10 §3.6 executors run UNCHANGED against the real composite.

    The tools layer depends only on ReadOnlyAdapterPort; plugging CompositeReadOnlyAdapter must work
    with zero tools/ changes — proves the seam.
    """
    from tools import registry

    composite = _composite()
    calls: list[tuple[str, dict[str, object]]] = [
        (
            "collect_prometheus_metric_evidence",
            {
                "service": "checkout",
                "metric": "http_requests_total",
                "evidence_type": "error_rate",
                "time_window": TIME_WINDOW,
            },
        ),
        ("query_prometheus_raw", {"query": "up", "time_window": TIME_WINDOW}),
        (
            "query_prometheus_histogram_percentile",
            {
                "metric": "http_request_duration_seconds",
                "percentile": 0.95,
                "time_window": TIME_WINDOW,
            },
        ),
        ("query_loki_service_logs", {"service": "checkout", "time_window": TIME_WINDOW}),
        ("k8s_get_pods", {"namespace": "demo"}),
        ("k8s_describe_pod", {"namespace": "demo", "pod": "checkout-0"}),
        ("k8s_logs", {"namespace": "demo", "pod": "checkout-0", "previous": False}),
        ("k8s_get_events", {"namespace": "demo"}),
        ("search_playbook", {"query": "DependencyTimeout", "top_k": 3}),
        ("topology_executor", {"service": "checkout"}),
    ]
    for name, kwargs in calls:
        result = registry.lookup(name)(composite, **kwargs)
        assert isinstance(result, dict), f"executor {name} must return a dict against the composite"
        # every executor output is JSON-safe against the REAL adapter too (AD-9)
        assert json.loads(json.dumps(result)) == result


# ---------------------------------------------------------------------------
# AC3 — time_window respected; source failure → error envelope (no crash)
# ---------------------------------------------------------------------------


def test_time_window_reaches_transport_and_is_echoed_prometheus() -> None:
    """AC3: prometheus forwards time_window to the transport (timestamp_range) + echoes it."""
    from adapters.transport import FakeReadOnlyTransport

    fake = FakeReadOnlyTransport()
    from adapters.readonly import PrometheusAdapter

    PrometheusAdapter(fake).query_promql(query="up", time_window=TIME_WINDOW)
    # the seam recorded the bounded time window it received
    assert fake.calls[0][0] == "prometheus"
    assert fake.calls[0][1]["time_window"] == {"start": TIME_WINDOW["start"], "end": None}


def test_time_window_reaches_transport_loki() -> None:
    """AC3: loki forwards time_window + correlation_id to the transport + echoes it."""
    from adapters.readonly import LokiAdapter
    from adapters.transport import FakeReadOnlyTransport

    fake = FakeReadOnlyTransport()
    LokiAdapter(fake).query_loki(service="checkout", time_window=TIME_WINDOW, correlation_id="abc")
    assert fake.calls[0][0] == "loki"
    assert fake.calls[0][1]["time_window"] == {"start": TIME_WINDOW["start"], "end": None}
    assert fake.calls[0][1]["correlation_id"] == "abc"


@pytest.mark.parametrize("fail_source", ["prometheus", "loki", "k8s", "qdrant", "topology"])
def test_transport_failure_returns_error_envelope_not_raise(fail_source: str) -> None:
    """AC3: a transport-level failure → structured RawOutput error envelope, NEVER raises.

    Exercises every source: a transport that raises TransportError must not propagate — the adapter
    folds it into an error envelope dict so the graph continues.
    """
    composite = _composite(fail_source=fail_source)
    # route a call into the failing source
    if fail_source == "prometheus":
        result = composite.query_promql(query="up", time_window=TIME_WINDOW)
    elif fail_source == "loki":
        result = composite.query_loki(service="s", time_window=TIME_WINDOW, correlation_id=None)
    elif fail_source == "k8s":
        result = composite.k8s_get(namespace="demo", label_selector=None)
    elif fail_source == "qdrant":
        result = composite.search_playbook(query="q", top_k=1)
    else:  # topology
        result = composite.topology_read(service=None)

    assert isinstance(result, dict)
    err = result["error"]
    assert isinstance(err, dict)
    assert err["code"] == "transport_error"
    assert isinstance(err["detail"], str) and err["detail"]


@pytest.mark.parametrize(
    "backend_error_source", ["prometheus", "loki", "k8s", "qdrant", "topology"]
)
def test_backend_error_response_returns_error_envelope(backend_error_source: str) -> None:
    """AC3: a backend ERROR response (not a raise) is also folded into an error envelope."""
    composite = _composite(backend_error_source=backend_error_source)
    if backend_error_source == "prometheus":
        result = composite.query_promql(query="up", time_window=TIME_WINDOW)
    elif backend_error_source == "loki":
        result = composite.query_loki(service="s", time_window=TIME_WINDOW, correlation_id=None)
    elif backend_error_source == "k8s":
        result = composite.k8s_get(namespace="demo", label_selector=None)
    elif backend_error_source == "qdrant":
        result = composite.search_playbook(query="q", top_k=1)
    else:
        result = composite.topology_read(service=None)

    assert isinstance(result, dict)
    err = result["error"]
    assert isinstance(err, dict)
    assert err["code"] == "backend_error"
    assert isinstance(err["detail"], str) and err["detail"]


def test_error_envelope_carries_request_context() -> None:
    """AC3: the error envelope also carries the request context (query/time_window) for 4.2."""
    result = _composite(fail_source="prometheus").query_promql(query="up", time_window=TIME_WINDOW)
    assert result["query"] == "up"
    assert result["time_window"] == {"start": TIME_WINDOW["start"], "end": None}


# ---------------------------------------------------------------------------
# AC6 — offline deterministic fake transport (AD-12)
# ---------------------------------------------------------------------------


def test_fake_transport_is_deterministic() -> None:
    """AD-12: same args → identical fake output (no wall-clock/random/hash)."""
    from adapters.transport import FakeReadOnlyTransport

    a = FakeReadOnlyTransport()
    b = FakeReadOnlyTransport()
    assert a.read_prometheus(query="up", time_window=TIME_WINDOW) == b.read_prometheus(
        query="up", time_window=TIME_WINDOW
    )
    assert a.read_k8s(
        namespace="demo",
        kind="pods",
        name=None,
        subresource=None,
        label_selector=None,
        field_selector=None,
        previous=False,
    ) == b.read_k8s(
        namespace="demo",
        kind="pods",
        name=None,
        subresource=None,
        label_selector=None,
        field_selector=None,
        previous=False,
    )


def test_composite_output_is_deterministic() -> None:
    """AD-12: composite adapter over the fake is deterministic too."""
    a = _composite().query_promql(query="up", time_window=TIME_WINDOW)
    b = _composite().query_promql(query="up", time_window=TIME_WINDOW)
    assert a == b


# ---------------------------------------------------------------------------
# AC5 — RAW dict, NOT Evidence (boundary = 4.2)
# ---------------------------------------------------------------------------


def test_adapters_return_dict_not_evidence() -> None:
    """AC5: adapter output is a plain dict, NOT an Evidence object (normalization = 4.2)."""
    from models.evidence import Evidence

    result = _composite().query_promql(query="up", time_window=TIME_WINDOW)
    assert isinstance(result, dict)
    assert not isinstance(result, Evidence)


def _imported_root_modules(path: Path) -> set[str]:
    """Root module names imported by a Python source file (AST — ignores docstring prose)."""
    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                roots.add(node.module.split(".")[0])
    return roots


def _constructs_name(path: Path, name: str) -> bool:
    """True if the source constructs/calls ``name(...)`` anywhere (AST — not docstring prose)."""
    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def _called(func: ast.expr) -> str | None:
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            return func.attr
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _called(node.func) == name:
            return True
    return False


def test_adapters_source_does_not_import_models() -> None:
    """AC5 / AD-1: adapters/ source must NOT import models / construct Evidence (4.2 boundary).

    AST-based so docstring prose (which legitimately mentions the Evidence boundary) does not trip it.
    """
    for mod in ("transport.py", "readonly.py", "__init__.py"):
        path = REPO_ROOT / "adapters" / mod
        assert "models" not in _imported_root_modules(path), (
            f"adapters/{mod} imports models (Evidence = 4.2 boundary)"
        )
        assert not _constructs_name(path, "Evidence"), (
            f"adapters/{mod} constructs Evidence (4.2 boundary)"
        )


# ---------------------------------------------------------------------------
# AC4 / AC2 — read-only + one-way source invariants (gate#1 PASS + grep)
# ---------------------------------------------------------------------------


def test_adapters_import_only_tools_and_stdlib() -> None:
    """AC4 / AD-1 one-way: adapters/ source must NOT import graph/services/routers (back-edge).

    AST-based (inspects real import roots) so docstring prose does not produce false positives; the
    layers contract is independently enforced HARD-FAIL by `uv run lint-imports` (gate #2).
    """
    forbidden = {"graph", "services", "routers"}
    for mod in ("transport.py", "readonly.py", "__init__.py"):
        path = REPO_ROOT / "adapters" / mod
        imported = _imported_root_modules(path)
        assert imported.isdisjoint(forbidden), (
            f"adapters/{mod} imports forbidden layer(s): {imported & forbidden}"
        )


def test_no_hidden_write_path_in_adapters_source() -> None:
    """AC2: leader-style no-hidden-write-path grep — read verbs only, no mutating primitives.

    Gate #1 catches deny-verb NAMES + command patterns; this catches a read-named method that
    internally mutates (POST/PUT/PATCH/DELETE, subprocess, os.system, open('w'), getattr command
    building, kubectl command strings).
    """
    for mod in ("transport.py", "readonly.py", "__init__.py"):
        src = (REPO_ROOT / "adapters" / mod).read_text(encoding="utf-8")
        for forbidden in (
            "subprocess",
            "os.system",
            "os.exec",
            "requests.post",
            "requests.put",
            "requests.patch",
            "requests.delete",
            ".post(",
            ".put(",
            ".patch(",
            ".delete(",
            "kubectl",
            "rollout",
            "helm uninstall",
            "terraform destroy",
            "rm -rf",
        ):
            assert forbidden not in src, (
                f"adapters/{mod} contains hidden-write-path token '{forbidden}'"
            )


def test_transport_methods_are_read_only_named() -> None:
    """AC2: the transport seam method names are read-only (none is a deny-verb)."""
    from adapters.transport import FakeReadOnlyTransport
    from ci.denyset import WRITE_VERBS

    # The 5 read methods on the seam protocol (introspected from the concrete fake impl).
    read_methods = {name for name in dir(FakeReadOnlyTransport) if name.startswith("read_")}
    assert read_methods == {
        "read_prometheus",
        "read_loki",
        "read_k8s",
        "read_qdrant",
        "read_topology",
    }
    assert read_methods.isdisjoint(WRITE_VERBS)


def test_gate1_passes_on_real_adapters() -> None:
    """AC2/AC6: gate #1 exit 0 — scans the real non-empty adapters/ (+ tools/), zero violations."""
    result = subprocess.run(
        [sys.executable, str(GATE_SCRIPT), "--root", str(REPO_ROOT)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, (
        f"gate #1 should PASS on real adapters/:\n{result.stdout}\n{result.stderr}"
    )
    assert "PASS" in result.stdout


def test_adapters_source_is_non_empty_so_gate_is_exercised() -> None:
    """Sanity: the adapters/ the gate scans is genuinely non-empty (so a PASS is meaningful)."""
    py_files = sorted((REPO_ROOT / "adapters").glob("*.py"))
    assert len(py_files) >= 3  # __init__, transport, readonly
