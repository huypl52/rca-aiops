# Alert Payload Mapping

**Project:** 26-rca-aiops  
**Status:** Current ingress-to-trigger mapping guide  
**Purpose:** Show how supported incoming payloads are interpreted today and what fields matter most for useful RCA.

## 1. Mapping stance

This document describes the **current supported ingress paths** and how they map into the normalized trigger contract.

Supported ingress paths today:
- Prometheus alerts
- Grafana alerts
- Kubernetes events

The source is determined by the endpoint used, not by trusting a free-form `source` field inside the payload.

See:
- `routers/ingest.py`
- `services/normalize.py`
- `models/incident_trigger.py`

## 2. Canonical trigger intent

Regardless of source, the runtime tries to normalize incoming payloads into a shape that gives the graph enough context to investigate:
- stable trigger identity
- source type
- signal type
- alert or reason name
- service identity
- namespace/environment identity
- severity
- time window or start time
- labels and annotations
- raw payload for auditability

The full normalized shape is broader than what every graph node consumes immediately, but these fields preserve the audit trail.

## 3. Prometheus alert mapping

### Current ingestion path supports
Typical useful incoming fields:
- `fingerprint`
- `labels.alertname`
- `labels.service`
- `labels.namespace` or equivalent namespace marker when present
- `labels.severity`
- `labels.scenario` when available
- `startsAt`
- `endsAt`
- `annotations.summary`
- `annotations.description`

### Practical mapping intent
Prometheus alerts should provide enough information to populate:
- canonical trigger name from `labels.alertname`
- service identity from `labels.service`
- severity from `labels.severity` when present
- incident timing from `startsAt` / `endsAt`
- human-readable summary from `annotations.summary` / `annotations.description`

### Alertmanager webhook format handling

Alertmanager sends its webhook payload as an envelope with an `alerts` array:
```json
{"status":"firing","alerts":[{"status":"firing","labels":{...},"annotations":{...},"startsAt":"...","endsAt":"...","fingerprint":"...",...}],"...":"..."}
```

The normalizer (`services/normalize.py`) includes `_unwrap_alertmanager_envelope()` which detects this envelope and extracts the first firing alert. Direct POSTs (manual `curl`, test harness) are unaffected — the normalizer handles both formats transparently.

The full original webhook envelope is preserved in `raw_payload` for audit/debug context, even when the normalizer selects one firing alert to populate the trigger fields.

Resolved-only Alertmanager envelopes are not accepted as fresh incidents. The repo now also sets `send_resolved: false` in the authored Alertmanager config so resolved notifications are suppressed at the source as a second defensive layer.

No adapter layer is needed. Alertmanager-to-RCA trigger forwarding returns `202` as of Phase 2 (2026-07-01).

### Minimum useful fields for RCA
If you want the downstream investigation to be useful, prioritize:
- alert name
- service name
- start time
- stable labels
- readable summary/description

## 4. Grafana alert mapping

### Current ingestion path supports
Useful incoming fields are conceptually similar to the Prometheus path:
- fingerprint or equivalent stable alert identity
- alert labels, especially service and severity
- start time and end time
- annotations or message fields that explain the symptom

### Practical mapping intent
Treat Grafana alert payloads as another alert-normalization source, not as a separate investigation model.

The target outcome is the same:
- a service-aware incident trigger
- enough time and label context to seed evidence collection

## 5. Kubernetes event mapping

### Current ingestion path supports
Useful incoming fields include:
- `metadata.uid`
- `reason`
- `message`
- `lastTimestamp` or `eventTime`
- `type`
- labels or object fields that identify the service/workload
- annotations where present

### Practical mapping intent
Kubernetes events are most useful when they can still be tied back to:
- a service or workload identity
- a namespace
- a reason or symptom category
- a timestamped incident window

## 6. What the graph uses most directly after normalization

The full normalized trigger is preserved, but the current graph is most sensitive to:
- `service`
- `namespace`
- `time_window`
- `labels`
- `affected_services` or topology seed when available

If these are weak or ambiguous, investigation quality drops even if ingestion technically succeeds.

See:
- `graph/nodes/incident_context_builder.py`

## 7. Mapping guidance for external teams

When adapting a target stack into this runtime, make sure each payload source can answer these questions:
- what incident class or alert name is this?
- which service does it belong to?
- which namespace or environment does it belong to?
- when did the incident begin?
- what labels help narrow evidence queries?
- what human-readable text explains the symptom?

If a source cannot answer most of those questions, it may still ingest, but it is not a strong RCA trigger source yet.

## 8. Scope guardrails

Safe claims:
- the current ingestion path supports Prometheus alerts, Grafana alerts, and Kubernetes events
- normalization preserves auditability and a canonical trigger shape
- better payload identity and time data improve RCA quality

Unsafe claims:
- every arbitrary webhook schema is already supported
- every supported ingest path has equal RCA breadth today
- ingestion alone certifies a target stack for integrated RCA

## 9. Cross-references

- `docs/integration/observability-contract.md`
- `docs/integration/examples.md`
- `docs/integration/readiness-checklist.md`
- `docs/integration/integration-standard.md`
- `docs/PROJECT_SPECS.md`
