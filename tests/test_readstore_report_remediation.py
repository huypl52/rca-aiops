"""Story 5.2 — read-store RCA report round-trip + remediation-off output guard +
partial-status wiring (4-A2) end-to-end.

Covers the Story 5-2 STANDARD spotlights:
  - AC1 — the FULL 5-1 cited report (6-key shape) round-trips store → response
    (AD-10 #3 — poll, no sync). A REAL report from ``build_rca_writer`` (Story 5-1)
    is stored → ``view`` / GET returns all 6 keys (``root_cause`` / ``evidence_backing``
    / ``confidence`` / ``open_questions`` / ``uncertainty`` / ``remediation``).
  - AC2 — the OUTPUT-SIDE remediation-off guard (defense-in-depth, T9 / D12): a report
    whose ``remediation`` CARRIES action text (simulating a prod/future report) → the
    read-view / GET response has ``remediation == []`` (the guard STRIPPED it). The guard
    is non-bypassable (EVERY ``view`` strips, idempotent) + READ-ONLY (the STORED record
    is intact — a projection strip, NEVER a write, NEVER a remediation synthesis).
  - 4-A2 partial-wiring (carry-forward) — a runner result with ``status="partial"`` →
    store record ``status="partial"`` (NOT masked as ``failed``) → GET ``status="partial"``;
    AND ``state_snapshot.sufficiency.gap`` (the "chưa đủ" honest content) is preserved
    (AD-10 #5 end-to-end). ``partial`` IS terminal (not re-dispatched). An unknown runner
    status STILL → ``failed`` (the defensive guard is preserved).
  - AD-9 — ``status`` stays REGISTRY-LEVEL: ``STATUS_PARTIAL`` is a registry constant;
    the 13-key ``InvestigationState`` spine is unchanged (gate #3 / gate #5 axis).
  - read-only (AC9 / §3.8 / AD-3) — the guard adds NO write/exec/patch verb (the gate #1
    AST axis); it is a projection strip, never a write, never a remediation synthesis.

The dispatcher's background executor abstracts async away, so these tests are SYNC (they
poll the in-process store). ``time.monotonic``/``time.sleep`` are test-helpers only —
AD-12 (no wall-clock) applies to graph nodes/reducers, NOT here.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from graph.nodes.rca_writer import build_rca_writer
from graph.runner import GraphRunnerResult
from graph.state import InvestigationState, JsonValue
from routers.app import create_app
from services.dispatch import Dispatcher
from services.investigations import (
    STATUS_FAILED,
    STATUS_PARTIAL,
    STATUS_RUNNING,
    STATUS_SUCCESS,
    InvestigationStore,
    default_store,
    reset_store,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
INVESTIGATIONS_SRC = REPO_ROOT / "services" / "investigations.py"
DISPATCH_SRC = REPO_ROOT / "services" / "dispatch.py"

# The 6-key FR-9 report shape the read-store MUST surface (AD-10 #3).
_REPORT_KEYS: set[str] = {
    "root_cause",
    "evidence_backing",
    "confidence",
    "open_questions",
    "uncertainty",
    "remediation",
}

# Repeat count for the idempotent/non-bypassable guard probe (AC2).
_REPEAT_VIEWS: int = 3

TRIGGER_DICT: dict[str, Any] = {
    "trigger_id": "tr-readstore-001",
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


class _PartialRunner:
    """Runner that returns an honest ``partial`` (max-iter exhausted) + a sufficiency gap.

    Models Story 4-3's honest partial: the run ENDED inconclusive (AD-10 #5), carrying a
    ``sufficiency.gap`` ("chưa đủ — cần thêm X"). Its snapshot deliberately includes
    ``sufficiency.gap`` so the 4-A2 wiring's "gap round-trips store → response" is provable.
    """

    async def run(
        self, trigger: dict[str, Any], investigation_id: str, max_iterations: int
    ) -> GraphRunnerResult:
        del trigger, investigation_id, max_iterations
        return GraphRunnerResult(
            status="partial",
            state_snapshot={
                "context": {},
                "sufficiency": {"gap": "chưa đủ — cần thêm latency breakdown"},
            },
            report=None,
        )


class _BogusRunner:
    """Runner that returns a status OUTSIDE {success, failed, partial} → defensive FAILED."""

    async def run(
        self, trigger: dict[str, Any], investigation_id: str, max_iterations: int
    ) -> GraphRunnerResult:
        del trigger, investigation_id, max_iterations
        return GraphRunnerResult(status="bogus", state_snapshot={"context": {}}, report=None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _names(path: Path) -> set[str]:
    """All identifier names referenced in a source file (AST — string-literal-immune)."""
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return names


def _wait_until(predicate: Any, timeout: float = 2.0, interval: float = 0.01) -> bool:
    """Poll ``predicate`` until True or timeout (test helper, sync)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def _is_terminal(store: InvestigationStore, investigation_id: str) -> bool:
    record = store.get(investigation_id)
    return record is not None and record.is_terminal


def _real_report() -> dict[str, JsonValue]:
    """Build a REAL 6-key cited report from the 5-1 writer (K2 honest-synthetic evidence).

    One grounded candidate (H01 backed by a citable evidence with a non-empty raw_excerpt) →
    a non-empty ``root_cause`` + ``evidence_backing``; AD-7 verbatim confidence + a projected
    ``uncertainty`` gap. This is the producer side (5-1); 5-2 verifies it round-trips the store.
    """
    node = build_rca_writer()
    state = cast(
        InvestigationState,
        {
            "hypotheses": [
                {"id": "H01", "priority": 1, "plan": {}, "status": "open"},
            ],
            "evidence": [
                {
                    "source_name": "prometheus",
                    "source_type": "metrics",
                    "query": "up",
                    "summary": "checkout instance down",
                    "raw_excerpt": "checkout_up=0",
                    "supports": ["H01"],
                    "timestamp_range": {"start": "t1", "end": "t2"},
                }
            ],
            "sufficiency": {
                "floor_pass": True,
                "ceiling_confidence": 0.8,
                "categorical": "medium",
                "gap": "chưa đủ — cần thêm latency",
            },
        },
    )
    out = node(state)
    report = out["report"]
    assert isinstance(report, dict), "the 5-1 writer must return a dict report"
    return report


def _contaminated_report() -> dict[str, Any]:
    """A report carrying remediation ACTION TEXT (simulating a prod/future report — AC2 probe).

    Looks like a valid 6-key report EXCEPT ``remediation`` carries leaked action text. The 5-2
    OUTPUT guard must strip it at the read boundary regardless of producer.
    """
    return {
        "root_cause": [{"rank": 1, "hypothesis_id": "H01", "priority": 1, "citations": []}],
        "evidence_backing": [],
        "confidence": {"ceiling_confidence": 0.5, "categorical": "low"},
        "open_questions": [],
        "uncertainty": "",
        "remediation": ["restart the checkout pod", "scale replicas to 3"],  # leaked action text
    }


def _store_terminal(
    store: InvestigationStore,
    investigation_id: str,
    status: str,
    snapshot: dict[str, Any] | None,
    report: dict[str, Any] | None,
) -> None:
    """Register + mark an investigation terminal in ``store`` (test setup, not the dispatcher)."""
    store.register_running(investigation_id, TRIGGER_DICT)
    store.set_terminal(investigation_id, status, snapshot, report)


@pytest.fixture(autouse=True)
def _reset_default_store() -> Any:
    """Clean default store per test (in-process isolation for the HTTP GET tests)."""
    reset_store()
    yield
    reset_store()


# ===========================================================================
# AC1 — the FULL 6-key report round-trips store → response (AD-10 #3)
# ===========================================================================


def test_ac1_real_report_has_six_keys() -> None:
    """Sanity: the REAL 5-1 report (via build_rca_writer) carries exactly the 6 FR-9 keys."""
    report = _real_report()
    assert set(report.keys()) == _REPORT_KEYS


def test_ac1_full_report_round_trips_store_to_view() -> None:
    """AC1: a stored real report → ``view`` returns the FULL 6-key report (AD-10 #3)."""
    store = InvestigationStore()
    report = _real_report()
    _store_terminal(store, "inv-ac1-unit", STATUS_SUCCESS, {"context": {}}, dict(report))

    view = store.view("inv-ac1-unit")
    assert view is not None
    assert view.status == STATUS_SUCCESS
    assert view.report is not None
    assert set(view.report.keys()) == _REPORT_KEYS  # all 6 keys round-trip
    # the grounded candidate + backing survive the store → view projection
    assert view.report["root_cause"] == report["root_cause"]
    assert view.report["evidence_backing"] == report["evidence_backing"]
    assert view.report["confidence"] == report["confidence"]
    # remediation is [] (the 5-1 producer default) → the guard is a no-op here
    assert view.report["remediation"] == []


def test_ac1_full_report_round_trips_store_to_http_get() -> None:
    """AC1: a stored real report → GET /api/investigations/{id} returns the FULL 6-key report."""
    report = _real_report()
    _store_terminal(default_store(), "inv-ac1-http", STATUS_SUCCESS, {"context": {}}, dict(report))

    client = TestClient(create_app())
    read = client.get("/api/investigations/inv-ac1-http").json()
    assert read["status"] == STATUS_SUCCESS
    assert isinstance(read["report"], dict)
    assert set(read["report"].keys()) == _REPORT_KEYS  # all 6 keys surface via the API
    assert read["report"]["root_cause"] == report["root_cause"]


# ===========================================================================
# AC2 — the remediation-off OUTPUT guard (defense-in-depth, T9 / D12)
# ===========================================================================


def test_ac2_guard_strips_remediation_action_text_from_view() -> None:
    """AC2 probe: a report CARRYING remediation action text → view has remediation == []."""
    store = InvestigationStore()
    _store_terminal(store, "inv-ac2-strip", STATUS_SUCCESS, {"context": {}}, _contaminated_report())
    view = store.view("inv-ac2-strip")
    assert view is not None
    assert view.report is not None
    assert view.report["remediation"] == []  # the guard STRIPPED the leaked action text


def test_ac2_guard_strips_remediation_action_text_from_http_get() -> None:
    """AC2 probe: a contaminated report → GET response remediation == [] (output boundary)."""
    _store_terminal(
        default_store(), "inv-ac2-http", STATUS_SUCCESS, {"context": {}}, _contaminated_report()
    )
    client = TestClient(create_app())
    read = client.get("/api/investigations/inv-ac2-http").json()
    assert read["report"]["remediation"] == []  # NEVER leaks action text to a client


def test_ac2_guard_is_read_only_stored_record_intact() -> None:
    """AC2: the guard is a PROJECTION strip — the STORED record is NEVER mutated (§3.8 / AD-3)."""
    store = InvestigationStore()
    _store_terminal(store, "inv-ac2-ro", STATUS_SUCCESS, {"context": {}}, _contaminated_report())
    # the read-view strips ...
    view = store.view("inv-ac2-ro")
    assert view is not None and view.report is not None
    assert view.report["remediation"] == []
    # ... but the STORED record RETAINS the original content (read-only strip, not a write)
    record = store.get("inv-ac2-ro")
    assert record is not None and record.report is not None
    assert record.report["remediation"] == ["restart the checkout pod", "scale replicas to 3"]


def test_ac2_guard_is_non_bypassable_and_idempotent() -> None:
    """AC2: EVERY view strips (non-bypassable chokepoint); repeated reads never leak content."""
    store = InvestigationStore()
    _store_terminal(store, "inv-ac2-idem", STATUS_SUCCESS, {"context": {}}, _contaminated_report())
    for _ in range(_REPEAT_VIEWS):
        view = store.view("inv-ac2-idem")
        assert view is not None and view.report is not None
        assert view.report["remediation"] == []  # every single read strips


def test_ac2_guard_leaves_non_dict_report_unchanged() -> None:
    """AC2: a None/non-dict report (no rca_writer ran) is returned UNCHANGED (no structure invented)."""
    store = InvestigationStore()
    _store_terminal(store, "inv-ac2-none", STATUS_SUCCESS, {"context": {}}, None)
    view = store.view("inv-ac2-none")
    assert view is not None
    assert view.report is None  # nothing to strip — no remediation field is invented


# ===========================================================================
# 4-A2 — partial-status wiring end-to-end (NOT masked as failed; gap preserved)
# ===========================================================================


def test_partial_is_terminal_in_store() -> None:
    """``partial`` IS terminal (member of ``_TERMINAL``); ``non_terminal`` excludes it (not a crash)."""
    store = InvestigationStore()
    _store_terminal(store, "inv-pt-term", STATUS_PARTIAL, {"context": {}}, None)
    record = store.get("inv-pt-term")
    assert record is not None
    assert record.status == STATUS_PARTIAL
    assert record.is_terminal  # the run ENDED — partial is terminal
    assert store.non_terminal() == []  # NOT a crash to resume (excluded from the resume scan)


def test_partial_surfaces_end_to_end_not_failed_gap_preserved() -> None:
    """4-A2 / AD-10 #5: runner ``partial`` → store ``partial`` (NOT failed) → GET ``partial`` + gap."""
    dispatcher = Dispatcher(runner=_PartialRunner(), store=InvestigationStore())
    inv_id = "inv-partial-e2e"
    dispatcher.dispatch(inv_id, TRIGGER_DICT)
    assert _wait_until(lambda: _is_terminal(dispatcher.store, inv_id))

    record = dispatcher.store.get(inv_id)
    assert record is not None
    assert record.status == STATUS_PARTIAL  # NOT masked as failed (4-A2 wiring)
    assert record.status != STATUS_FAILED

    view = dispatcher.store.view(inv_id)
    assert view is not None
    assert view.status == STATUS_PARTIAL
    # the "chưa đủ" honest content round-trips store → view (AD-10 #5 — reportable gap)
    assert view.state_snapshot["sufficiency"]["gap"] == "chưa đủ — cần thêm latency breakdown"


def test_partial_surfaces_via_http_get() -> None:
    """4-A2: a stored partial → GET surfaces status=partial (NOT failed) + the gap."""
    snapshot = {"context": {}, "sufficiency": {"gap": "chưa đủ — cần thêm latency breakdown"}}
    _store_terminal(default_store(), "inv-partial-http", STATUS_PARTIAL, snapshot, None)
    client = TestClient(create_app())
    read = client.get("/api/investigations/inv-partial-http").json()
    assert read["status"] == STATUS_PARTIAL  # honest partial surfaces at the API (NOT failed)
    assert read["state_snapshot"]["sufficiency"]["gap"] == "chưa đủ — cần thêm latency breakdown"


def test_unknown_runner_status_still_falls_to_failed() -> None:
    """The defensive guard is PRESERVED: a status outside {success,failed,partial} → FAILED (not silent)."""
    dispatcher = Dispatcher(runner=_BogusRunner(), store=InvestigationStore())
    dispatcher.dispatch("inv-bogus", TRIGGER_DICT)
    assert _wait_until(lambda: _is_terminal(dispatcher.store, "inv-bogus"))
    record = dispatcher.store.get("inv-bogus")
    assert record is not None
    assert (
        record.status == STATUS_FAILED
    )  # unknown → failed (runner contract violation, not silent)


def test_failed_and_success_still_accepted() -> None:
    """success/failed pass-through is UNCHANGED by the 4-A2 wiring (no regression)."""
    store = InvestigationStore()
    _store_terminal(store, "inv-ok", STATUS_SUCCESS, {"context": {}}, None)
    _store_terminal(store, "inv-bad", STATUS_FAILED, {"context": {}}, None)
    ok = store.get("inv-ok")
    bad = store.get("inv-bad")
    assert ok is not None and bad is not None
    assert ok.status == STATUS_SUCCESS
    assert bad.status == STATUS_FAILED
    assert ok.is_terminal and bad.is_terminal


# ===========================================================================
# AD-9 — status stays REGISTRY-LEVEL (13-key spine unchanged)
# ===========================================================================


def test_status_remains_registry_level_spine_unchanged() -> None:
    """AD-9: STATUS_PARTIAL is a registry constant; the 13-key InvestigationState spine is unchanged."""
    assert STATUS_PARTIAL == "partial"
    assert len(InvestigationState.__annotations__) == 13  # spine UNCHANGED
    assert "status" not in InvestigationState.__annotations__  # NOT a spine key
    assert "partial" not in InvestigationState.__annotations__  # NOT a spine key


# ===========================================================================
# Read-only (AC9 / §3.8 / AD-3) — the guard adds NO write/exec/patch verb
# ===========================================================================


def test_guard_adds_no_write_or_exec_path() -> None:
    """The 5-2 guard + wiring add NO write/exec/patch verb (gate #1 AST axis — read-only strip)."""
    forbidden = (_names(INVESTIGATIONS_SRC) | _names(DISPATCH_SRC)) & {
        "subprocess",
        "kubectl",
        "patch",
        "delete",
        "scale",
        "rollback",
        "exec",
    }
    assert not forbidden, f"5-2 added a write/remediation path (AD-3 violation): {forbidden}"


def test_running_still_non_terminal_under_partial_addition() -> None:
    """Adding ``partial`` to ``_TERMINAL`` does NOT make ``running`` terminal (resume source intact)."""
    store = InvestigationStore()
    store.register_running("inv-running", TRIGGER_DICT)
    record = store.get("inv-running")
    assert record is not None
    assert record.status == STATUS_RUNNING
    assert not record.is_terminal  # running stays non-terminal (the resume scan still finds it)
    assert store.non_terminal() == [record]
