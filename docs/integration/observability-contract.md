# Observability Contract

**Project:** 26-rca-aiops  
**Status:** Current-runtime observability contract  
**Purpose:** State what the RCA runtime actually assumes today for alerts, metrics, logs, traces, evidence, and floor checks.

## 1. Contract stance

This document describes the **current runtime contract**, not the broadest future integration vision.

Separate each expectation into one of three buckets:
- **supported today** — directly reflected in current runtime behavior
- **recommended for onboarding** — useful conventions that improve RCA quality
- **not yet broadly validated** — desirable but not yet proven across targets

## 2. Supported today

### 2.1 Trigger ingress and normalization
Current supported ingress paths are:
- Prometheus alerts
- Grafana alerts
- Kubernetes events

These enter through source-specific ingest routes and are normalized into a canonical incident trigger shape before the graph starts.

See:
- `routers/ingest.py`
- `services/normalize.py`
- `models/incident_trigger.py`

### 2.2 Context fields the graph actually uses
The current incident context builder depends mainly on:
- `service`
- `namespace`
- `time_window`
- `labels`
- `topology_seed`

This is narrower than the broader integration vision in the standard docs.

See:
- `graph/nodes/incident_context_builder.py`

### 2.3 Metrics / Prometheus-style evidence
The currently proven planner/runtime path is PromQL-first.

Supported today:
- provider-backed planner seam emits executable `query_prometheus_raw` plans on the validated path
- deterministic fallback also emits PromQL queries on the validated path
- the runtime expects a useful target stack to expose service/namespace-scoped metrics that can support request, error, and latency analysis

Important scope note:
- the active proven path is still narrower than a broad multi-tool planner
- current live proof is metric/alert-driven, not broad trace-first reasoning

See:
- `graph/hypothesis_sources.py`
- `tools/executors.py`
- `tools/router.py`
- `docs/current-rca-runtime-truth-table.md`

### 2.4 Logs / Loki-style evidence
Log-based evidence is part of the intended integration surface, and the demo stack includes structured logs and Loki shipping.

Supported today at the contract level:
- logs can be a read-only evidence source
- service and namespace identity should remain queryable
- structured fields materially improve RCA usefulness

Deployment status (as of Phase 2, 2026-07-01):
- Loki `3.2.1` is running in single-binary mode with an in-memory ring KV store (`common.ring.kvstore.store: inmemory`). The original Consul default was replaced with a single-instance in-memory ring.
- Alloy `v1.8.0` is running and shipping demo pod logs to Loki. The manifest uses the valid `v`-prefixed tag and a simplified `discovery.kubernetes` → `loki.source.kubernetes` pipeline.
- Both components are `1/1` ready and validated in the live cluster.

Scope note:
- log-driven RCA breadth is not yet validated as strongly as the PromQL-first seeded path

See:
- `demo/app/factory.py`
- `observability/manifests/30-loki-alloy.yaml`
- `observability/manifests/40-grafana.yaml`

### 2.5 Evidence normalization shape
Raw evidence is normalized into a canonical shape that preserves:
- `source_type`
- `source_name`
- `query`
- `timestamp_range`
- `summary`
- `raw_excerpt` where available
- `confidence` where available
- deterministic `supports` / `contradicts` lists when derived

Normalization must remain deterministic and must not invent facts.

See:
- `models/evidence.py`
- `graph/nodes/evidence_normalizer.py`
- `docs/integration/integration-standard.md`

### 2.6 Read-only evidence access
This is one of the strongest current guarantees.

Evidence collection must remain read-only:
- query
- fetch
- describe
- inspect

It must not:
- patch
- delete
- exec remediation
- mutate the target

See:
- `tools/executors.py`
- `tools/port.py`
- `docs/current-rca-runtime-truth-table.md`

## 3. Recommended for onboarding

### 3.1 OTEL / traces
Recommended onboarding fields:
- `service.name`
- `service.namespace`
- `deployment.environment`
- `trace_id`
- `span_id`
- request or correlation id
- exception metadata where available

Why these are recommended:
- they improve evidence correlation across metrics, logs, and traces
- they reduce ambiguity during investigation review

Scope note:
- the current runtime does not yet prove broad trace-driven RCA consumption at the same level as the metric-driven demo path

### 3.2 Metrics labeling conventions
Recommended fields and labels:
- stable service identity
- stable namespace/environment identity
- request/error/latency metric families
- histogram latency metrics where possible
- labels that make service-scoped querying deterministic

### 3.3 Log schema conventions
Recommended log fields:
- timestamp
- service name
- namespace/environment
- severity/level
- message
- correlation id or trace id when available
- exception type/message where available

These conventions are not just cosmetic; they materially improve whether logs are usable as evidence.

## 4. Not yet broadly validated

The following should be documented as desired or recommended, not as already certified product breadth:
- broad trace-driven RCA across arbitrary target stacks
- broad planner/tool execution breadth beyond the current PromQL-first validated path
- universal floor coverage for many incident classes
- automatic topology-rich reasoning across arbitrary service graphs
- engine self-observability as a complete integration contract

See:
- `docs/integration/readiness-gap-assessment.md`
- `docs/current-rca-runtime-truth-table.md`

## 5. Floor-rule limitation

Current floor-check behavior is real and important, but the checked-in registry remains narrow.

Supported today:
- fail-closed behavior for unknown or unsupported trigger coverage
- seeded proof for the validated demo path

Not yet safe to imply:
- broad incident-family floor coverage for arbitrary target stacks

See:
- `config/floor_registry.yaml`
- `graph/floor_check.py`

## 6. Practical onboarding interpretation

Treat a target stack as contract-ready only when:
- it can emit supported triggers
- it exposes stable service and namespace identity
- it provides read-only metrics/log evidence in a shape the runtime can use
- it can support deterministic time-windowed evidence review
- it can satisfy or explicitly extend the required floor rules for its incident classes

## 7. Cross-references

- `docs/integration/integration-standard.md`
- `docs/current-rca-runtime-truth-table.md`
- `docs/integration/alert-payload-mapping.md`
- `docs/integration/examples.md`
- `docs/integration/readiness-checklist.md`
