# AIOps Integration Standard — RCA AI Agent POC

**Project:** 26-rca-aiops  
**Status:** Canonical integration standard  
**Purpose:** Define how the RCA/AIOps product integrates with external app/server stacks through a repeatable, standards-based onboarding model.

## 1. Scope and positioning

This standard defines the minimum integration contract for onboarding an external stack into the RCA/AIOps product.

It is **standards-based onboarding**, not universal plug-and-play.

It assumes three separate validation layers:
- **Backend / UAT validation already achieved** — internal product behavior, contracts, and safety boundaries were validated in the RCA UAT set
- **Service smoke validation** — direct smoke checks for the demo microservices confirm the stack can be exercised end to end
- **Per-target integrated RCA acceptance** — required for each external target stack before that target is certified

This standard is the source of truth for what must be wired into a target stack before acceptance.

## 2. Integration model

A target stack is integrated when the RCA/AIOps product can:
1. receive triggers or alerts from the target
2. identify the target service and runtime context
3. collect read-only evidence from the target’s observability sources
4. normalize evidence into the product contract
5. produce an RCA output that is traceable, auditable, and fail-closed

The product should be treated as an **evidence-driven RCA layer** for a known target scope, not a generic plug-in for every environment without onboarding work.

## 3. Required integration domains

### 3.1 Trigger / alert sources
A target must expose at least one supported trigger path, such as:
- metric alerts
- log alerts
- trace / APM anomaly signals
- Kubernetes or runtime events
- change / deploy events that correlate to symptoms

The trigger source must produce a reproducible incident signal with a timestamped payload.

### 3.2 Service identity contract
Every integrated target must have a stable service identity model.

Required identity fields:
- service name
- namespace / environment
- owner or owning team
- runtime type or deployment unit
- correlation key(s) used to join telemetry

Recommended identity fields:
- app name
- version / release channel
- cluster / region / tenant
- dependency group or criticality tier

### 3.3 Metrics / logs / traces / APM sources
A target integration should cover the observability surfaces that matter for RCA:
- **metrics** — counters, gauges, histograms, saturation, error rate, latency
- **logs** — request, error, and application logs with searchable labels
- **traces** — distributed traces or span-based timing where available
- **APM** — when present, use it as a signal source, not as the sole truth

The product should be able to use one or more of these sources, but the integration should document which sources are authoritative for the target.

### 3.4 Runtime / infra metadata
A target must provide runtime context sufficient to explain the incident window:
- host / pod / container identity
- namespace / deployment / replica set
- process or workload ID when available
- start / stop / restart times
- health / readiness state where relevant

### 3.5 Change intelligence / deploy metadata
Integrations should capture release context that can explain a symptom:
- deployment timestamp
- release version / build SHA
- rollout strategy
- config change marker
- feature flag or migration marker if relevant

If a change event can correlate with the trigger, it must be available as evidence metadata.

### 3.6 Topology / ownership metadata
The product should know how the target depends on other services.

Minimum topology metadata:
- upstream / downstream dependencies
- owning team or escalation owner
- critical dependency labels
- blast-radius hints where available

### 3.7 Read-only evidence adapters
The product must access evidence through **read-only adapters** only.

Adapters should:
- query, fetch, or read evidence
- never mutate target systems
- never execute remediation
- never require privileged write paths

### 3.8 Evidence normalization
Raw evidence must be normalized into the product’s canonical evidence shape.

Normalization should preserve:
- source type
- source name
- query or retrieval context
- time window
- summary
- raw excerpt or snippet where possible
- confidence or relevance hint
- support / contradict markers when available

Normalization must not invent facts.

### 3.9 RCA output contract
The target integration is accepted only when the RCA output is usable and traceable.

Minimum output contract:
- incident / investigation reference
- suspected root cause or insufficient-evidence result
- supporting evidence list
- confidence or certainty signal
- open caveats / follow-up items
- read-only safety confirmation

### 3.10 Safety / fail-closed / auditability
The integration must fail closed when evidence is insufficient.

Required safety properties:
- no write / patch / delete / exec behavior in evidence collection
- no hidden remediation path
- no invented conclusions without evidence
- clear audit trail from trigger to RCA output
- reproducible evidence references for leadership review

## 4. Onboarding maturity tiers

Use these tiers to avoid claiming certification too early.

| Tier | Meaning | Outcome |
|---|---|---|
| **Tier 0 — Discovered** | Target identified, but metadata is incomplete | Not onboarded |
| **Tier 1 — Connected** | Trigger and identity are wired | Partial integration |
| **Tier 2 — Observable** | Metrics / logs / traces and metadata are usable | Ready for acceptance run |
| **Tier 3 — Accepted** | Integrated RCA acceptance run passed for the target | Certified target |

## 5. What counts as integrated acceptance

A target is accepted only when a real run proves all of the following:
- a fault or symptom was reproduced or injected
- a trigger was observed
- the product collected evidence from the target’s observability sources
- the agent investigation ran
- the RCA output was recorded
- the run concluded PASS / FAIL / BLOCKED with caveats

UAT backend validation and demo smoke validation do **not** certify a target by themselves.

## 6. Operating rules

- Keep all integrations read-only.
- Prefer explicit metadata contracts over implicit assumptions.
- Keep evidence normalization deterministic and auditable.
- Treat missing metadata as onboarding work, not as a product failure.
- Use per-target acceptance before declaring a stack integrated.

## 7. References

- `docs/uat/uat-closeout-bundle.md` — UAT closeout context
- `docs/uat/demo-microservice-smoke-status.md` — demo service smoke status
- `docs/uat/integrated-rca-acceptance-run.md` — per-target integrated acceptance record
