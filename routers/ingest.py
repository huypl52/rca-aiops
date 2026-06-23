"""FastAPI ingest router — 3 trigger endpoints → normalizer → IncidentTrigger (FR-1).

Endpoints (exact paths, spec §3.4 table / epic line 229):
  - POST /api/alerts/prometheus  → normalize_prometheus  (source = prometheus_alertmanager)
  - POST /api/alerts/grafana      → normalize_grafana     (source = grafana_alerting_loki)
  - POST /api/events/kubernetes   → normalize_kubernetes   (source = kubernetes_event)

AD-1 one-way: this router imports ONLY `services` + `models` — it MUST NOT import
`graph` / `adapters` / `tools` (enforced by gate #2 import-linter). Router is thin:
parse request → call normalizer service → return the validated `IncidentTrigger`
(HTTP 200). It does NOT open an investigation, return 202+investigation_id, group,
or dispatch (those are Stories 1.2 / 1.4).

Each endpoint declares a Pydantic request schema (an open envelope — webhooks carry
many source-specific fields) and returns the typed `IncidentTrigger` (never a raw
dict). The canonical-contract validation lives in `IncidentTrigger` (AD-9 single
source); the source is decided by the endpoint path, NOT trusted from the body.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from models import IncidentTrigger
from services.normalize import (
    normalize_grafana,
    normalize_kubernetes,
    normalize_prometheus,
)

router = APIRouter()


class TriggerEnvelope(BaseModel):
    """Open source-specific webhook envelope (extras kept).

    Webhooks (Alertmanager / Grafana / K8s event) carry many loose fields. We
    model the request as a declared Pydantic schema with `extra="allow"` so the
    full payload round-trips into the normalizer; the canonical IncidentTrigger
    is the single source of contract validation (AD-9).
    """

    model_config = ConfigDict(extra="allow")

    def as_payload(self) -> dict[str, Any]:
        """Full payload dict (incl. extras) handed to the normalizer."""
        return self.model_dump()


class PrometheusAlertPayload(TriggerEnvelope):
    """Raw Prometheus Alertmanager alert payload."""


class GrafanaAlertPayload(TriggerEnvelope):
    """Raw Grafana Alerting (Loki LogQL) alert payload."""


class KubernetesEventPayload(TriggerEnvelope):
    """Raw Kubernetes Event payload."""


@router.post("/api/alerts/prometheus", response_model=IncidentTrigger)
def ingest_prometheus(payload: PrometheusAlertPayload) -> IncidentTrigger:
    """Normalize a Prometheus Alertmanager alert → IncidentTrigger."""
    return normalize_prometheus(payload.as_payload())


@router.post("/api/alerts/grafana", response_model=IncidentTrigger)
def ingest_grafana(payload: GrafanaAlertPayload) -> IncidentTrigger:
    """Normalize a Grafana Alerting (Loki) alert → IncidentTrigger."""
    return normalize_grafana(payload.as_payload())


@router.post("/api/events/kubernetes", response_model=IncidentTrigger)
def ingest_kubernetes(payload: KubernetesEventPayload) -> IncidentTrigger:
    """Normalize a Kubernetes Event → IncidentTrigger."""
    return normalize_kubernetes(payload.as_payload())
