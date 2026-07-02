"""Demo MVP — read-only incident index (`GET /api/investigations`) + static UI mount.

Covers the additive read-only inbox surface:
  - empty list returns ``{"items": []}``.
  - populated list maps trigger-derived fields (defensive ``get`` → "" for missing keys).
  - deterministic newest-first order by ``started_at`` (ISO-8601 lexical), empty
    ``started_at`` last, ``investigation_id`` ascending tiebreak.
  - the existing per-investigation GET endpoint is untouched.
  - the optional ``/ui`` static mount exists when ``demo/ui`` is present (additive).

Read-only (AD-3): the index only projects stored trigger metadata; it never mutates,
never invents fields, and exposes no write/remediation verb.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from routers.app import create_app
from services.investigations import (
    STATUS_PARTIAL,
    STATUS_RUNNING,
    STATUS_SUCCESS,
    default_store,
    reset_store,
)

# A trigger carrying the full inbox-relevant vocabulary.
FULL_TRIGGER: dict[str, Any] = {
    "trigger_id": "tr-full-1",
    "source": "prometheus_alertmanager",
    "signal_type": "metric",
    "canonical_trigger": "DependencyTimeout",
    "alert_name": "DownstreamErrorHigh",
    "severity": "critical",
    "title": "payment dependency timing out",
    "service": "payment",
    "started_at": "2026-07-02T10:00:00Z",
}

# A minimal trigger (only required-ish fields) — exercises defensive ``get`` fallbacks
# for source / alert_name / severity / canonical_trigger / title / started_at.
SPARSE_TRIGGER: dict[str, Any] = {
    "trigger_id": "tr-sparse-1",
    "service": "order",
}


@pytest.fixture(autouse=True)
def _reset_default_store() -> Any:
    reset_store()
    yield
    reset_store()


def _client() -> TestClient:
    return TestClient(create_app())


def test_empty_list() -> None:
    resp = _client().get("/api/investigations")
    assert resp.status_code == 200
    assert resp.json() == {"items": []}


def test_list_field_mapping_from_full_trigger() -> None:
    store = default_store()
    store.register_running("inv-full", FULL_TRIGGER)

    items = _client().get("/api/investigations").json()["items"]
    assert len(items) == 1
    it = items[0]
    assert it == {
        "investigation_id": "inv-full",
        "status": STATUS_RUNNING,
        "source": "prometheus_alertmanager",
        "alert_name": "DownstreamErrorHigh",
        "severity": "critical",
        "service": "payment",
        "canonical_trigger": "DependencyTimeout",
        "title": "payment dependency timing out",
        "started_at": "2026-07-02T10:00:00Z",
    }


def test_list_handles_missing_trigger_fields_defensively() -> None:
    """Sparse trigger → missing keys degrade to "" (never raise, never invent)."""
    store = default_store()
    store.register_running("inv-sparse", SPARSE_TRIGGER)

    it = _client().get("/api/investigations").json()["items"][0]
    assert it["investigation_id"] == "inv-sparse"
    assert it["service"] == "order"
    assert it["source"] == ""
    assert it["alert_name"] == ""
    assert it["severity"] == ""
    assert it["canonical_trigger"] == ""
    assert it["title"] == ""
    assert it["started_at"] == ""


def test_list_newest_first_with_empty_started_at_last() -> None:
    """Deterministic order: started_at desc; empty started_at last; id asc tiebreak."""
    store = default_store()
    older = {**FULL_TRIGGER, "trigger_id": "t-old", "started_at": "2026-07-01T00:00:00Z"}
    newer = {**FULL_TRIGGER, "trigger_id": "t-new", "started_at": "2026-07-02T12:00:00Z"}
    # Two with identical started_at to exercise the id tiebreak (ascending).
    same_a = {**FULL_TRIGGER, "trigger_id": "t-same", "started_at": "2026-07-02T12:00:00Z"}
    no_time = {**FULL_TRIGGER, "trigger_id": "t-none"}
    del no_time["started_at"]
    for iid, trig in [
        ("inv-old", older),
        ("inv-new", newer),
        ("inv-same-z", same_a),
        ("inv-none", no_time),
    ]:
        store.register_running(iid, trig)

    ids = [i["investigation_id"] for i in _client().get("/api/investigations").json()["items"]]
    # newer (12:00) before older; among the two 12:00 rows id asc; empty started_at last.
    assert ids == ["inv-new", "inv-same-z", "inv-old", "inv-none"]


def test_index_does_not_expose_trigger_blob_or_report() -> None:
    """The narrow list model must not leak the raw trigger dict or report payload."""
    store = default_store()
    store.register_running(
        "inv-leak", {**FULL_TRIGGER, "labels": {"secret": "x"}, "raw_payload": {"k": "v"}}
    )
    store.set_terminal(
        "inv-leak", STATUS_SUCCESS, {"context": {}}, {"root_cause": "rc", "remediation": ["do-x"]}
    )

    body = _client().get("/api/investigations").json()["items"][0]
    assert "labels" not in body
    assert "raw_payload" not in body
    assert "trigger" not in body
    assert "report" not in body
    assert "state_snapshot" not in body


def test_detail_endpoint_unchanged_alongside_index() -> None:
    store = default_store()
    store.register_running("inv-detail", FULL_TRIGGER)
    store.set_terminal(
        "inv-detail",
        STATUS_PARTIAL,
        {"sufficiency": {"gap": "inconclusive"}},
        {"root_cause": None, "evidence_backing": [], "confidence": "low", "remediation": ["x"]},
    )
    client = _client()
    detail = client.get("/api/investigations/inv-detail").json()
    assert detail["status"] == STATUS_PARTIAL
    assert detail["report"]["remediation"] == []  # output-side guard intact
    assert detail["state_snapshot"]["sufficiency"]["gap"] == "inconclusive"


def test_detail_404_unaffected() -> None:
    resp = _client().get("/api/investigations/does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "investigation_not_found"


def test_static_ui_mount_served_when_present() -> None:
    """The /ui mount is additive and serves index.html from demo/ui (repo layout)."""
    ui_dir = Path(__file__).resolve().parent.parent / "demo" / "ui"
    if not ui_dir.is_dir():
        pytest.skip("demo/ui not present in this layout")
    client = _client()
    resp = client.get("/ui/")
    assert resp.status_code == 200
    assert "Alert-First Incident Console" in resp.text


def test_served_app_js_carries_c1_c2_polish() -> None:
    """C1/C2 are frontend-only; in a Python repo with no JS harness the strongest
    available check is a content assertion on the SHIPPED app.js. Guards against a
    revert to raw-JSON report fields (C1) or ungated "report is ready" narration (C2).

    Coarse by design: it asserts the behaviors exist in the served asset, not pixel
    rendering (no browser here). Skipped when demo/ui is absent.
    """
    ui_dir = Path(__file__).resolve().parent.parent / "demo" / "ui"
    if not ui_dir.is_dir():
        pytest.skip("demo/ui not present in this layout")
    src = _client().get("/ui/app.js").text

    # C1: report root cause/confidence render via shared unwrap helpers (no raw JSON
    # for these structured fields).
    assert "function formatCandidate" in src
    assert "rankedCandidates(r.root_cause)" in src
    assert "confidenceText(r.confidence)" in src

    # C2: success narration is gated on report presence — the no-report branch exists.
    assert "no RCA report was produced this run" in src


# ---------------------------------------------------------------------------
# F1 regression — detail header/meta must render from trigger truth, not from
# top-level state_snapshot keys the live runner never emits.
# ---------------------------------------------------------------------------


def test_detail_carries_trigger_summary_from_full_trigger() -> None:
    """The detail response includes a trigger-derived summary (additive field)."""
    store = default_store()
    store.register_running("inv-ts-full", FULL_TRIGGER)

    body = _client().get("/api/investigations/inv-ts-full").json()
    ts = body["trigger_summary"]
    assert ts["source"] == "prometheus_alertmanager"
    assert ts["alert_name"] == "DownstreamErrorHigh"
    assert ts["severity"] == "critical"
    assert ts["service"] == "payment"
    assert ts["canonical_trigger"] == "DependencyTimeout"
    assert ts["started_at"] == "2026-07-02T10:00:00Z"


def test_detail_recovers_header_meta_from_live_snapshot_shape() -> None:
    """F1: live state_snapshot only carries {context, next_action, evidence_count,
    tool_calls_count}. The header/meta must still render via trigger_summary, never
    degrading to the UUID / all-'—' cells."""
    store = default_store()
    trigger = {
        **FULL_TRIGGER,
        "namespace": "demo",
        "affected_services": ["order", "inventory"],
    }
    store.register_running("inv-live", trigger)
    # Overwrite the snapshot to the REAL live shape (no top-level trigger fields).
    live_snapshot = {
        "context": {
            "service": "order",
            "namespace": "demo",
            "labels": {"alertname": "DependencyTimeout", "severity": "critical"},
            "topology_seed": {"services": ["order"]},
        },
        "next_action": "context_built",
        "evidence_count": 0,
        "tool_calls_count": 0,
    }
    store.set_terminal("inv-live", STATUS_SUCCESS, live_snapshot, None)

    body = _client().get("/api/investigations/inv-live").json()
    # The snapshot itself has NO top-level header/meta keys (proves the bug precondition).
    for absent in ("alert_name", "canonical_trigger", "severity", "service", "started_at"):
        assert absent not in body["state_snapshot"]
    # trigger_summary still provides every field the UI header/meta needs.
    ts = body["trigger_summary"]
    assert ts["alert_name"] == "DownstreamErrorHigh"
    assert ts["canonical_trigger"] == "DependencyTimeout"
    assert ts["severity"] == "critical"
    assert ts["service"] == "payment"
    assert ts["namespace"] == "demo"
    assert ts["started_at"] == "2026-07-02T10:00:00Z"
    assert ts["affected_services"] == ["order", "inventory"]


def test_trigger_summary_safe_for_sparse_trigger() -> None:
    """A trigger missing most fields yields "" / [] (never raises, never invents)."""
    store = default_store()
    store.register_running("inv-sparse-ts", {"trigger_id": "t1", "service": "order"})

    ts = _client().get("/api/investigations/inv-sparse-ts").json()["trigger_summary"]
    assert ts["service"] == "order"
    assert ts["source"] == ""
    assert ts["alert_name"] == ""
    assert ts["affected_services"] == []
    assert ts["namespace"] == ""


# ---------------------------------------------------------------------------
# F2 regression — pin the rca_writer report contract the chat unwrap relies on.
# The JS answer() unwraps root_cause (list of {rank, hypothesis_id, citations}) and
# confidence ({ceiling_confidence, categorical}). If the producer shape drifts, this
# test fails so the UI unwrap is revisited (instead of silently printing [object Object]).
# ---------------------------------------------------------------------------


def test_rca_writer_report_shape_for_chat_unwrap() -> None:
    from graph.nodes.rca_writer import build_rca_writer
    from graph.state import InvestigationState

    node = build_rca_writer()
    state = cast(
        InvestigationState,
        {
            "hypotheses": [{"id": "H01", "priority": 1, "plan": {}, "status": "open"}],
            "evidence": [
                {
                    "source_name": "prometheus",
                    "source_type": "metrics",
                    "query": "up",
                    "summary": "checkout down",
                    "raw_excerpt": "checkout_up=0",
                    "supports": ["H01"],
                    "timestamp_range": {"start": "t1", "end": "t2"},
                }
            ],
            "sufficiency": {
                "floor_pass": True,
                "ceiling_confidence": 0.8,
                "categorical": "medium",
                "gap": "gap",
            },
        },
    )
    report = node(state)["report"]
    assert isinstance(report, dict)

    # root_cause: list of candidate dicts; the chat takes the rank-1 hypothesis_id.
    rc = report["root_cause"]
    assert isinstance(rc, list) and rc
    top = rc[0]
    assert isinstance(top, dict)
    assert isinstance(top["hypothesis_id"], str)
    assert isinstance(top["citations"], list)
    assert isinstance(top["rank"], int)

    # confidence: object with categorical (str) + ceiling_confidence (number).
    conf = report["confidence"]
    assert isinstance(conf, dict)
    assert isinstance(conf["categorical"], str)
    assert isinstance(conf["ceiling_confidence"], (int, float))
