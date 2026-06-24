"""Story 7.2 — the kubernetes_event trigger source: the tested, agent-free core.

Exercises ``observability.event_watcher`` IN-PROCESS (no cluster needed — this dev env has
no local K8s). Asserts:
  - ``event_to_ingest_payload`` is PURE + reproducible (same event -> same payload);
  - a representative K8s event round-trips through the Story-1.1 normalizer to a VALID
    ``IncidentTrigger`` (source=kubernetes_event) — i.e. the trigger source produces a
    valid 1.1 envelope (Story 7.2 LOCK §3). The §3.7 surfaces are covered: BackOff ->
    CrashLoopBackOff, OOMKilled -> OOMKilled;
  - ``forward_events`` POSTs each event to the kubernetes ingest endpoint, counts 2xx as
    forwarded / non-2xx as skipped, and NEVER raises (a raising poster is swallowed).
"""

from __future__ import annotations

from models import IncidentTrigger
from observability.event_watcher import (
    KUBERNETES_INGEST_PATH,
    ForwardStats,
    event_to_ingest_payload,
    forward_events,
)
from services.normalize import normalize_kubernetes

_BASE_URL = "http://rca-backend.rca.svc.cluster.local:8000"


def _crashloop_event() -> dict[str, object]:
    return {
        "metadata": {"uid": "evt-crashloop-1"},
        "reason": "BackOff",
        "message": "Back-off restarting failed container order in demo/order-abc",
        "type": "Warning",
        "lastTimestamp": "2026-06-24T10:00:00Z",
        "involvedObject": {"name": "order"},
    }


def _oom_event() -> dict[str, object]:
    return {
        "metadata": {"uid": "evt-oom-1"},
        "reason": "OOMKilled",
        "message": "container payment OOMKilled — memory limit exceeded",
        "type": "Warning",
        "lastTimestamp": "2026-06-24T10:05:00Z",
        "involvedObject": {"name": "payment"},
    }


def test_event_to_ingest_payload_is_pure_and_reproducible() -> None:
    """The transform is pure: the same event yields the byte-identical payload (run twice)."""
    first = event_to_ingest_payload(_crashloop_event())
    second = event_to_ingest_payload(_crashloop_event())
    assert first == second


def test_event_to_ingest_payload_seeds_service_from_involved_object() -> None:
    """labels.service is seeded from involvedObject.name so the normalizer resolves service."""
    payload = event_to_ingest_payload(_crashloop_event())
    labels = payload["labels"]
    assert isinstance(labels, dict)
    assert labels["service"] == "order"


def test_crashloopbackoff_event_round_trips_to_valid_incident_trigger() -> None:
    """BackOff event -> payload -> normalize_kubernetes -> valid IncidentTrigger (§3.7 CrashLoopBackOff)."""
    payload = event_to_ingest_payload(_crashloop_event())
    trigger = normalize_kubernetes(payload)
    assert isinstance(trigger, IncidentTrigger)
    assert trigger.source.value == "kubernetes_event"
    assert trigger.canonical_trigger == "CrashLoopBackOff"
    assert trigger.service == "order"
    assert trigger.severity.value == "warning"


def test_oom_event_maps_to_oomkilled_canonical() -> None:
    """OOMKilled event -> canonical OOMKilled (§3.7)."""
    payload = event_to_ingest_payload(_oom_event())
    trigger = normalize_kubernetes(payload)
    assert trigger.canonical_trigger == "OOMKilled"
    assert trigger.service == "payment"


def test_forward_events_targets_kubernetes_ingest_endpoint() -> None:
    """forward_events POSTs to {base}/api/events/kubernetes (the Story-1.1 kubernetes endpoint)."""
    seen: list[str] = []

    def post(url: str, *, json: object) -> int:
        seen.append(url)
        return 202

    forward_events([_crashloop_event()], ingest_base_url=_BASE_URL, post=post)
    assert len(seen) == 1
    assert seen[0] == _BASE_URL + KUBERNETES_INGEST_PATH


def test_forward_events_forwards_each_event_and_never_raises() -> None:
    """A 2xx POST is forwarded; a raising poster is swallowed (never-raise); a non-2xx is skipped."""

    def post(url: str, *, json: object) -> int:
        # the 2nd event's poster raises -> must be swallowed, not fatal
        if json is not None and isinstance(json, dict) and json.get("reason") == "OOMKilled":
            raise RuntimeError("simulated transport failure")
        return 202

    stats = forward_events(
        [_crashloop_event(), _oom_event(), _crashloop_event()],
        ingest_base_url=_BASE_URL,
        post=post,
    )
    assert isinstance(stats, ForwardStats)
    assert stats.forwarded == 2  # two BackOff events -> 202
    assert stats.skipped == 1  # the OOMKilled event raised -> skipped


def test_forward_events_counts_non_2xx_as_skipped() -> None:
    """A non-2xx status (e.g. ingest 422 rejecting the envelope) counts as skipped, not forwarded."""

    def post(url: str, *, json: object) -> int:
        return 422

    stats = forward_events([_crashloop_event()], ingest_base_url=_BASE_URL, post=post)
    assert stats.forwarded == 0
    assert stats.skipped == 1


def test_forward_events_handles_empty_event_stream() -> None:
    """An empty event stream forwards/skips nothing."""
    calls: list[int] = []

    def post(url: str, *, json: object) -> int:
        calls.append(1)
        return 202

    stats = forward_events([], ingest_base_url=_BASE_URL, post=post)
    assert calls == []
    assert stats == ForwardStats(forwarded=0, skipped=0)
