# Demo Script

**Project:** 26-rca-aiops  
**Status:** Runtime-aware demo script  
**Purpose:** Help one presenter run the validated live demo without overclaiming the current runtime.

## 1. Demo goal

Show the strongest current story the repo can support:
- validated live path A: direct Prometheus alert for `DependencyTimeout` on `order-service`
- validated live path B: Grafana Loki alert for `DNSFailureLogSpike` on `user`
- investigation is created asynchronously
- the operator can poll by `investigation_id`
- on this environment, the Prometheus path returns a structured evidence-backed RCA report
- the live walkthrough stays honest about Kubernetes-event limits

This script avoids claiming Kubernetes-event demos are equally ready.

## 2. Opening talk track

Use wording close to this:

> This POC is a read-only RCA investigation flow. On the validated live paths, a direct Prometheus `DependencyTimeout` alert for `order-service` and a Grafana Loki `DNSFailureLogSpike` alert for `user` can each create an investigation. The Prometheus path is the strongest report-centric story on this environment. We do not show remediation automation in this demo.

Keep these scope notes explicit:
- the system under investigation is the 5-service demo stack
- the RCA backend is separate from the demo stack
- the read-only boundary applies to the RCA investigation tools, not to the demo services themselves
- the validated live demo can use direct Prometheus ingest or live Grafana Loki alerting
- the Kubernetes-event path exists, but this rehearsal did not validate it as a live-success path
- backend `/metrics` currently returns `404` in this environment

## 3. Primary demo story

Use one of these validated scenarios:

### Option A — strongest report-centric story
- incident class: `DependencyTimeout`
- target service: `order-service`
- namespace: `demo`
- trigger source: direct Prometheus alert

Why choose Option A:
- it is still the strongest live path from the rehearsal
- it produced `status=success` with a non-null `report`
- it included cited evidence and ranked root-cause output
- it is the safest stakeholder-facing story today

### Option B — live log-alerting story
- incident class: `DNSFailureLogSpike`
- target service: `user`
- namespace: `demo`
- trigger source: Grafana Loki alert

Why choose Option B:
- it is now a validated live trigger path through Loki + Grafana Alerting
- Grafana produced a real alert with `service=user`
- the backend accepted the live Grafana webhook with `202`
- it is the strongest way to show log-based trigger ingestion without overclaiming Kubernetes-event readiness

## 4. Pre-demo truth check

Before the meeting, confirm the validated live path is still holding.

### 4.1 Required signal

If the backend is running on the rehearsed path:
- `RCA_CHECKPOINT_DB` is set
- the supported Prometheus trigger creates an investigation
- polling reaches `status=success`
- `report` is non-null on this environment

### 4.2 Fallback signal

If the planned path regresses:
- fall back to lifecycle-only narration
- if Prometheus report output regresses, you may still use the separately validated Grafana live-trigger story
- do not swap to Kubernetes-event success claims unless separately rehearsed and validated

## 5. Demo flow

### Step 1 — Set context

Say:
- what the system under investigation is
- what namespace(s) are involved
- what trigger type you will use
- whether this run is expected to demonstrate:
  - investigation lifecycle only, or
  - investigation lifecycle plus cited RCA output

### Step 2 — Show the health and deployment surface

Show:
- `demo` namespace exists
- `observability` namespace exists
- `rca` namespace exists
- backend health endpoint returns OK

Narration:
- the demo stack emits metrics/logs/events
- Prometheus proves the metric-trigger path
- Loki + Grafana Alerting prove the log-trigger path
- the RCA backend receives supported triggers and creates investigations
- Kubernetes events are still not part of the validated live-success story here

### Step 3 — Send one supported trigger

Use one validated trigger path:
- direct Prometheus-style alert payload for `DependencyTimeout`, or
- live Grafana Loki rule firing for `DNSFailureLogSpike`

Narration:
- this is the investigation entrypoint
- the backend returns `202` plus `investigation_id`
- the flow is asynchronous, so the operator polls

### Step 4 — Poll the investigation

Show:
- `GET /api/investigations/{investigation_id}`
- `status`
- `state_snapshot`
- `report` if present

Narration:
- this is the main operator-facing runtime surface today
- the current POC uses polling, not SSE

### Step 5A — If `report` is null

Say:

> The alert ingestion and investigation lifecycle worked, but this run did not produce the validated cited report path. We do not claim a grounded RCA report from this run.

What to emphasize:
- honest runtime behavior
- no fake report generation
- safe investigation lifecycle is working

### Step 5B — If `report` is present

Show the report fields:
- `root_cause`
- `evidence_backing`
- `confidence`
- `open_questions`
- `uncertainty`
- `remediation`

Narration:
- `root_cause` claims must be backed by cited evidence
- `evidence_backing` preserves concrete excerpts
- `remediation` is intentionally empty in this POC
- uncertainty is preserved rather than smoothed over

### Step 6 — Close the demo

Use wording close to this:

> The current strength of this POC is two validated live trigger stories: direct Prometheus for the strongest report-centric walkthrough, and Grafana Loki alerting for the strongest live log-trigger walkthrough. Kubernetes-event remains outside the validated live-success story.

## 6. Presenter branches

### Branch A — Safe baseline demo

Use when:
- runtime mode is unclear
- the Prometheus path regresses
- cluster setup is fragile

Goal:
- prove supported alert ingestion
- prove investigation creation
- prove polling and state visibility
- prove read-only posture

### Branch B — Validated live report demo

Use only when:
- the rehearsed Prometheus path is still green
- the environment is stable enough to return a non-null `report`
- the presenter has already tested the exact trigger path

Goal:
- everything in Branch A
- plus cited RCA output walkthrough

### Branch C — Validated live Grafana trigger demo

Use only when:
- Loki is ingesting matching demo logs
- Grafana active alerts show `DNSFailureLogSpike` with `service=user`
- the backend has already accepted the live Grafana webhook with `202`

Goal:
- prove live log-trigger ingestion through Loki + Grafana Alerting
- prove the backend accepts the real Grafana source, not only a hand-crafted POST
- keep claims scoped to trigger ingestion unless the resulting investigation also produces a grounded report in that run

## 7. What to avoid saying

Do not say:
- the system always returns a final RCA report
- Kubernetes-event demos are live-success paths here
- Grafana always returns the same report quality as the Prometheus path
- this POC performs remediation
- backend `/metrics` is available in this environment

Prefer saying:
- current runtime path
- supported trigger path
- grounded when evidence-backed
- validated on the proven demo story

## 8. Suggested evidence to keep open during the demo

Have these ready:
- namespace/deployment status output
- one supported trigger payload
- one poll response with `investigation_id`
- one known-good example of a non-null report, if Branch B is planned

## 9. Cross-references

- `docs/current-rca-runtime-truth-table.md`
- `docs/integration/environment-bootstrap-runbook.md`
- `docs/integration/execution-checklist.md`
- `docs/operator-runbook.md`
- `docs/aiops-integrated-acceptance-runbook.md`

## Unresolved questions

- Which exact environment will host the live demo: local kind, shared cluster, or narrated evidence-only walkthrough?
- Has the chosen demo environment already been verified to return a non-null `report` for the `DependencyTimeout` path?
- Who is the final audience: engineering leadership, platform operators, or external stakeholders?
