"""Pydantic contract models AT PORTS (AD-9).

Story 0.2 implements the runtime contract models:
  - `IncidentTrigger` — 18 fields spec §3.4 + optional `incident_id` (H3)
  - `Evidence` — 9 fields spec §3.6, tiered (AD-6 MUST)

These live only at the port (api-gateway validate-on-ingress /
evidence_normalizer model_validate-on-read). Consumer wiring is deferred:
routers ingest = Story 1-1 (E1), evidence_normalizer node = Story 4-2 (E4).

The canonical field vocabulary (gate #5 drift source-of-truth) lives in
`ci.contract_schema`, NOT here.
"""

from models.evidence import Evidence, TimestampRange
from models.incident_trigger import (
    IncidentTrigger,
    Severity,
    SignalType,
    TriggerSource,
)

__all__ = [
    "Evidence",
    "IncidentTrigger",
    "Severity",
    "SignalType",
    "TimestampRange",
    "TriggerSource",
]
