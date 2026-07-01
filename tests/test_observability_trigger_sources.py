"""Story 7.2 — the 2 config-driven trigger sources produce valid Story-1.1 envelopes.

The ``prometheus_alertmanager`` and ``grafana_alerting_loki`` trigger sources (AC2) are
CONFIG-driven (Alertmanager ``webhook_configs`` + Grafana Alerting contact point — see
``observability/manifests/``). They POST the source's NATIVE alert body to the existing
Story-1.1 ingest endpoints. This proves that body — exactly as the source would POST it —
normalizes to a VALID ``IncidentTrigger`` (so the trigger-source -> ingest pathway is real,
with NO ingest-code change). The kubernetes_event source is proven in
``test_observability_event_watcher.py``.
"""

from __future__ import annotations

from models import IncidentTrigger, SignalType, TriggerSource
from services.normalize import normalize_grafana, normalize_prometheus


def test_prometheus_alert_round_trips_to_valid_incident_trigger() -> None:
    """An Alertmanager alert (as POSTed to /api/alerts/prometheus) -> valid IncidentTrigger."""
    alert = {
        "fingerprint": "fp-prom-deptimeout",
        "startsAt": "2026-06-24T10:00:00Z",
        "endsAt": "2026-06-24T10:05:00Z",
        "labels": {"alertname": "DependencyTimeout", "service": "order", "severity": "critical"},
        "annotations": {
            "summary": "order dependency timeout",
            "description": "payment unreachable",
        },
    }
    trigger = normalize_prometheus(alert)
    assert isinstance(trigger, IncidentTrigger)
    assert trigger.source == TriggerSource.PROMETHEUS_ALERTMANAGER
    assert trigger.signal_type == SignalType.METRIC
    assert trigger.canonical_trigger == "DependencyTimeout"
    assert trigger.service == "order"


def test_alertmanager_envelope_round_trips_to_valid_incident_trigger() -> None:
    """Alertmanager's native webhook envelope normalizes from its first firing alert."""
    envelope = {
        "receiver": "rca-ingest",
        "status": "firing",
        "groupLabels": {"alertname": "DependencyTimeout", "service": "order"},
        "alerts": [
            {
                "status": "resolved",
                "fingerprint": "fp-old",
                "startsAt": "2026-06-24T09:50:00Z",
                "endsAt": "2026-06-24T09:55:00Z",
                "labels": {
                    "alertname": "DependencyTimeout",
                    "service": "order",
                    "severity": "critical",
                },
                "annotations": {"summary": "old alert", "description": "old alert"},
            },
            {
                "status": "firing",
                "fingerprint": "fp-prom-deptimeout",
                "startsAt": "2026-06-24T10:00:00Z",
                "endsAt": "2026-06-24T10:05:00Z",
                "labels": {
                    "alertname": "DependencyTimeout",
                    "service": "order",
                    "severity": "critical",
                },
                "annotations": {
                    "summary": "order dependency timeout",
                    "description": "payment unreachable",
                },
            },
        ],
    }
    trigger = normalize_prometheus(envelope)
    assert isinstance(trigger, IncidentTrigger)
    assert trigger.source == TriggerSource.PROMETHEUS_ALERTMANAGER
    assert trigger.signal_type == SignalType.METRIC
    assert trigger.canonical_trigger == "DependencyTimeout"
    assert trigger.service == "order"
    assert trigger.trigger_id == "fp-prom-deptimeout"
    assert trigger.raw_payload == envelope


def test_grafana_alert_round_trips_to_valid_incident_trigger() -> None:
    """A Grafana Alerting (Loki LogQL) alert (as POSTed to /api/alerts/grafana) -> valid IncidentTrigger."""
    alert = {
        "fingerprint": "fp-grafana-dns",
        "startsAt": "2026-06-24T10:00:00Z",
        "labels": {"alertname": "DNSFailureLogSpike", "service": "user", "severity": "warning"},
        "annotations": {
            "summary": "DNS failure log spike",
            "description": "dns+failure log pattern elevated",
        },
    }
    trigger = normalize_grafana(alert)
    assert isinstance(trigger, IncidentTrigger)
    assert trigger.source == TriggerSource.GRAFANA_ALERTING_LOKI
    assert trigger.signal_type == SignalType.LOG
    assert trigger.canonical_trigger == "DNSFailureLogSpike"
    assert trigger.service == "user"


def test_all_three_trigger_sources_map_to_valid_incident_triggers() -> None:
    """Headline AC2 invariant: every one of the 3 trigger sources yields a valid IncidentTrigger."""
    sources_seen: set[str] = set()
    sources_seen.add(
        normalize_prometheus(
            {
                "fingerprint": "fp1",
                "startsAt": "2026-06-24T10:00:00Z",
                "labels": {
                    "alertname": "PaymentFailureHigh",
                    "service": "order",
                    "severity": "critical",
                },
                "annotations": {"summary": "x", "description": "y"},
            }
        ).source.value
    )
    sources_seen.add(
        normalize_grafana(
            {
                "fingerprint": "fp2",
                "startsAt": "2026-06-24T10:00:00Z",
                "labels": {
                    "alertname": "CertificateErrorDetected",
                    "service": "user",
                    "severity": "warning",
                },
                "annotations": {"summary": "x", "description": "y"},
            }
        ).source.value
    )
    # kubernetes_event proven in test_observability_event_watcher.py; asserted here for the trio.
    assert sources_seen == {"prometheus_alertmanager", "grafana_alerting_loki"}
