# Demo Guide

**Project:** 26-rca-aiops  
**Status:** Canonical rerun guide for the validated demo flows  
**Purpose:** Give one durable source of truth for what the validated live demo can honestly claim, how to run it, and when to downgrade the story.

## 1. What this guide is for

This guide is for the **full Kubernetes-backed demo environment**.
It assumes the `demo`, `observability`, and `rca` namespaces exist, `kubectl` can reach the cluster, and the RCA backend is exposed through the real demo deployment surface.

What this guide is **not**:
- not a local FastAPI smoke-test guide
- not proof that `localhost:8000` on its own equals live-demo readiness
- not a claim that any `202 + investigation_id` response means the full cluster-backed story is healthy

Local backend smoke runs are still useful for quick API checks, but they are a lower evidence bar than the validated demo paths below.

## 2. What this demo actually shows

This repo currently supports two validated demo paths:

1. **Direct Prometheus report-centric path**
   - strongest story when you want to show a grounded RCA report
   - validated scenario: `DependencyTimeout` on `order-service`
2. **Live Grafana Loki trigger path**
   - strongest story when you want to show live log-triggering through Grafana Alerting
   - validated scenario: `DNSFailureLogSpike` on `user`
   - latest verified rerun reached `success` with a cited RCA report after the live webhook path completed
   - Grafana sends an **alert webhook** into RCA, **not raw logs**

The common RCA surface is the same in both cases:
- a supported trigger lands at the RCA backend
- the backend returns `202 Accepted` plus an `investigation_id`
- the operator polls `GET /api/investigations/{investigation_id}`
- the truthful runtime evidence is `status`, `state_snapshot`, and `report` if present

## 3. Supported runtime surface

### 3.1 Demo entrypoints
The two validated demo entrypoints are:
- `POST /api/alerts/prometheus`
- `POST /api/alerts/grafana`

### 3.2 Read surface
After ingest, the presenter/operator reads the investigation through:
- `GET /api/investigations/{investigation_id}`

This is the real operator-facing runtime surface today.

### 3.3 Report interpretation
When a report is present, the meaningful fields are:
- `root_cause`
- `evidence_backing`
- `confidence`
- `open_questions`
- `uncertainty`
- `remediation`

Important guardrails:
- `report` may still be `null` even on `success`
- `remediation` is intentionally empty in this POC
- Grafana proves a live alert-webhook path, not raw-log ingestion into RCA
- the current DNS Grafana path can now follow through to a cited report, but it is still less deterministic than Mode B
- Kubernetes-event is not part of the validated live-success story here

## 4. Recommended run order

Use this order unless the environment is already known to be degraded:

1. export `RCA_HYPOTHESIS_LLM_API_KEY` and `RCA_HYPOTHESIS_LLM_API_URL` if the backend secret is not already present
2. run `scripts/demo-mode-b.sh` for the default validated replay path
3. only switch to the manual path when you are debugging or need a partial rerun
4. if the environment is stable, demonstrate the **Grafana Loki path** as a separate live-alert story; current verified scope is alert firing plus at least one successful cited RCA follow-through on `DNSFailureLogSpike`

Recommended story order in the room:
- start with the report-centric Prometheus flow
- then switch to the live Grafana webhook story
- end by showing the investigation read surface and report fields

## 5. Demo scripts

### 5.1 Preflight
```bash
scripts/demo-preflight.sh
```
Checks kubectl context, cluster reachability, namespaces, key workloads, and backend health, then prints GO / NO-GO.

### 5.2 Default validated replay path
```bash
export RCA_HYPOTHESIS_LLM_API_KEY=<your-key>
export RCA_HYPOTHESIS_LLM_API_URL=<your-llm-endpoint>
scripts/demo-mode-b.sh
```
Use this for the strongest report-centric story when you want the flow to replay cleanly across machines.

### 5.3 Manual Prometheus trigger path
```bash
kubectl -n rca port-forward deploy/rca-backend 18000:8000
scripts/demo-trigger-prometheus.sh
```
Use this when you need to debug the report-centric flow step by step.

### 5.4 Live Grafana Loki trigger
```bash
kubectl -n observability port-forward deploy/grafana 3000:3000
kubectl -n observability port-forward deploy/loki 3100:3100
kubectl -n rca port-forward deploy/rca-backend 18000:8000
scripts/demo-trigger-grafana.sh
```
Use this for the live log-trigger story.

### 5.5 Watch one investigation
```bash
scripts/demo-watch-investigation.sh <investigation_id>
```
Use this after either trigger path returns an `investigation_id`.

For exact commands and host checks, use `docs/demo/operator-cheatsheet.md`.

## 6. GO / NO-GO guidance

### GO
Treat the run as GO when:
- `scripts/demo-preflight.sh` prints GO
- the chosen trigger returns `202 Accepted`
- an `investigation_id` is present
- the watcher reaches a terminal status
- if you are claiming the report-centric story, the `report` is non-null

### NO-GO
Treat the run as NO-GO when any of these are true:
- `kubectl` is missing
- required namespaces or workloads are missing
- `rca-backend` health fails
- the Prometheus trigger does not return `202` or has no `investigation_id`
- the Prometheus path returns `report=null` but you were planning to present it as a report demo
- Grafana does not show the expected firing alert and you have no fresh evidence that the webhook path is still valid

## 7. Fallback policy

If the environment is shaky:
- fall back to the **Prometheus path** first
- if the report is missing, downgrade the story to lifecycle-only
- do **not** claim the Grafana path proves raw-log ingestion into RCA; it proves the alert webhook path
- do **not** claim Kubernetes-event readiness from this guide; that path is outside the validated live story here

## 8. Role split across demo docs

Use each file for one job only:
- `docs/demo/guide.md` — validated demo truth, run order, GO / NO-GO, fallback policy
- `docs/demo/operator-cheatsheet.md` — exact commands, runtime checks, blocker triage
- `docs/demo/presenter-script.md` — what to say in the room
- `docs/demo/report-template.md` — record one run and its verdict

## 9. Cross-references

- `docs/demo/operator-cheatsheet.md`
- `docs/demo/presenter-script.md`
- `docs/demo/report-template.md`
- `docs/current-rca-runtime-truth-table.md`

## 10. Unresolved questions

- Which environment will host the rerun: local kind, shared cluster, or narrated evidence-only walkthrough?
- Do you want the presenter to prefer the Prometheus report story every time, or switch to Grafana when the live webhook path is freshly verified?
