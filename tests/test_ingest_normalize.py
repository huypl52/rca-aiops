"""Story 1-1 — ingest endpoints + normalize → IncidentTrigger (AC1-AC8).

Covers: 3 endpoints exact path + source mapping (AC1), normalize → reused
IncidentTrigger 18-field + enums (AC2), reject-on-missing no-guess/no-partial
(AC3), no-collapse canonical derived from §3.7 (AC4), raw_payload inline +
raw_payload_ref None (AC5), validate-on-ingress rejects bad enum/type (AC6),
gate #2 one-way routers→services→models (AC7), scope kept — echo IncidentTrigger
200, no 202/grouping/dispatch/state (AC8).
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from models import IncidentTrigger, Severity, SignalType, TriggerSource
from routers.app import create_app
from services.normalize import (
    BENCHMARK_CANONICAL_TRIGGERS,
    MissingFieldError,
    UnknownCanonicalError,
    normalize_grafana,
    normalize_kubernetes,
    normalize_prometheus,
)

# ---------------------------------------------------------------------------
# Fixtures — source-specific raw payloads (shaped like real webhooks).
# ---------------------------------------------------------------------------

PROM_DEP_TIMEOUT: dict[str, Any] = {
    "fingerprint": "fp-dep-timeout-001",
    "status": "firing",
    "labels": {
        "alertname": "DependencyTimeout",
        "severity": "critical",
        "service": "order-service",
        "namespace": "demo",
        "scenario": "dependency_timeout",
        "affected_services": "order-service,payment-service",
    },
    "annotations": {
        "summary": "order-service dependency timeout",
        "description": "Downstream dependency timeout firing on order-service",
    },
    "startsAt": "2026-06-24T10:00:00Z",
    "endsAt": "2026-06-24T10:05:00Z",
}

PROM_PAYMENT_FAILURE: dict[str, Any] = {
    "fingerprint": "fp-payment-002",
    "status": "firing",
    "labels": {
        "alertname": "PaymentFailureHigh",
        "severity": "critical",
        "service": "payment-service",
        "namespace": "demo",
        "scenario": "payment_failure",
    },
    "annotations": {
        "summary": "payment failure rate high",
        "description": "payment_failed_total above threshold",
    },
    "startsAt": "2026-06-24T10:00:00Z",
}

GRAFANA_DNS: dict[str, Any] = {
    "fingerprint": "fp-dns-001",
    "status": "firing",
    "labels": {
        "alertname": "DNSFailureLogSpike",
        "severity": "warning",
        "service": "user-service",
        "namespace": "demo",
        "scenario": "dns_failure",
    },
    "annotations": {"summary": "DNS failure log spike", "description": "DNS error logs surging"},
    "startsAt": "2026-06-24T10:00:00Z",
}

K8S_CRASHLOOP: dict[str, Any] = {
    "apiVersion": "events.k8s.io/v1",
    "kind": "Event",
    "metadata": {"uid": "evt-crashloop-001", "namespace": "demo"},
    "reason": "BackOff",
    "message": "Back-off restarting failed container payment",
    "type": "Warning",
    "involvedObject": {"kind": "Pod", "name": "payment-abc", "namespace": "demo"},
    "lastTimestamp": "2026-06-24T10:00:00Z",
    "labels": {"service": "payment-service", "scenario": "crashloop", "severity": "critical"},
}

@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


# ---------------------------------------------------------------------------
# AC1 + AC8 — 3 endpoints exact path, source decided by path, echo IncidentTrigger (200).
# ---------------------------------------------------------------------------


def test_prometheus_endpoint_normalizes_to_incident_trigger(client: TestClient) -> None:
    resp = client.post("/api/alerts/prometheus", json=PROM_DEP_TIMEOUT)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source"] == "prometheus_alertmanager"
    assert body["signal_type"] == "metric"


def test_grafana_endpoint_normalizes_to_incident_trigger(client: TestClient) -> None:
    resp = client.post("/api/alerts/grafana", json=GRAFANA_DNS)
    assert resp.status_code == 200, resp.text
    assert resp.json()["source"] == "grafana_alerting_loki"
    assert resp.json()["signal_type"] == "log"


def test_kubernetes_endpoint_normalizes_to_incident_trigger(client: TestClient) -> None:
    resp = client.post("/api/events/kubernetes", json=K8S_CRASHLOOP)
    assert resp.status_code == 200, resp.text
    assert resp.json()["source"] == "kubernetes_event"
    assert resp.json()["signal_type"] == "kubernetes_event"


def test_unknown_path_is_not_an_ingest_endpoint(client: TestClient) -> None:
    # Exactly 3 ingest endpoints exist (AC1) — no 4th path.
    resp = client.post("/api/alerts/unknown", json={})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# AC2 — normalize → reused IncidentTrigger (18 §3.4 fields + incident_id), enums correct.
# ---------------------------------------------------------------------------


def test_normalize_prometheus_yields_full_incident_trigger() -> None:
    trigger = normalize_prometheus(PROM_DEP_TIMEOUT)
    assert isinstance(trigger, IncidentTrigger)
    spec_fields = set(IncidentTrigger.model_fields.keys()) - {"incident_id"}
    assert len(spec_fields) == 18  # §3.4 = 18 (lesson D-1: count by spec table)
    assert trigger.source == TriggerSource.PROMETHEUS_ALERTMANAGER
    assert trigger.signal_type == SignalType.METRIC
    assert trigger.severity == Severity.CRITICAL
    assert trigger.canonical_trigger == "DependencyTimeout"
    assert trigger.service == "order-service"
    assert trigger.affected_services == ["order-service", "payment-service"]
    assert trigger.namespace == "demo"
    assert trigger.ends_at == "2026-06-24T10:05:00Z"
    assert trigger.incident_id is None


def test_namespace_defaults_to_demo_when_absent() -> None:
    raw = {**GRAFANA_DNS}
    raw["labels"] = {**raw["labels"]}
    raw["labels"].pop("namespace")
    trigger = normalize_grafana(raw)
    assert trigger.namespace == "demo"  # §3.4 default


# ---------------------------------------------------------------------------
# AC3 — reject-on-missing: raise BEFORE constructing IncidentTrigger (no guess/partial).
# ---------------------------------------------------------------------------


def test_normalize_raises_missing_field_before_constructing() -> None:
    raw = {**PROM_DEP_TIMEOUT}
    raw["labels"] = {**raw["labels"]}
    raw["labels"].pop("service")  # required field removed
    with pytest.raises(MissingFieldError, match="service"):
        normalize_prometheus(raw)


def test_missing_required_field_returns_422_envelope_no_200(client: TestClient) -> None:
    raw: dict[str, Any] = {**PROM_DEP_TIMEOUT}
    raw.pop("fingerprint", None)  # trigger_id source removed
    resp = client.post("/api/alerts/prometheus", json=raw)
    assert resp.status_code == 422
    body = resp.json()
    assert set(body.keys()) == {"error", "code", "detail"}
    assert body["code"] == "missing_required_field"
    assert "fingerprint" in body["detail"]


def test_kubernetes_missing_uid_rejects(client: TestClient) -> None:
    raw = {**K8S_CRASHLOOP, "metadata": {"namespace": "demo"}}  # no uid
    resp = client.post("/api/events/kubernetes", json=raw)
    assert resp.status_code == 422
    assert resp.json()["code"] == "missing_required_field"


# ---------------------------------------------------------------------------
# AC4 — no-collapse canonical (A3): 2 distinct faults → 2 distinct canonicals, both §3.7.
# ---------------------------------------------------------------------------


def test_two_distinct_faults_do_not_collapse_canonical() -> None:
    dep = normalize_prometheus(PROM_DEP_TIMEOUT)
    pay = normalize_prometheus(PROM_PAYMENT_FAILURE)
    assert dep.canonical_trigger != pay.canonical_trigger  # A3: no collapse
    assert dep.canonical_trigger in BENCHMARK_CANONICAL_TRIGGERS
    assert pay.canonical_trigger in BENCHMARK_CANONICAL_TRIGGERS
    assert dep.canonical_trigger == "DependencyTimeout"
    assert pay.canonical_trigger == "PaymentFailureHigh"


def test_unknown_canonical_is_rejected_not_invented(client: TestClient) -> None:
    raw = {
        "fingerprint": "fp-x",
        "labels": {"alertname": "MysteryAlert", "severity": "warning", "service": "svc"},
        "annotations": {"summary": "s", "description": "d"},
        "startsAt": "2026-06-24T10:00:00Z",
    }
    with pytest.raises(UnknownCanonicalError):
        normalize_prometheus(raw)
    resp = client.post("/api/alerts/prometheus", json=raw)
    assert resp.status_code == 422
    assert resp.json()["code"] == "unknown_canonical_trigger"


def test_benchmark_canonical_vocabulary_matches_spec_3_7() -> None:
    # The 11 §3.7 canonicals — DERIVED, not invented (no 12th term).
    assert BENCHMARK_CANONICAL_TRIGGERS == frozenset(
        {
            "DependencyTimeout",
            "PaymentFailureHigh",
            "DownstreamLatencyHigh",
            "NodeDiskPressure",
            "MemoryUsageHigh",
            "InventoryReserveFailureHigh",
            "DNSFailureLogSpike",
            "CertificateErrorDetected",
            "CrashLoopBackOff",
            "OOMKilled",
            "DeploymentUnavailable",
        }
    )


# ---------------------------------------------------------------------------
# AC5 — raw_payload inline (AD-9 #5) + raw_payload_ref None (§3.4 row 18).
# ---------------------------------------------------------------------------


def test_raw_payload_inline_and_ref_none() -> None:
    trigger = normalize_kubernetes(K8S_CRASHLOOP)
    assert trigger.raw_payload == K8S_CRASHLOOP  # inline, original preserved
    assert trigger.raw_payload_ref is None  # §3.4 row 18, POC


def test_raw_payload_is_json_safe() -> None:
    import json

    trigger = normalize_prometheus(PROM_DEP_TIMEOUT)
    # AD-9 rule 1: state-form must be plain JSON-safe.
    json.dumps(trigger.model_dump())


# ---------------------------------------------------------------------------
# AC6 — validate-on-ingress: bad enum/type rejected by Pydantic (model = single source).
# ---------------------------------------------------------------------------


def test_invalid_severity_rejected_by_pydantic() -> None:
    raw = {**PROM_DEP_TIMEOUT}
    raw["labels"] = {**raw["labels"], "severity": "panic"}  # ∉ {info,warning,critical}
    with pytest.raises(ValidationError):
        normalize_prometheus(raw)


def test_invalid_severity_returns_422_envelope(client: TestClient) -> None:
    raw = {**PROM_DEP_TIMEOUT}
    raw["labels"] = {**raw["labels"], "severity": "panic"}
    resp = client.post("/api/alerts/prometheus", json=raw)
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "invalid_trigger_field"
    assert set(body.keys()) == {"error", "code", "detail"}


# ---------------------------------------------------------------------------
# AC7 — gate #2 one-way: routers import only services+models (no graph/adapters/tools).
# Enforced structurally by import-linter; this test asserts the layering in code.
# ---------------------------------------------------------------------------


def test_routers_module_does_not_import_forbidden_layers() -> None:
    # gate #2 one-way (AD-1): routers may import only fastapi/pydantic/models/
    # services. Verified structurally via AST (import-linter is the real HARD-FAIL
    # gate; this test mirrors it so a regression is caught in the unit suite too).
    import ast

    import routers.app as app_mod
    import routers.ingest as ingest_mod

    forbidden_roots = {"graph", "adapters", "tools"}

    def imported_modules(source: str) -> set[str]:
        tree = ast.parse(source)
        roots: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    roots.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    roots.add(node.module.split(".")[0])
        return roots

    for module in (ingest_mod, app_mod):
        assert module.__file__ is not None
        with open(module.__file__) as fh:  # noqa: PTH123
            roots = imported_modules(fh.read())
        leaked = roots & forbidden_roots
        assert not leaked, f"{module.__name__} imports forbidden layer(s): {leaked}"


# ---------------------------------------------------------------------------
# Hardening follow-ups (code-review loop) — no-guess / no-collapse / envelope.
# ---------------------------------------------------------------------------


def test_source_is_decided_by_path_not_spoofable_from_body(client: TestClient) -> None:
    # AC1 / T4.5: the endpoint path fixes the source — a spoofed `source`/signal in
    # the body must be IGNORED (we never trust the raw body for source).
    raw = {**PROM_DEP_TIMEOUT, "source": "kubernetes_event", "signal_type": "log"}
    resp = client.post("/api/alerts/prometheus", json=raw)
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "prometheus_alertmanager"
    assert body["signal_type"] == "metric"


def test_contradictory_scenario_and_alert_rejected_not_collapsed() -> None:
    # A3: scenario says DependencyTimeout but alertname says PaymentFailureHigh —
    # a self-contradictory payload. Must NOT silently prefer one (collapse risk).
    raw = {
        "fingerprint": "fp-x",
        "labels": {
            "alertname": "PaymentFailureHigh",
            "severity": "critical",
            "service": "svc",
            "scenario": "dependency_timeout",
        },
        "annotations": {"summary": "s", "description": "d"},
        "startsAt": "2026-06-24T10:00:00Z",
    }
    with pytest.raises(UnknownCanonicalError, match="contradictory"):
        normalize_prometheus(raw)


def test_non_string_label_value_rejected_by_model(client: TestClient) -> None:
    # No str() coercion: a non-string label value must be rejected by the model
    # (validate-on-ingress), never silently stringified into "True"/"123".
    raw = {**PROM_DEP_TIMEOUT}
    raw["labels"] = {**raw["labels"], "replicas": True}
    resp = client.post("/api/alerts/prometheus", json=raw)
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "invalid_trigger_field"
    assert set(body.keys()) == {"error", "code", "detail"}


def test_non_string_required_field_rejected_not_coerced(client: TestClient) -> None:
    # fingerprint as int must NOT be coerced to "12345" (type-confusion / collision).
    raw = {**PROM_DEP_TIMEOUT, "fingerprint": 12345}
    resp = client.post("/api/alerts/prometheus", json=raw)
    assert resp.status_code == 422
    assert resp.json()["code"] == "missing_required_field"


def test_unknown_severity_passes_through_rejected_by_enum(client: TestClient) -> None:
    # "none"/"panic" are NOT silently downgraded to INFO — deferred to the enum.
    raw = {**PROM_DEP_TIMEOUT}
    raw["labels"] = {**raw["labels"], "severity": "none"}
    resp = client.post("/api/alerts/prometheus", json=raw)
    assert resp.status_code == 422
    assert resp.json()["code"] == "invalid_trigger_field"
