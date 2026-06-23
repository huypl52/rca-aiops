"""Trigger normalization service — raw payload → IncidentTrigger (FR-1, AD-9).

Lives in the services layer (AD-1 one-way: routers → services → models). REUSES
`models.IncidentTrigger` (18-field §3.4, Story 0-2 commit 7592e4c) — does NOT
redefine the model or its enums.

AD-9 validate-on-ingress: the normalizer is the api-gateway port boundary. It:
  1. extracts required fields from the source-specific raw payload and REJECTS
     on missing (raises a domain exception BEFORE constructing IncidentTrigger —
     no guess, no partial/bán-phần object);
  2. derives `canonical_trigger` from the spec §3.7 benchmark vocabulary (11
     terms) — no collapse of two distinct faults into one canonical (A3), and
     no invention of a canonical outside the vocabulary;
  3. constructs `IncidentTrigger(**fields)` — the model is the single source of
     validation (enum / type / `extra="forbid"`). `raw_payload` is stored inline
     (AD-9 #5); `raw_payload_ref` is None (§3.4 row 18, POC).

Source mapping (spec §3.4 table / epic line 229 + §3.7 line 783):
  - prometheus → normalize_prometheus  (source = prometheus_alertmanager, metric)
  - grafana    → normalize_grafana     (source = grafana_alerting_loki,  log)
  - kubernetes → normalize_kubernetes   (source = kubernetes_event,      kubernetes_event)
"""

from __future__ import annotations

from typing import Any

from models import IncidentTrigger, Severity, SignalType, TriggerSource

# ---------------------------------------------------------------------------
# canonical_trigger vocabulary — DERIVED from spec §3.7 (11 benchmark scenarios).
# NOT invented. A trigger's canonical_trigger MUST belong to this set; a payload
# that does not map to any of these is rejected (unknown_canonical_trigger) — we
# never collapse into a near-canonical and never invent a new one (A3).
# ---------------------------------------------------------------------------
BENCHMARK_CANONICAL_TRIGGERS: frozenset[str] = frozenset(
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

# scenario label (§3.7 left-most column) → canonical_trigger. Exact §3.7 mapping.
_SCENARIO_TO_CANONICAL: dict[str, str] = {
    "dependency_timeout": "DependencyTimeout",
    "payment_failure": "PaymentFailureHigh",
    "latency_spike": "DownstreamLatencyHigh",
    "disk_pressure": "NodeDiskPressure",
    "memory_leak": "MemoryUsageHigh",
    "inventory_reserve_failure": "InventoryReserveFailureHigh",
    "dns_failure": "DNSFailureLogSpike",
    "certificate_expired": "CertificateErrorDetected",
    "crashloop": "CrashLoopBackOff",
    "oom": "OOMKilled",
    "bad_deployment_config": "DeploymentUnavailable",
}

# alert/event identifier (alertname / K8s reason) → canonical_trigger, for the
# common case where the identifier already equals the canonical or maps 1-1.
# All values are §3.7 terms (bounded, no invention).
_ALERT_TO_CANONICAL: dict[str, str] = {
    # prometheus alertname often equals canonical
    "DependencyTimeout": "DependencyTimeout",
    "PaymentFailureHigh": "PaymentFailureHigh",
    "DownstreamLatencyHigh": "DownstreamLatencyHigh",
    "NodeDiskPressure": "NodeDiskPressure",
    "MemoryUsageHigh": "MemoryUsageHigh",
    "InventoryReserveFailureHigh": "InventoryReserveFailureHigh",
    # grafana log-pattern alertname
    "DNSFailureLogSpike": "DNSFailureLogSpike",
    "CertificateErrorDetected": "CertificateErrorDetected",
    # kubernetes event reason → canonical
    "BackOff": "CrashLoopBackOff",
    "OOMKilled": "OOMKilled",
    "DeploymentReplicasNotUpdated": "DeploymentUnavailable",
}

# severity normalization — spec §3.4 domain {info, warning, critical}.
# Recognized shorthands only ("warn"→warning). "none"/unknown are NOT guessed
# down to INFO: they pass through unchanged so Pydantic rejects them via the
# Severity enum (validate-on-ingress, no silent downgrade).
_SEVERITY_MAP: dict[str, Severity] = {
    "critical": Severity.CRITICAL,
    "warning": Severity.WARNING,
    "warn": Severity.WARNING,
    "info": Severity.INFO,
}


# ---------------------------------------------------------------------------
# Domain exceptions — raised by the normalizer, mapped to the error envelope
# {error, code, detail} by the FastAPI global handler (routers/app.py).
# ---------------------------------------------------------------------------


class NormalizeError(Exception):
    """Base domain error for trigger normalization."""

    code: str = "normalize_rejected"

    def __init__(self, detail: str, *, code: str | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        if code is not None:
            self.code = code


class MissingFieldError(NormalizeError):
    """A required field is missing from the raw payload — reject, do NOT guess."""

    code = "missing_required_field"


class UnknownCanonicalError(NormalizeError):
    """Raw payload maps to no §3.7 canonical — surface, do NOT invent/collapse."""

    code = "unknown_canonical_trigger"


# ---------------------------------------------------------------------------
# Extraction helpers. `_req_*` raise MissingFieldError (no guess, no partial);
# `_opt_*` return a defaulted value when the spec sanctions a default.
# ---------------------------------------------------------------------------


def _req_str(d: dict[str, Any], key: str, *, ctx: str) -> str:
    # Required string: present AND a real str. We do NOT coerce non-str via
    # str() — that would mask type errors (e.g. an int fingerprint colliding
    # with a string fingerprint) and bypass validate-on-ingress.
    if key not in d or d[key] is None:
        raise MissingFieldError(f"{ctx}: missing required field '{key}'")
    value = d[key]
    if not isinstance(value, str):
        raise MissingFieldError(
            f"{ctx}: field '{key}' must be a string, got {type(value).__name__}"
        )
    return value


def _opt_str(d: dict[str, Any], key: str) -> str | None:
    # Optional string: absent/None → None; present-but-non-str → reject (no coercion).
    value = d.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise MissingFieldError(
            f"field '{key}' must be a string when present, got {type(value).__name__}"
        )
    return value


def _opt_dict(d: dict[str, Any], key: str) -> dict[str, Any]:
    value = d.get(key)
    return {} if not isinstance(value, dict) else value


def _req_value(value: str | None, name: str) -> str:
    if value is None or not value.strip():
        raise MissingFieldError(f"missing required field '{name}'")
    return value


def _severity(value: str | None, *, k8s_type: str | None = None) -> Severity | str:
    """Normalize severity. Unknown values pass through to Pydantic validate-on-ingress.

    A present-but-unrecognized severity (e.g. "panic" ∉ §3.4 domain) is NOT a
    missing field — it is returned as-is so `IncidentTrigger` rejects it via
    enum validation (→ ValidationError → envelope `invalid_trigger_field`).
    """
    if value:
        key = value.strip().lower()
        if key in _SEVERITY_MAP:
            return _SEVERITY_MAP[key]
        return value  # defer to Pydantic validate-on-ingress (Severity enum)
    if k8s_type:
        # K8s event type → severity (spec-sanctioned normalization, not a guess).
        return Severity.WARNING if k8s_type.strip().lower() == "warning" else Severity.INFO
    raise MissingFieldError("missing required field 'severity'")


def _resolve_canonical(labels: dict[str, Any], alert_id: str | None) -> str:
    """Derive canonical_trigger from §3.7 vocabulary. No collapse, no invent."""
    scenario = labels.get("scenario")
    scenario_canon: str | None = (
        _SCENARIO_TO_CANONICAL[scenario]
        if isinstance(scenario, str) and scenario in _SCENARIO_TO_CANONICAL
        else None
    )
    alert_canon: str | None = (
        _ALERT_TO_CANONICAL[alert_id]
        if isinstance(alert_id, str) and alert_id in _ALERT_TO_CANONICAL
        else None
    )
    # A3 anti-collapse: if BOTH the scenario label AND the alert identifier map
    # to §3.7 canonicals but DISAGREE, the payload is self-contradictory. We
    # must NOT silently prefer one (that could mask a distinct fault). Reject.
    if scenario_canon and alert_canon and scenario_canon != alert_canon:
        raise UnknownCanonicalError(
            f"contradictory canonical sources: scenario={scenario!r}->{scenario_canon} "
            f"vs alert={alert_id!r}->{alert_canon}; refusing to collapse (A3)"
        )
    resolved = scenario_canon or alert_canon
    if resolved is not None:
        return resolved
    explicit = labels.get("canonical_trigger")
    if isinstance(explicit, str) and explicit in BENCHMARK_CANONICAL_TRIGGERS:
        return explicit
    raise UnknownCanonicalError(
        f"cannot derive canonical_trigger from scenario={scenario!r} alert={alert_id!r}; "
        f"not in §3.7 vocabulary (no collapse, no invent)"
    )


def _affected_services(labels: dict[str, Any], service: str) -> list[str]:
    raw = labels.get("affected_services")
    items: list[str]
    if isinstance(raw, list):
        items = [str(item).strip() for item in raw if str(item).strip()]
    elif isinstance(raw, str) and raw.strip():
        items = [part.strip() for part in raw.split(",") if part.strip()]
    else:
        items = []
    # dedupe while preserving order; empty → spec default [service].
    seen: set[str] = set()
    deduped: list[str] = []
    for s in items:
        if s not in seen:
            seen.add(s)
            deduped.append(s)
    return deduped or [service]


def _build_trigger(
    *,
    source: TriggerSource,
    signal_type: SignalType,
    trigger_id: str,
    alert_name: str,
    severity: Severity | str,
    service: str,
    started_at: str,
    title: str,
    description: str,
    labels: dict[str, Any],
    annotations: dict[str, Any],
    raw_payload: dict[str, Any],
    ends_at: str | None = None,
) -> IncidentTrigger:
    """Resolve canonical (§3.7) then construct IncidentTrigger — validate-on-ingress."""
    canonical_trigger = _resolve_canonical(labels, alert_name)
    # namespace: §3.4 default `demo` (spec-sanctioned). Use the label only when it
    # is a real non-empty string — never coerce a falsy/0 value into "demo".
    ns = labels.get("namespace")
    namespace = ns if isinstance(ns, str) and ns.strip() else "demo"
    fields: dict[str, Any] = {
        "trigger_id": trigger_id,
        "source": source,
        "signal_type": signal_type,
        "canonical_trigger": canonical_trigger,
        "alert_name": alert_name,
        "severity": severity,
        "title": title,
        "description": description,
        "service": service,
        "affected_services": _affected_services(labels, service),
        # symptom: observed symptom expression — spec §3.4 "usually title or message".
        "symptom": title,
        "namespace": namespace,
        "started_at": started_at,
        "ends_at": ends_at,
        # labels/annotations are NOT pre-coerced: IncidentTrigger's dict[str,str]
        # is the single validator (AD-9). A non-string value is rejected by the
        # model rather than silently stringified.
        "labels": labels,
        "annotations": annotations,
        # AD-9 #5: raw_payload inline (JSON-safe dict); raw_payload_ref None (§3.4 row 18 POC).
        "raw_payload": raw_payload,
        "raw_payload_ref": None,
    }
    return IncidentTrigger(**fields)


# ---------------------------------------------------------------------------
# Per-source normalizers. Each decides source/signal_type (the endpoint path
# selects which function — source is NOT trusted from the raw payload body).
# ---------------------------------------------------------------------------


def normalize_prometheus(raw: dict[str, Any]) -> IncidentTrigger:
    """Prometheus Alertmanager alert → IncidentTrigger (source=prometheus_alertmanager)."""
    labels = _opt_dict(raw, "labels")
    annotations = _opt_dict(raw, "annotations")
    return _build_trigger(
        source=TriggerSource.PROMETHEUS_ALERTMANAGER,
        signal_type=SignalType.METRIC,
        trigger_id=_req_str(raw, "fingerprint", ctx="prometheus alert"),
        alert_name=_req_str(labels, "alertname", ctx="prometheus labels"),
        severity=_severity(_opt_str(labels, "severity")),
        service=_req_str(labels, "service", ctx="prometheus labels"),
        started_at=_req_str(raw, "startsAt", ctx="prometheus alert"),
        ends_at=_opt_str(raw, "endsAt"),
        title=_req_str(annotations, "summary", ctx="prometheus annotations"),
        description=_req_str(annotations, "description", ctx="prometheus annotations"),
        labels=labels,
        annotations=annotations,
        raw_payload=raw,
    )


def normalize_grafana(raw: dict[str, Any]) -> IncidentTrigger:
    """Grafana Alerting (Loki LogQL) alert → IncidentTrigger (source=grafana_alerting_loki)."""
    labels = _opt_dict(raw, "labels")
    annotations = _opt_dict(raw, "annotations")
    return _build_trigger(
        source=TriggerSource.GRAFANA_ALERTING_LOKI,
        signal_type=SignalType.LOG,
        trigger_id=_req_str(raw, "fingerprint", ctx="grafana alert"),
        alert_name=_req_str(labels, "alertname", ctx="grafana labels"),
        severity=_severity(_opt_str(labels, "severity")),
        service=_req_str(labels, "service", ctx="grafana labels"),
        started_at=_req_str(raw, "startsAt", ctx="grafana alert"),
        ends_at=_opt_str(raw, "endsAt"),
        title=_req_str(annotations, "summary", ctx="grafana annotations"),
        description=_req_str(annotations, "description", ctx="grafana annotations"),
        labels=labels,
        annotations=annotations,
        raw_payload=raw,
    )


def normalize_kubernetes(raw: dict[str, Any]) -> IncidentTrigger:
    """Kubernetes Event → IncidentTrigger (source=kubernetes_event)."""
    metadata = _opt_dict(raw, "metadata")
    labels = _opt_dict(raw, "labels") or _opt_dict(metadata, "labels")
    annotations = _opt_dict(raw, "annotations") or _opt_dict(metadata, "annotations")
    involved = _opt_dict(raw, "involvedObject")
    service = _opt_str(labels, "service") or _opt_str(involved, "name")
    reason = _req_str(raw, "reason", ctx="kubernetes event")
    started_at = _opt_str(raw, "lastTimestamp") or _opt_str(raw, "eventTime")
    title = _opt_str(annotations, "summary") or reason
    return _build_trigger(
        source=TriggerSource.KUBERNETES_EVENT,
        signal_type=SignalType.KUBERNETES_EVENT,
        trigger_id=_req_str(metadata, "uid", ctx="kubernetes metadata"),
        alert_name=reason,
        severity=_severity(_opt_str(labels, "severity"), k8s_type=_opt_str(raw, "type")),
        service=_req_value(service, "service"),
        started_at=_req_value(started_at, "started_at"),
        title=title,
        description=_req_str(raw, "message", ctx="kubernetes event"),
        ends_at=None,
        labels=labels,
        annotations=annotations,
        raw_payload=raw,
    )


__all__ = [
    "BENCHMARK_CANONICAL_TRIGGERS",
    "MissingFieldError",
    "NormalizeError",
    "UnknownCanonicalError",
    "normalize_grafana",
    "normalize_kubernetes",
    "normalize_prometheus",
]
