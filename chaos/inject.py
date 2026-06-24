"""chaos/inject — the DETERMINISTIC symptom injector (Story 7.3 AC1).

``inject(scenario_key)`` returns the exact **trigger-source payload** the
corresponding 7.2 trigger source carries to ingest — i.e. what Prometheus
Alertmanager / Grafana Alerting POST to ``/api/alerts/{prometheus,grafana}``, and
what the kubernetes event-watcher POSTs to ``/api/events/kubernetes``. Tagging
``labels.scenario`` with the §3.7 snake_case key is the ROBUST canonical-resolution
path (``services.normalize._resolve_canonical`` checks ``labels.scenario`` FIRST,
before the alert/event identifier).

The in-process proof surface (``tests/test_chaos_inject.py``): for each of the 11
scenarios, ``normalize_*(inject(k))`` yields the correct §3.7 canonical — proving
the chaos→symptom→trigger→canonical mapping deterministically, with NO live
cluster (this dev env has none). This is the AC1 deliverable: chaos creates the
fault (the payload IS the faulted symptom the source would carry) → the 7.2 stack
detects it → the correct incident fires.

DETERMINISTIC (AD-12): every value is a literal string — no clock, no random, no
IO, no datetime, no uuid, no ``hash()``-on-strings, no set-iteration order. The
fixed timestamp / fingerprint are module constants. ``inject(k) == inject(k)``
byte-identically, across ``PYTHONHASHSEED`` (the payload is a dict whose iteration
order is insertion order, not hash order).

Import-pure: stdlib + :mod:`chaos.scenarios` ONLY.
"""

from __future__ import annotations

from typing import Any

from chaos.scenarios import BENCHMARK_SCENARIOS, ScenarioSpec

#: Fixed incident window for every injected payload (deterministic — AD-12: no
#: wall-clock). Same ISO-8601 shape the 7.2 trigger-source fixtures + the 1.1
#: normalizer validate; a constant, not ``datetime.now()``.
_FIXED_STARTS_AT = "2026-06-24T10:00:00Z"
_FIXED_ENDS_AT = "2026-06-24T10:05:00Z"

#: Index the 11 specs by their §3.7 snake_case key (deterministic dict — insertion order).
_SCENARIOS: dict[str, ScenarioSpec] = {spec.name: spec for spec in BENCHMARK_SCENARIOS}


class UnknownScenarioError(KeyError):
    """Raised when ``inject`` is asked for a scenario key outside the §3.7 eleven."""


def _alert_payload(spec: ScenarioSpec) -> dict[str, Any]:
    """Prometheus Alertmanager / Grafana Alerting webhook body (the trigger payload).

    ``labels.scenario`` (robust path) + ``labels.alertname`` (1-1 map) both resolve
    to ``canonical_trigger`` — they agree by construction (ScenarioSpec derives both
    from §3.7), so the normalizer's anti-collapse check never trips.
    """
    return {
        "fingerprint": f"chaos-{spec.fingerprint_suffix}",
        "startsAt": _FIXED_STARTS_AT,
        "endsAt": _FIXED_ENDS_AT,
        "labels": {
            "alertname": spec.alert_name,
            "service": spec.service,
            "severity": spec.severity,
            "scenario": spec.name,
            "namespace": "demo",
        },
        "annotations": {
            "summary": spec.summary,
            "description": spec.description,
        },
    }


def _event_payload(spec: ScenarioSpec) -> dict[str, Any]:
    """Kubernetes Event body (the shape the 7.2 event-watcher forwards to ingest)."""
    return {
        "metadata": {"uid": f"chaos-{spec.fingerprint_suffix}", "namespace": "demo"},
        "reason": spec.alert_name,
        "message": spec.description,
        "type": "Warning" if spec.severity != "info" else "Normal",
        "lastTimestamp": _FIXED_STARTS_AT,
        "involvedObject": {"name": spec.service, "namespace": "demo"},
        "labels": {
            "scenario": spec.name,
            "service": spec.service,
        },
    }


def inject(scenario: str) -> dict[str, Any]:
    """Return the deterministic trigger-source payload for one §3.7 scenario.

    A prometheus/grafana scenario yields the alert webhook body; a kubernetes
    scenario yields the Event body. Both are validated by the matching
    ``services.normalize`` function in the in-process test.
    """
    spec = _SCENARIOS.get(scenario)
    if spec is None:
        raise UnknownScenarioError(scenario)
    return _event_payload(spec) if spec.is_kubernetes else _alert_payload(spec)


def inject_all() -> list[dict[str, Any]]:
    """Return the 11 deterministic trigger-source payloads in §3.7 table order."""
    return [inject(spec.name) for spec in BENCHMARK_SCENARIOS]


__all__ = ["UnknownScenarioError", "inject", "inject_all"]
