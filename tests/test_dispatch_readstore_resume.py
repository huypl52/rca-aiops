"""Story 1.4 — async dispatch MECHANISM + read-store GET (poll) + in-process resume.

Covers AC1-10 (AD-10 #2-5, AD-3, AD-9, FR-7) for the dispatcher / GraphRunner
PORT / investigation registry / read-store / in-process resume:
  - AC1 — async non-blocking 202 (HTTP does NOT block on the investigation).
  - AC2 — GraphRunner PORT seam (dispatcher via port/DI; swap runner → unchanged;
          no compiled-graph import).
  - AC3 — investigation registry + status REGISTRY-LEVEL (NOT a graph-state key;
          13-key spine preserved; snapshot JSON-safe).
  - AC4 — read-store GET poll, no sync (non-blocking; unknown id → 404).
  - AC5 — in-process resume at-least-once idempotent (survives task-death).
  - AC6 — cross-restart boundary honest (in-process only; no LangGraph checkpointer).
  - AC7 — terminal/failed NOT silent + lifetime cap (FR-7).
  - AC8 — idempotent 1-2 preserved (202 + investigation_id; trigger_id idempotency).
  - AC9 — read-only trace (AD-3; no remediation/tool-registry path).
  - AC10 — one-way gate #2 + scope kept.

The dispatcher's background executor abstracts async away, so these tests are
SYNC (they poll the in-process store). ``time.monotonic``/``time.sleep`` are test-
helper only — AD-12 (no wall-clock) applies to graph nodes/reducers, NOT here.
"""

from __future__ import annotations

import ast
import asyncio
import json
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from graph.runner import (
    ContextBuilderRunner,
    GraphRunner,
    GraphRunnerResult,
    StubGraphRunner,
)
from graph.state import InvestigationState
from routers.app import create_app
from services.dispatch import (
    Dispatcher,
    dispatch,
    reset_dispatcher,
    set_default_dispatcher,
    startup_scan,
)
from services.investigations import (
    STATUS_FAILED,
    STATUS_RUNNING,
    STATUS_SUCCESS,
    InvestigationReadView,
    InvestigationRecord,
    InvestigationStore,
    default_store,
    reset_store,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DISPATCH_SRC = REPO_ROOT / "services" / "dispatch.py"
RUNNER_SRC = REPO_ROOT / "graph" / "runner.py"
INVESTIGATIONS_SRC = REPO_ROOT / "services" / "investigations.py"


# --- shared raw payload (mirror test_grouping.py — passes normalize-on-ingress) ---
PROM_DEP_TIMEOUT: dict[str, object] = {
    "fingerprint": "fp-dispatch-001",
    "status": "firing",
    "labels": {
        "alertname": "DependencyTimeout",
        "severity": "critical",
        "service": "order-service",
        "namespace": "demo",
        "scenario": "dependency_timeout",
    },
    "annotations": {
        "summary": "order-service dependency timeout",
        "description": "Downstream dependency timeout firing on order-service",
    },
    "startsAt": "2026-06-24T10:00:00Z",
    "endsAt": "2026-06-24T10:05:00Z",
}

TRIGGER_DICT: dict[str, Any] = {
    "trigger_id": "tr-dispatch-001",
    "service": "order-service",
    "namespace": "demo",
    "started_at": "2026-06-24T10:00:00Z",
    "ends_at": "2026-06-24T10:05:00Z",
    "labels": {"severity": "critical", "scenario": "dependency_timeout"},
    "affected_services": ["order-service", "inventory"],
}


# ---------------------------------------------------------------------------
# Test runners (GraphRunner Protocol impls) — deterministic, no real I/O.
# ---------------------------------------------------------------------------


class _GatedRunner:
    """Runner that polls a threading.Event before terminal (non-blocking on the
    bg loop). For AC1 (non-blocking) + AC5 (survives-task-death). Counts calls."""

    def __init__(self, gate: threading.Event) -> None:
        self.gate = gate
        self.calls = 0

    async def run(
        self, trigger: dict[str, Any], investigation_id: str, max_iterations: int
    ) -> GraphRunnerResult:
        # Poll the gate until released — the gate (NOT max_iterations) controls
        # termination; tests always release the gate before waiting for terminal.
        # max_iterations is accepted to satisfy the PORT signature but ignored
        # (the lifetime cap is exercised by _LoopingRunner / AC7, not here).
        del trigger, max_iterations
        self.calls += 1
        while not self.gate.is_set():
            await asyncio.sleep(0.005)
        return GraphRunnerResult(
            status="success",
            state_snapshot={"context": {"gated": True, "id": investigation_id}},
            report=None,
        )


class _FailingRunner:
    """Runner that raises → dispatcher maps to status=failed (NOT silent, AC7)."""

    async def run(
        self, trigger: dict[str, Any], investigation_id: str, max_iterations: int
    ) -> GraphRunnerResult:
        del trigger, investigation_id, max_iterations
        raise RuntimeError("boom (AC7 not-silent failure)")


class _LoopingRunner:
    """Runner that honors max_iterations (loops `desired` times; exceed cap → failed)."""

    def __init__(self, desired: int) -> None:
        self.desired = desired

    async def run(
        self, trigger: dict[str, Any], investigation_id: str, max_iterations: int
    ) -> GraphRunnerResult:
        del trigger, investigation_id
        for _ in range(self.desired):
            await asyncio.sleep(0)  # yield to the loop (simulates graph iterations)
        if self.desired > max_iterations:
            return GraphRunnerResult(
                status="failed",
                state_snapshot={"context": {"reason": "cap_exceeded"}},
                report=None,
            )
        return GraphRunnerResult(status="success", state_snapshot={"context": {}}, report=None)


class _RecordingRunner:
    """Wraps a runner and records how many times run() was invoked (idempotency)."""

    def __init__(self, inner: GraphRunner) -> None:
        self.inner = inner
        self.calls = 0

    async def run(
        self, trigger: dict[str, Any], investigation_id: str, max_iterations: int
    ) -> GraphRunnerResult:
        self.calls += 1
        result: GraphRunnerResult = await self.inner.run(trigger, investigation_id, max_iterations)
        return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _wait_until(predicate: Any, timeout: float = 2.0, interval: float = 0.01) -> bool:
    """Poll ``predicate`` until True or timeout (test helper, sync)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def _import_module_paths(path: Path) -> list[str]:
    """Full import module strings in a source file (AST — no string false-positives)."""
    tree = ast.parse(path.read_text())
    paths: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            paths.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            paths.append(node.module)
    return paths


def _names(path: Path) -> set[str]:
    """All identifier names referenced in a source file (AST)."""
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return names


def _terminal(store: InvestigationStore, investigation_id: str) -> InvestigationRecord:
    """Assert + narrow: the investigation record exists and is terminal (mypy-safe)."""
    record = store.get(investigation_id)
    assert record is not None, f"no record for {investigation_id}"
    assert record.is_terminal, f"not terminal: {record.status}"
    return record


def _view(store: InvestigationStore, investigation_id: str) -> InvestigationReadView:
    """Assert + narrow: a read-view exists for ``investigation_id`` (mypy-safe)."""
    view = store.view(investigation_id)
    assert view is not None, f"no view for {investigation_id}"
    return view


def _is_terminal(store: InvestigationStore, investigation_id: str) -> bool:
    """None-safe terminal check for use inside ``_wait_until`` predicates (mypy-safe)."""
    record = store.get(investigation_id)
    return record is not None and record.is_terminal


@pytest.fixture(autouse=True)
def _reset_default_dispatcher() -> Any:
    """Fresh default dispatcher + clean store per test (in-process isolation)."""
    reset_store()
    reset_dispatcher()
    set_default_dispatcher(Dispatcher())  # fresh default (ContextBuilderRunner)
    yield
    reset_dispatcher()
    reset_store()


# ===========================================================================
# AC1 — async non-blocking 202 (AD-10#2: 1-2 CONTRACT, 1-4 MECHANISM)
# ===========================================================================


def test_ac1_dispatch_returns_before_runner_terminal() -> None:
    """dispatch() returns immediately; store shows running while runner is gated."""
    gate = threading.Event()
    dispatcher = Dispatcher(runner=_GatedRunner(gate), store=InvestigationStore())
    inv_id = "inv-ac1-unit"

    returned = dispatcher.dispatch(inv_id, TRIGGER_DICT)

    assert returned == inv_id
    # runner is gated (not terminal) yet the store already shows running → non-blocking
    record = dispatcher.store.get(inv_id)
    assert record is not None
    assert record.status == STATUS_RUNNING
    assert not record.is_terminal

    # release the runner and let it reach terminal
    gate.set()
    assert _wait_until(lambda: _is_terminal(dispatcher.store, inv_id))
    assert _terminal(dispatcher.store, inv_id).status == STATUS_SUCCESS

    dispatcher.kill(inv_id)


def test_ac1_http_202_before_runner_terminal() -> None:
    """HTTP 202 returns BEFORE a gated runner reaches terminal (runtime non-blocking)."""
    gate = threading.Event()
    set_default_dispatcher(Dispatcher(runner=_GatedRunner(gate)))
    client = TestClient(create_app())

    response = client.post("/api/alerts/prometheus", json=PROM_DEP_TIMEOUT)

    assert response.status_code == 202
    inv_id = response.json()["investigation_id"]
    assert inv_id

    # The runner is still gated — yet GET returns immediately with status=running.
    read = client.get(f"/api/investigations/{inv_id}").json()
    assert read["status"] == STATUS_RUNNING

    gate.set()
    assert _wait_until(
        lambda: client.get(f"/api/investigations/{inv_id}").json()["status"] == STATUS_SUCCESS
    )


# ===========================================================================
# AC2 — GraphRunner PORT seam (1-4 defines, 3-5 plugs compiled graph)
# ===========================================================================


def test_ac2_dispatcher_runner_satisfies_port() -> None:
    """The dispatcher's runner satisfies the GraphRunner Protocol (entry contract)."""
    dispatcher = Dispatcher(runner=ContextBuilderRunner(), store=InvestigationStore())
    assert isinstance(dispatcher.runner, GraphRunner)
    assert isinstance(StubGraphRunner(), GraphRunner)


def test_ac2_swap_runner_dispatcher_unchanged() -> None:
    """Swapping the runner impl (stub ↔ 1-3 ↔ fake-compiled) leaves the dispatcher
    behavior identical except the runner output — the seam 3-5 exploits."""
    trigger = dict(TRIGGER_DICT)

    d_stub = Dispatcher(runner=StubGraphRunner(), store=InvestigationStore())
    d_real = Dispatcher(runner=ContextBuilderRunner(), store=InvestigationStore())

    d_stub.dispatch("inv-swap", trigger)
    d_real.dispatch("inv-swap", trigger)

    assert _wait_until(lambda: _is_terminal(d_stub.store, "inv-swap"))
    assert _wait_until(lambda: _is_terminal(d_real.store, "inv-swap"))

    # both reach success via the SAME dispatcher contract — only the snapshot differs
    assert _terminal(d_stub.store, "inv-swap").status == STATUS_SUCCESS
    assert _terminal(d_real.store, "inv-swap").status == STATUS_SUCCESS
    # 1-3 runner actually built context; stub did not — dispatcher doesn't care
    assert _terminal(d_real.store, "inv-swap").state_snapshot["context"]


def test_ac2_dispatcher_does_not_import_compiled_graph() -> None:
    """Dispatcher imports ONLY the graph.runner PORT — no state/nodes/compile internals."""
    paths = _import_module_paths(DISPATCH_SRC)
    graph_imports = [p for p in paths if p == "graph" or p.startswith("graph.")]
    assert graph_imports == ["graph.runner"], (
        f"dispatcher may import ONLY the graph.runner port (AD-2); found {graph_imports}"
    )
    # no compiled-graph / node / state-internal symbols
    forbidden = _names(DISPATCH_SRC) & {
        "StateGraph",
        "compile",
        "add_node",
        "add_edge",
        "SqliteSaver",
        "MemorySaver",
        "incident_context_builder",
        "create_initial_state",
        "InvestigationState",
    }
    assert not forbidden, f"dispatcher must not reference compiled-graph internals: {forbidden}"


# ===========================================================================
# AC3 — investigation registry + status REGISTRY-LEVEL (AD-9 spine preserved)
# ===========================================================================


def test_ac3_status_is_registry_level_not_graph_state() -> None:
    """Lifecycle status lives in the registry, NOT in the 13-key InvestigationState spine."""
    assert len(InvestigationState.__annotations__) == 13  # spine UNCHANGED (AD-9)
    assert "status" not in InvestigationState.__annotations__

    store = InvestigationStore()
    store.register_running("inv-ac3", TRIGGER_DICT)
    record = store.get("inv-ac3")
    assert record is not None
    assert record.status == STATUS_RUNNING  # registry-level
    assert _view(store, "inv-ac3").status == STATUS_RUNNING


def test_ac3_state_snapshot_is_json_safe() -> None:
    """The terminal state-snapshot is JSON-safe (AD-9 — gate #3 axis, round-trip)."""
    dispatcher = Dispatcher(runner=ContextBuilderRunner(), store=InvestigationStore())
    dispatcher.dispatch("inv-ac3-json", TRIGGER_DICT)
    assert _wait_until(lambda: _is_terminal(dispatcher.store, "inv-ac3-json"))
    snapshot = _terminal(dispatcher.store, "inv-ac3-json").state_snapshot
    round_tripped = json.loads(json.dumps(snapshot))
    assert round_tripped == snapshot  # deep-equal round-trip


# ===========================================================================
# AC4 — read-store GET poll, no sync (AD-10#3)
# ===========================================================================


def test_ac4_get_returns_store_nonblocking() -> None:
    """GET returns the store snapshot immediately (non-blocking) while running."""
    gate = threading.Event()
    set_default_dispatcher(Dispatcher(runner=_GatedRunner(gate)))
    client = TestClient(create_app())

    inv_id = client.post("/api/alerts/prometheus", json=PROM_DEP_TIMEOUT).json()["investigation_id"]
    read = client.get(f"/api/investigations/{inv_id}").json()
    assert read["investigation_id"] == inv_id
    assert read["status"] == STATUS_RUNNING  # non-blocking: returned before terminal
    assert isinstance(read["state_snapshot"], dict)
    gate.set()


def test_ac4_unknown_investigation_id_is_404() -> None:
    """Unknown investigation_id → 404 (graceful read-store lookup miss)."""
    client = TestClient(create_app())
    response = client.get("/api/investigations/never-minted")
    assert response.status_code == 404


def test_ac4_report_none_for_minimal_runner() -> None:
    """report is None until the rca_writer node (Story 5-1) — minimal runner emits None."""
    set_default_dispatcher(Dispatcher(runner=ContextBuilderRunner()))
    client = TestClient(create_app())
    inv_id = client.post("/api/alerts/prometheus", json=PROM_DEP_TIMEOUT).json()["investigation_id"]
    assert _wait_until(
        lambda: client.get(f"/api/investigations/{inv_id}").json()["status"] == STATUS_SUCCESS
    )
    assert client.get(f"/api/investigations/{inv_id}").json()["report"] is None


# ===========================================================================
# AC5 — in-process resume at-least-once idempotent (survives task-death)
# ===========================================================================


def test_ac5_resume_survives_task_death() -> None:
    """Kill the in-flight task → store stays non-terminal → startup_scan re-dispatches
    at-least-once → same idempotent terminal outcome (read-only, no double-apply)."""
    gate = threading.Event()
    runner = _GatedRunner(gate)
    dispatcher = Dispatcher(runner=runner, store=InvestigationStore())
    inv_id = "inv-ac5"

    dispatcher.dispatch(inv_id, TRIGGER_DICT)
    # ensure the run actually started (mid-run), then simulate task-death
    assert _wait_until(lambda: runner.calls >= 1)
    assert dispatcher.has_inflight(inv_id)
    assert dispatcher.kill(inv_id) is True

    # task dead → store record stays NON-terminal (running) → resume source
    assert _wait_until(lambda: not dispatcher.has_inflight(inv_id))
    record = dispatcher.store.get(inv_id)
    assert record is not None
    assert record.status == STATUS_RUNNING  # NOT marked failed (crash ≠ failure)

    # release the gate so the re-dispatched run can terminate
    gate.set()
    resumed = dispatcher.startup_scan()
    assert resumed >= 1  # at-least-once re-dispatch happened

    assert _wait_until(lambda: _is_terminal(dispatcher.store, inv_id))
    final = _terminal(dispatcher.store, inv_id)
    assert final.status == STATUS_SUCCESS  # idempotent outcome
    assert runner.calls >= 2  # initial run + resume re-dispatch


def test_ac5_no_duplicate_concurrent_task() -> None:
    """Re-dispatching an id with a LIVE in-flight task is a no-op (no duplicate spawn)."""
    gate = threading.Event()
    runner = _GatedRunner(gate)
    dispatcher = Dispatcher(runner=runner, store=InvestigationStore())
    inv_id = "inv-ac5-dedup"

    dispatcher.dispatch(inv_id, TRIGGER_DICT)
    assert _wait_until(lambda: runner.calls >= 1 and dispatcher.has_inflight(inv_id))
    calls_before = runner.calls

    # re-dispatch the SAME id while the task is live → idempotent no-op
    dispatcher.dispatch(inv_id, TRIGGER_DICT)
    time.sleep(0.05)  # give the loop a chance to (not) spawn a duplicate
    assert runner.calls == calls_before  # no second concurrent run

    gate.set()
    assert _wait_until(lambda: _is_terminal(dispatcher.store, inv_id))


# ===========================================================================
# AC6 — cross-restart boundary HONEST (7-4 NOT 1-4)
# ===========================================================================


def test_ac6_no_langgraph_checkpointer_attached() -> None:
    """1-4 uses an in-process registry/executor — NO LangGraph checkpointer (3-5/7-4)."""
    forbidden = (_names(DISPATCH_SRC) | _names(RUNNER_SRC)) & {
        "SqliteSaver",
        "MemorySaver",
        "PostgresSaver",
        "checkpointer",
        "StateGraph",
    }
    assert not forbidden, f"1-4 must NOT attach a LangGraph checkpointer (7-4): {forbidden}"


def test_ac6_constrain_note_documents_cross_restart_boundary() -> None:
    """Constrain notes record that cross-restart durability = Story 7-4 (in-process only)."""
    combined = DISPATCH_SRC.read_text() + "\n" + INVESTIGATIONS_SRC.read_text()
    assert "7-4" in combined
    assert "SqliteSaver" in combined
    assert "cross-restart" in combined.lower() or "cross_restart" in combined.lower()


# ===========================================================================
# AC7 — terminal/failed NOT silent + lifetime cap (AD-10#5, FR-7)
# ===========================================================================


def test_ac7_runner_failure_marks_failed_not_silent() -> None:
    """A failing runner → status=failed (NOT silent, NOT stuck running)."""
    dispatcher = Dispatcher(runner=_FailingRunner(), store=InvestigationStore())
    dispatcher.dispatch("inv-ac7-fail", TRIGGER_DICT)
    assert _wait_until(lambda: _is_terminal(dispatcher.store, "inv-ac7-fail"))
    assert _terminal(dispatcher.store, "inv-ac7-fail").status == STATUS_FAILED


def test_ac7_lifetime_cap_marks_failed() -> None:
    """Exceeding the dispatcher-level lifetime cap (FR-7) → status=failed."""
    # runner wants 50 iterations; dispatcher caps at 10 → runner reports failed
    dispatcher = Dispatcher(
        runner=_LoopingRunner(desired=50), store=InvestigationStore(), max_iterations=10
    )
    dispatcher.dispatch("inv-ac7-cap", TRIGGER_DICT)
    assert _wait_until(lambda: _is_terminal(dispatcher.store, "inv-ac7-cap"))
    assert _terminal(dispatcher.store, "inv-ac7-cap").status == STATUS_FAILED


def test_ac7_success_marks_success() -> None:
    """A successful runner → status=success (terminal)."""
    dispatcher = Dispatcher(runner=ContextBuilderRunner(), store=InvestigationStore())
    dispatcher.dispatch("inv-ac7-ok", TRIGGER_DICT)
    assert _wait_until(lambda: _is_terminal(dispatcher.store, "inv-ac7-ok"))
    assert _terminal(dispatcher.store, "inv-ac7-ok").status == STATUS_SUCCESS


# ===========================================================================
# AC8 — idempotent 1-2 preserved (no regression under dispatch wiring)
# ===========================================================================


def test_ac8_idempotent_trigger_id_returns_same_investigation_id() -> None:
    """Re-sending the same trigger_id → same investigation_id (1-2 idempotency preserved)."""
    client = TestClient(create_app())
    first = client.post("/api/alerts/prometheus", json=PROM_DEP_TIMEOUT).json()["investigation_id"]
    second = client.post("/api/alerts/prometheus", json=PROM_DEP_TIMEOUT).json()["investigation_id"]
    assert first == second  # AD-10 #1 idempotency (1-2) NOT regressed by dispatch wiring


def test_ac8_distinct_trigger_id_returns_distinct_investigation_id() -> None:
    """Distinct trigger_id → distinct investigation_id (1-2 1:1 preserved)."""
    client = TestClient(create_app())
    payload_a = {**PROM_DEP_TIMEOUT, "fingerprint": "fp-distinct-a"}
    payload_b = {**PROM_DEP_TIMEOUT, "fingerprint": "fp-distinct-b"}
    a = client.post("/api/alerts/prometheus", json=payload_a).json()["investigation_id"]
    b = client.post("/api/alerts/prometheus", json=payload_b).json()["investigation_id"]
    assert a != b


def test_ac8_response_is_202_with_investigation_id_body() -> None:
    """The 202 + {investigation_id} body from 1-2 is unchanged by the dispatch call."""
    client = TestClient(create_app())
    response = client.post("/api/alerts/prometheus", json=PROM_DEP_TIMEOUT)
    assert response.status_code == 202
    assert set(response.json().keys()) == {"investigation_id"}


# ===========================================================================
# AC9 — read-only trace (AD-3 — NOT impl tool registry 2-1)
# ===========================================================================


def test_ac9_read_only_trace_note_present() -> None:
    """AD-3 read-only trace is documented (at-least-once safe because read-only)."""
    combined = DISPATCH_SRC.read_text() + "\n" + INVESTIGATIONS_SRC.read_text()
    assert "read-only" in combined.lower() or "read_only" in combined.lower()
    assert "2-1" in combined  # tool registry deferred to Story 2-1


def test_ac9_no_remediation_or_write_path_in_services() -> None:
    """No write/remediation/exec path in the dispatcher/store (tool registry = 2-1)."""
    forbidden = (_names(DISPATCH_SRC) | _names(INVESTIGATIONS_SRC)) & {
        "subprocess",
        "kubectl",
        "patch",
        "delete",
        "scale",
        "rollback",
        "exec",
    }
    assert not forbidden, f"no write/remediation path in services (AD-3/2-1): {forbidden}"


# ===========================================================================
# AC10 — one-way gate #2 + scope kept
# ===========================================================================


def test_ac10_services_do_not_import_adapters_or_tools() -> None:
    """services/ imports neither adapters nor tools (gate #2 one-way, AD-1)."""
    for src in (DISPATCH_SRC, INVESTIGATIONS_SRC):
        roots = {p.split(".")[0] for p in _import_module_paths(src)}
        assert "adapters" not in roots, f"{src.name} imports adapters (back-edge)"
        assert "tools" not in roots, f"{src.name} imports tools (back-edge)"


def test_ac10_gate2_one_way_contract_kept() -> None:
    """The import-linter layers contract is KEPT (routers→services→graph→...)."""
    result = subprocess.run(
        ["uv", "run", "lint-imports"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, f"gate #2 BROKEN:\n{result.stdout}\n{result.stderr}"
    assert "KEPT" in result.stdout


def test_ac10_dispatch_and_startup_scan_are_module_convenience_wrappers() -> None:
    """The module-level dispatch()/startup_scan() delegate to the default dispatcher."""
    # dispatch registers + returns the id immediately (non-blocking)
    inv_id = dispatch("inv-ac10-wrapper", TRIGGER_DICT)
    assert inv_id == "inv-ac10-wrapper"
    assert default_store().get("inv-ac10-wrapper") is not None
    # startup_scan returns an int count (0 here — the in-flight task is still running)
    assert isinstance(startup_scan(), int)
