"""IncidentTrigger contract model — 18 fields spec §3.4 (AD-9 port boundary).

Pydantic v2 model living at the port (api-gateway validate-on-ingress). The
canonical field vocabulary lives in `ci.contract_schema` (gate #5 single source
of truth); this module implements the runtime contract that validates against
it. Consumer wiring (routers ingest) is Story 1-1, NOT here.

Spec §3.4 = exactly 18 fields; row 18 = `raw_payload_ref` (ref-variant,
optional, None POC). `incident_id` is the optional H3 grouping add-on (FR-2 /
DEC-1), not a §3.4 field.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict


class TriggerSource(StrEnum):
    """Normalized trigger source — spec §3.4 (3 ingest endpoints)."""

    PROMETHEUS_ALERTMANAGER = "prometheus_alertmanager"
    GRAFANA_ALERTING_LOKI = "grafana_alerting_loki"
    KUBERNETES_EVENT = "kubernetes_event"


class Severity(StrEnum):
    """Normalized severity — spec §3.4."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class SignalType(StrEnum):
    """Signal type guiding investigation direction — spec §3.4."""

    METRIC = "metric"
    LOG = "log"
    KUBERNETES_EVENT = "kubernetes_event"


class IncidentTrigger(BaseModel):
    """Normalized incident trigger — 18 fields spec §3.4 + optional incident_id (H3).

    Validated on ingress at the api-gateway port (AD-9). `extra="forbid"` rejects
    invented fields at runtime (defense-in-depth alongside CI gate #5, which
    guards source-level drift).
    """

    model_config = ConfigDict(extra="forbid")

    # 1
    trigger_id: str
    """Unique trigger instance id (fingerprint/UID) — trace/dedupe."""

    # 2
    source: TriggerSource
    """Normalized trigger source (§3.4 table)."""

    # 3
    signal_type: SignalType
    """Signal class: metric / log / kubernetes_event — picks investigation lane."""

    # 4
    canonical_trigger: str
    """Domain-normalized trigger name, PascalCase (e.g. DependencyTimeout)."""

    # 5
    alert_name: str
    """Original/near-source alert or event name."""

    # 6
    severity: Severity
    """Normalized severity: info / warning / critical."""

    # 7
    title: str
    """Short readable title (from summary/reason)."""

    # 8
    description: str
    """Longer description (annotation/message/note)."""

    # 9
    service: str
    """Primary service the trigger attaches to (label service/app)."""

    # 10
    affected_services: list[str]
    """Services directly affected — topology/RCA seed."""

    # 11
    symptom: str
    """Observed symptom expression (usually title or message)."""

    # 12
    namespace: str
    """Kubernetes namespace/tenant scope (default `demo`)."""

    # 13
    started_at: str
    """Trigger start/firing/event time — ISO-8601 UTC (incident window)."""

    # 14
    ends_at: str | None = None
    """Resolved/end time ISO-8601 UTC; None while still firing or unknown."""

    # 15
    labels: dict[str, str]
    """Normalized labels dict (service, namespace, severity, scenario, ...)."""

    # 16
    annotations: dict[str, str]
    """Descriptive metadata (summary/description from source)."""

    # 17
    raw_payload: dict[str, Any]
    """Original received payload, stored inline for debug/extra context (active POC)."""

    # 18 — §3.4 row 18 (ref-variant). None/deferred in POC; prod sets ref when
    # the original payload is too large/sensitive to keep inline.
    raw_payload_ref: str | None = None
    """Reference to raw payload if stored out-of-band (blob/object store). None POC."""

    # H3 grouping add-on (optional). NOT a §3.4 field (FR-2 / DEC-1).
    incident_id: str | None = None
    """Optional incident grouping id (H3 1-trigger-1-investigation POC; H2 grouping = prod)."""
