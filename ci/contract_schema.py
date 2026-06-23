"""Canonical contract schema field-sets (CI gate #5, AD-13 #5 / AD-6).

SINGLE SOURCE OF TRUTH for the §3.4 / §3.6 contract field vocabulary. The
expected field-sets here are derived from `docs/PROJECT_SPECS.md` tables, NOT
from the Pydantic models — otherwise the drift gate would be tautological
(`set(Model.model_fields) == set(Model.model_fields)`). Imported by:
  - `tests/ci/test_gate5_contract_schema.py` — CI gate #5 contract test

Spec ground truth (count by spec TABLE, not prose — lesson D-1: 17-vs-18):
  - §3.4 IncidentTrigger = 18 fields, row 18 = `raw_payload_ref`.
  - §3.6 Evidence = 9 fields, tiered (required / optional-nullable / derived).

`incident_id` is the H3 grouping add-on (FR-2 / DEC-1) — it is NOT a §3.4
field; the gate test acknowledges it separately.
"""

from __future__ import annotations

# IncidentTrigger — exactly the 18 fields of spec §3.4, in table order.
# row 18 = `raw_payload_ref` (ref-variant, optional, None POC).
SPEC_INCIDENT_TRIGGER_FIELDS: tuple[str, ...] = (
    "trigger_id",
    "source",
    "signal_type",
    "canonical_trigger",
    "alert_name",
    "severity",
    "title",
    "description",
    "service",
    "affected_services",
    "symptom",
    "namespace",
    "started_at",
    "ends_at",
    "labels",
    "annotations",
    "raw_payload",
    "raw_payload_ref",
)

# H3 grouping add-on (optional, default None) — NOT a §3.4 field (FR-2 / DEC-1).
INCIDENT_TRIGGER_GROUPING_FIELDS: tuple[str, ...] = ("incident_id",)

# IncidentTrigger enum domains (spec §3.4).
TRIGGER_SOURCES: frozenset[str] = frozenset(
    {"prometheus_alertmanager", "grafana_alerting_loki", "kubernetes_event"}
)
TRIGGER_SEVERITIES: frozenset[str] = frozenset({"info", "warning", "critical"})
TRIGGER_SIGNAL_TYPES: frozenset[str] = frozenset({"metric", "log", "kubernetes_event"})

# Evidence — exactly the 9 fields of spec §3.6, in spec order.
SPEC_EVIDENCE_FIELDS: tuple[str, ...] = (
    "source_type",
    "source_name",
    "query",
    "timestamp_range",
    "summary",
    "raw_excerpt",
    "confidence",
    "supports",
    "contradicts",
)

# Evidence tiers (project-context Cat 2 — Evidence object tiers).
EVIDENCE_REQUIRED: tuple[str, ...] = (
    "source_type",
    "source_name",
    "query",
    "timestamp_range",
    "summary",
)
EVIDENCE_OPTIONAL_NULLABLE: tuple[str, ...] = ("raw_excerpt", "confidence")
# Derived/conditional: list, [] when empty, NEVER null. Filled by
# evidence_normalizer / reflector (E4), not by raw tools.
EVIDENCE_DERIVED: tuple[str, ...] = ("supports", "contradicts")

__all__ = [
    "EVIDENCE_DERIVED",
    "EVIDENCE_OPTIONAL_NULLABLE",
    "EVIDENCE_REQUIRED",
    "INCIDENT_TRIGGER_GROUPING_FIELDS",
    "SPEC_EVIDENCE_FIELDS",
    "SPEC_INCIDENT_TRIGGER_FIELDS",
    "TRIGGER_SEVERITIES",
    "TRIGGER_SIGNAL_TYPES",
    "TRIGGER_SOURCES",
]
