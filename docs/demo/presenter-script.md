# Demo Script

**Project:** 26-rca-aiops  
**Status:** Presenter talk track for the validated demo flows  
**Purpose:** Help one presenter narrate the live demo without overclaiming the current runtime.

For validated-path truth, endpoints, GO / NO-GO, and fallback policy, use `docs/demo/guide.md`.
For exact commands and runtime checks, use `docs/demo/operator-cheatsheet.md`.

## 1. Opening talk track

Use wording close to this:

> This POC is a read-only RCA investigation flow. On the validated live paths, a direct Prometheus `DependencyTimeout` alert for `order-service` and a Grafana Loki `DNSFailureLogSpike` alert for `user` can each create an investigation. The Prometheus path is the strongest report-centric story on this environment. We do not show remediation automation in this demo.

Keep these scope notes explicit:
- the system under investigation is the 5-service demo stack
- the RCA backend is separate from the demo stack
- the read-only boundary applies to the RCA investigation tools, not to the demo services themselves
- Kubernetes-event is not part of the validated live-success story here
- backend `/metrics` currently returns `404` in this environment

## 2. Demo flow narration

### Step 1 — Set context
Say:
- what the system under investigation is
- what namespace(s) are involved
- which validated path you will use
- whether this run is expected to demonstrate lifecycle only, or lifecycle plus cited RCA output

### Step 2 — Show health and deployment surface
Narration:
- the demo stack emits metrics and logs
- Prometheus proves the metric-trigger path
- Loki + Grafana Alerting prove the live log-trigger path
- the RCA backend receives supported triggers and creates investigations

### Step 3 — Send one supported trigger
Narration:
- this is the investigation entrypoint
- the backend returns `202` plus `investigation_id`
- the flow is asynchronous, so the operator polls

### Step 4 — Poll the investigation
Narration:
- this is the main operator-facing runtime surface today
- the current POC uses polling, not SSE
- the honest evidence is `status`, `state_snapshot`, and `report` if present

### Step 5A — If `report` is null
Say:

> The alert ingestion and investigation lifecycle worked, but this run did not produce the validated cited report path. We do not claim a grounded RCA report from this run.

Emphasize:
- honest runtime behavior
- no fake report generation
- safe investigation lifecycle is working

### Step 5B — If `report` is present
Narration:
- `root_cause` claims must be backed by cited evidence
- `evidence_backing` preserves concrete excerpts
- `remediation` is intentionally empty in this POC
- uncertainty is preserved rather than smoothed over

### Step 6 — Close the demo
Use wording close to this:

> The current strength of this POC is two validated live trigger stories: direct Prometheus for the strongest report-centric walkthrough, and Grafana Loki alerting for the strongest live log-trigger walkthrough. Kubernetes-event remains outside the validated live-success story.

## 3. Presenter branches

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
Use when:
- the rehearsed Prometheus path is still green
- the environment is stable enough to return a non-null `report`
- the presenter has already tested the exact trigger path

Goal:
- everything in Branch A
- plus cited RCA output walkthrough

### Branch C — Validated live Grafana trigger demo
Use when:
- Loki is ingesting matching demo logs
- Grafana active alerts show `DNSFailureLogSpike` with `service=user`
- the backend has already accepted the live Grafana webhook with `202`

Goal:
- prove live log-trigger ingestion through Loki + Grafana Alerting
- prove the backend accepts the real Grafana source, not only a hand-crafted POST
- keep claims scoped to trigger ingestion unless the resulting investigation also produces a grounded report in that run

## 4. What to avoid saying

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

## 5. Suggested evidence to keep open during the demo

Have these ready:
- namespace/deployment status output
- one supported trigger payload
- one poll response with `investigation_id`
- one known-good example of a non-null report, if Branch B is planned

## 6. Cross-references

- `docs/demo/guide.md`
- `docs/demo/operator-cheatsheet.md`
- `docs/current-rca-runtime-truth-table.md`

## Unresolved questions

- Which exact environment will host the live demo: local kind, shared cluster, or narrated evidence-only walkthrough?
- Has the chosen demo environment already been verified to return a non-null `report` for the `DependencyTimeout` path?
- Who is the final audience: engineering leadership, platform operators, or external stakeholders?
