# Readiness Checklist

**Project:** 26-rca-aiops  
**Status:** Current-runtime target-stack gate  
**Purpose:** Decide whether a target stack is ready for an integrated RCA acceptance run against the runtime that exists today.

## How to use this checklist

- Use one copy per target stack or environment.
- Mark each item with one of:
  - **PASS**
  - **PARTIAL**
  - **FAIL**
  - **N/A**
- Record blockers immediately.
- Do not call a target stack accepted until it passes integrated RCA acceptance separately.

## 1. Trigger and ingest readiness

| Item | Status | Notes |
|---|---|---|
| At least one supported ingress source is available: Prometheus alert, Grafana alert, or Kubernetes event |  |  |
| Incoming payload includes a stable alert or reason name |  |  |
| Incoming payload identifies the target service or workload |  |  |
| Incoming payload gives a usable start timestamp or incident window |  |  |
| Labels/annotations are preserved well enough to support investigation narrowing |  |  |

## 2. Identity and context readiness

| Item | Status | Notes |
|---|---|---|
| Target service naming is stable |  |  |
| Namespace or environment identity is stable |  |  |
| Affected services or topology seed can be supplied when relevant |  |  |
| Operators can explain how payload identity maps to runtime service identity |  |  |

## 3. Metrics readiness

| Item | Status | Notes |
|---|---|---|
| The target exposes service-scoped metrics usable by PromQL queries |  |  |
| Metrics support request, error, or latency investigation |  |  |
| Labels support deterministic service and namespace filtering |  |  |
| The target can support a time-windowed evidence query during an incident |  |  |

## 4. Logs and trace readiness

| Item | Status | Notes |
|---|---|---|
| Logs are searchable by service and environment |  |  |
| Logs carry usable message/severity fields |  |  |
| Correlation fields such as request ID or trace ID are present when available |  |  |
| Trace/OTEL data is available if the target expects trace-assisted RCA |  |  |

## 5. Evidence and adapter readiness

| Item | Status | Notes |
|---|---|---|
| Evidence access path is read-only only |  |  |
| The team can explain which observability sources are authoritative for this target |  |  |
| Evidence can be tied to a service, query/retrieval context, and time window |  |  |
| Raw excerpts or snippets can be preserved where available |  |  |
| Auditability expectations are understood |  |  |

## 6. Floor-rule readiness

| Item | Status | Notes |
|---|---|---|
| The incident classes expected for this target are known |  |  |
| Matching floor rules exist for those incident classes, or gaps are explicitly recorded |  |  |
| The team understands that unsupported trigger classes may fail closed |  |  |

## 7. Runtime mode readiness

| Item | Status | Notes |
|---|---|---|
| The deployment mode is known: minimal path vs durable/full-graph RCA path |  |  |
| If integrated RCA is expected, the environment is configured for the richer RCA runtime path |  |  |
| Provider-backed planner expectations are explicit if that mode is enabled |  |  |

## 8. RCA output and review readiness

| Item | Status | Notes |
|---|---|---|
| Reviewers know what counts as usable RCA output for this target |  |  |
| The team accepts grounded evidence as the basis for RCA claims |  |  |
| The team is prepared to record PASS / FAIL / BLOCKED rather than smoothing over uncertainty |  |  |
| A reviewer or sign-off owner is assigned |  |  |

## 9. Readiness outcome

| Field | Value |
|---|---|
| Target status | Not ready / Partially ready / Ready for integrated acceptance / Accepted |
| Reviewer |  |
| Date |  |
| Key blockers |  |
| Notes |  |

## 10. Interpretation notes

- **PASS** means the condition is met clearly enough for the current runtime.
- **PARTIAL** means the target may still be able to run, but the gap can materially reduce RCA quality.
- **FAIL** means the target is not ready for a defensible integrated acceptance run on that dimension.
- **N/A** means the condition does not apply to the target, not that it was skipped casually.

## Cross-references

- `docs/integration/observability-contract.md`
- `docs/integration/alert-payload-mapping.md`
- `docs/integration/examples.md`
- `docs/integration/onboarding-checklist.md`
- `docs/integration/integrated-acceptance-runbook.md`
