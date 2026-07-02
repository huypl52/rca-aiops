# Demo Guide

**Project:** 26-rca-aiops  
**Status:** Canonical rerun guide for the validated demo flows  
**Purpose:** Give one durable source of truth for what the validated live demo can honestly claim, how to run it, and when to downgrade the story.

## 1. What this demo actually shows

This repo currently supports two validated demo paths:

1. **Direct Prometheus report-centric path**
   - strongest story when you want to show a grounded RCA report
   - validated scenario: `DependencyTimeout` on `order-service`
2. **Live Grafana Loki trigger path**
   - strongest story when you want to show live log-triggering through Grafana Alerting
   - validated scenario: `DNSFailureLogSpike` on `user`
   - Grafana sends an **alert webhook** into RCA, **not raw logs**

The common RCA surface is the same in both cases:
- a supported trigger lands at the RCA backend
- the backend returns `202 Accepted` plus an `investigation_id`
- the operator polls `GET /api/investigations/{investigation_id}`
- the truthful runtime evidence is `status`, `state_snapshot`, and `report` if present

## 2. Supported runtime surface

### 2.1 Demo entrypoints
The two validated demo entrypoints are:
- `POST /api/alerts/prometheus`
- `POST /api/alerts/grafana`

### 2.2 Read surface
After ingest, the presenter/operator reads the investigation through:
- `GET /api/investigations/{investigation_id}`

This is the real operator-facing runtime surface today.

### 2.3 Report interpretation
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
- Kubernetes-event is not part of the validated live-success story here

## 3. Recommended run order

Use this order unless the environment is already known to be degraded:

1. run the preflight
2. bring up the required port-forwards
3. demonstrate the **Prometheus path first**
4. if the environment is stable, demonstrate the **Grafana Loki path**
5. use the watch script to narrate the investigation until terminal status

Recommended story order in the room:
- start with the report-centric Prometheus flow
- then switch to the live Grafana webhook story
- end by showing the investigation read surface and report fields

## 4. Demo scripts

### 4.1 Preflight
```bash
scripts/demo-preflight.sh
```
Checks the namespaces, key workloads, and backend health, then prints GO / NO-GO.

### 4.2 Direct Prometheus trigger
```bash
kubectl -n rca port-forward deploy/rca-backend 8000:8000
scripts/demo-trigger-prometheus.sh
```
Use this for the strongest report-centric story.

### 4.3 Live Grafana Loki trigger
```bash
kubectl -n observability port-forward deploy/grafana 3000:3000
kubectl -n observability port-forward deploy/loki 3100:3100
kubectl -n rca port-forward deploy/rca-backend 8000:8000
scripts/demo-trigger-grafana.sh
```
Use this for the live log-trigger story.

### 4.4 Watch one investigation
```bash
scripts/demo-watch-investigation.sh <investigation_id>
```
Use this after either trigger path returns an `investigation_id`.

For exact commands and host checks, use `docs/demo/operator-cheatsheet.md`.

## 5. GO / NO-GO guidance

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

## 6. Fallback policy

If the environment is shaky:
- fall back to the **Prometheus path** first
- if the report is missing, downgrade the story to lifecycle-only
- do **not** claim the Grafana path proves raw-log ingestion into RCA; it proves the alert webhook path
- do **not** claim Kubernetes-event readiness from this guide; that path is outside the validated live story here

## 7. Role split across demo docs

Use each file for one job only:
- `docs/demo/guide.md` — validated demo truth, run order, GO / NO-GO, fallback policy
- `docs/demo/operator-cheatsheet.md` — exact commands, runtime checks, blocker triage
- `docs/demo/presenter-script.md` — what to say in the room
- `docs/demo/report-template.md` — record one run and its verdict

## 8. Cross-references

- `docs/demo/operator-cheatsheet.md`
- `docs/demo/presenter-script.md`
- `docs/demo/report-template.md`
- `docs/current-rca-runtime-truth-table.md`

## 9. Unresolved questions

- Which environment will host the rerun: local kind, shared cluster, or narrated evidence-only walkthrough?
- Do you want the presenter to prefer the Prometheus report story every time, or switch to Grafana when the live webhook path is freshly verified?
