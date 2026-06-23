"""FastAPI ingest router — 3 trigger endpoints → normalizer → grouping → 202 + investigation_id (FR-1 / FR-2).

Endpoints (exact paths, spec §3.4 table / epic line 229):
  - POST /api/alerts/prometheus  → normalize_prometheus  (source = prometheus_alertmanager)
  - POST /api/alerts/grafana      → normalize_grafana     (source = grafana_alerting_loki)
  - POST /api/events/kubernetes   → normalize_kubernetes   (source = kubernetes_event)

Flow (Story 1-2, FR-2 / AD-10): parse request → call the normalizer service (Story
1-1, validates the raw payload into a typed `IncidentTrigger`, rejecting on missing /
unknown-canonical / invalid field with the `{error, code, detail}` 422 envelope) →
call the grouping service (Story 1-2, H3 1-trigger-1-investigation, idempotent on
`trigger_id`, sets `incident_id = investigation_id`) → return `202 Accepted +
{investigation_id}`.

AD-1 one-way: this router imports ONLY `services` + `models` — it MUST NOT import
`graph` / `adapters` / `tools` (enforced by gate #2 import-linter). Router is thin:
it never echoes the `IncidentTrigger` (that was Story 1-1's 200; the grouping layer
upgrades it to 202 + investigation_id).

Scope (locked 1-2 vs 1-4 vs 3-5): the handler returns 202 immediately — it does NOT
await the graph, run a background worker, expose a read-store, or resume a checkpoint
(those are Stories 1-4 / 3-5). Non-blocking is an async CONTRACT here, not an async
mechanism.

Each endpoint declares a Pydantic request schema (an open envelope — webhooks carry
many source-specific fields). The canonical-contract validation lives in
`IncidentTrigger` (AD-9 single source); the source is decided by the endpoint path,
NOT trusted from the body.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from services.grouping import group
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


class InvestigationAccepted(BaseModel):
    """`202 Accepted` response body — the async investigation handle (FR-2 / AD-10).

    `investigation_id` is the handle clients poll the read-store by (Story 1-4). The
    handler returns 202 immediately and does NOT block on the investigation running.
    """

    investigation_id: str


@router.post(
    "/api/alerts/prometheus",
    response_model=InvestigationAccepted,
    status_code=202,
)
def ingest_prometheus(payload: PrometheusAlertPayload) -> InvestigationAccepted:
    """Normalize a Prometheus alert → group (idempotent) → 202 + investigation_id."""
    trigger = normalize_prometheus(payload.as_payload())
    return InvestigationAccepted(investigation_id=group(trigger))


@router.post(
    "/api/alerts/grafana",
    response_model=InvestigationAccepted,
    status_code=202,
)
def ingest_grafana(payload: GrafanaAlertPayload) -> InvestigationAccepted:
    """Normalize a Grafana (Loki) alert → group (idempotent) → 202 + investigation_id."""
    trigger = normalize_grafana(payload.as_payload())
    return InvestigationAccepted(investigation_id=group(trigger))


@router.post(
    "/api/events/kubernetes",
    response_model=InvestigationAccepted,
    status_code=202,
)
def ingest_kubernetes(payload: KubernetesEventPayload) -> InvestigationAccepted:
    """Normalize a Kubernetes Event → group (idempotent) → 202 + investigation_id."""
    trigger = normalize_kubernetes(payload.as_payload())
    return InvestigationAccepted(investigation_id=group(trigger))
