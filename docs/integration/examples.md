# Integration Examples

**Project:** 26-rca-aiops  
**Status:** Current-runtime examples  
**Purpose:** Show small, copy-adaptable examples that match the runtime validated today.

## 1. Example alert payload characteristics

A useful incoming alert payload should make these questions easy to answer:
- what incident class is this?
- which service does it belong to?
- when did it start?
- what labels or annotations help narrow evidence collection?
- what short text explains the symptom?

For the currently proven seeded path, a strong payload shape includes values equivalent to:
- alert name: `DependencyTimeout`
- service: `order-service`
- namespace: `demo`
- severity: `critical`
- scenario label for easier run classification
- start time and end time or firing window
- human-readable summary/description

## 2. Example normalized trigger interpretation

A useful normalized trigger interpretation should preserve:
- stable trigger identity
- source type
- signal type
- service and namespace identity
- labels and annotations
- start/end timing
- raw payload for auditability

The current graph uses only a subset of that shape most directly during investigation startup:
- `service`
- `namespace`
- `time_window`
- `labels`
- topology seed or affected services when present

This is why technically valid ingestion can still produce weak RCA if service identity or time data is poor.

## 3. Example evidence item shape

A useful normalized evidence item should look conceptually like this:
- `source_type`: where the evidence came from
- `source_name`: the service or source identity
- `query`: the query or retrieval context
- `timestamp_range`: the incident-aligned time window
- `summary`: short explanation of what the evidence showed
- `raw_excerpt`: concrete snippet or excerpt when available
- `supports`: deterministic hypothesis links when exact matching exists
- `contradicts`: deterministic contradiction links when available

The current grounded RCA path depends heavily on `raw_excerpt` and deterministic support linkage.

## 4. Example observability expectation set

For a target stack that wants to use the currently strongest validated path, prefer:
- service-scoped metrics that can support request/error/latency investigation
- stable namespace or environment identity
- searchable logs keyed by service identity
- correlation fields such as request ID or trace ID when available
- alert payloads that preserve alert name, service, severity, and timing

Recommended onboarding conventions, even when not yet broadly validated at equal depth:
- OTEL `service.name`
- OTEL `service.namespace`
- deployment environment tags
- trace/span correlation fields
- structured logs with severity and message fields

## 5. Example readiness interpretation

### Strong target
A strong target typically has:
- one supported alert source already wired
- stable service and namespace identity
- PromQL-friendly metrics with service labels
- searchable logs with service and message context
- explicit understanding of which incident classes have floor coverage
- environment configured for the durable/full-graph RCA path when integrated RCA is expected

### Weak target
A weak target typically shows one or more of these gaps:
- webhook exists, but service identity is ambiguous
- metrics exist, but labels do not support deterministic service filtering
- logs exist, but they cannot be tied back to the service or incident window reliably
- the team expects arbitrary incident classes to pass even though floor coverage is narrow
- the deployment is still on a minimal path while expecting full RCA behavior

## 6. Example operator takeaway

If a target only satisfies this statement:
- “we can send alerts to the backend”

that is not enough.

A stronger statement is:
- “we can send supported alerts that identify service, namespace, severity, and incident timing, and we can back them with read-only metrics/log evidence in a deterministic time window.”

That second statement is much closer to readiness for integrated acceptance.

## Cross-references

- `docs/integration/observability-contract.md`
- `docs/integration/alert-payload-mapping.md`
- `docs/integration/readiness-checklist.md`
- `docs/current-rca-runtime-truth-table.md`
- `docs/uat/integrated-rca-acceptance-run.md`
