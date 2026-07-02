# Demo Guide

**Project:** 26-rca-aiops  
**Status:** Rerun guide for the validated demo flows  
**Purpose:** Give one durable runbook for the presenter to replay the demo later without guessing the flow.

## 1. What this demo actually shows

The demo has two validated paths:

1. **Direct Prometheus report-centric path**
   - best story when you want to show a grounded RCA report
   - still the strongest report-centric path in this repo
2. **Live Grafana Loki trigger path**
   - best story when you want to show live log-triggering through Grafana Alerting
   - Grafana sends an **alert webhook** into RCA, **not raw logs**

The common RCA surface is the same in both cases:
- the trigger lands at the RCA backend
- the backend returns `202 Accepted` plus an `investigation_id`
- the presenter then polls `GET /api/investigations/{investigation_id}`
- the useful runtime evidence is `status`, `state_snapshot`, and `report` if present

## 2. End-to-end flow in plain technical terms

### 2.1 What emits metrics and logs

The 5-service demo stack emits:
- **metrics** that Prometheus can scrape and alert on
- **logs** that Alloy ships into Loki
- **alerting signals** that Grafana can turn into a webhook

### 2.2 What Prometheus does

Prometheus is the report-centric trigger source.

When the validated `DependencyTimeout` condition appears on `order-service`, Prometheus produces the alert signal that the RCA backend accepts through:

```text
POST /api/alerts/prometheus
```

This is the strongest path for showing a cited RCA report.

### 2.3 What Loki, Alloy, and Grafana do

For the live log path:
- the app writes log lines
- **Alloy** tails the pod stdout and forwards the logs to **Loki**
- **Grafana** evaluates the Loki-based alert rule
- when the rule fires, **Grafana Alerting** sends a webhook to RCA

Important: RCA does **not** ingest the raw log stream from Grafana. It receives the **alert webhook**.

The validated Loki scenario is `DNSFailureLogSpike` on `user`.

### 2.4 What actually hits RCA backend

RCA backend accepts the supported alert payloads and creates an investigation.

The two demo entrypoints are:
- `POST /api/alerts/prometheus`
- `POST /api/alerts/grafana`

After that, the operator reads the investigation through:
- `GET /api/investigations/{investigation_id}`

That read endpoint is the real investigation surface for the presenter.

## 3. Recommended presenter run order

Use this order unless you already know the environment is degraded:

1. run the preflight
2. bring up the required port-forwards
3. demonstrate the **Prometheus path first**
4. if the environment is stable, demonstrate the **Grafana Loki path**
5. use the watch script to narrate the investigation until terminal status

Recommended story order in the room:
- start with the report-centric Prometheus flow
- then switch to the live Grafana webhook story
- end by showing the investigation read surface and report fields

## 4. Scripts and usage

### 4.1 Preflight

Check whether the demo is ready before you present:

```bash
scripts/demo-preflight.sh
```

What it does:
- checks `kubectl`
- checks the `demo`, `observability`, and `rca` namespaces
- checks the key workloads
- checks `rca-backend` health
- prints **GO** or **NO-GO** for the report-centric Prometheus path

Useful rerun example:

```bash
KUBECONFIG=~/demo.conf scripts/demo-preflight.sh
```

### 4.2 Direct Prometheus trigger

Use this when you want the strongest report-centric demo:

```bash
kubectl -n rca port-forward deploy/rca-backend 8000:8000
scripts/demo-trigger-prometheus.sh
```

What it does:
- POSTs the validated `DependencyTimeout` payload
- prints the HTTP status
- prints the `investigation_id`
- prints the next poll command

Useful rerun examples:

```bash
scripts/demo-trigger-prometheus.sh --help
scripts/demo-trigger-prometheus.sh --url http://localhost:8000
RCA_BACKEND_URL=http://localhost:8000 scripts/demo-trigger-prometheus.sh
```

### 4.3 Live Grafana Loki trigger

Use this when you want the live log-trigger story:

```bash
kubectl -n observability port-forward deploy/grafana 3000:3000
kubectl -n observability port-forward deploy/loki 3100:3100
kubectl -n rca port-forward deploy/rca-backend 8000:8000
scripts/demo-trigger-grafana.sh
```

What it does:
- injects DNS-failure logs into the `user` pod stdout
- waits for Loki ingestion and the Grafana alert hold window
- checks whether Grafana has a firing `DNSFailureLogSpike` alert
- checks whether the backend webhook was observable as `POST /api/alerts/grafana -> 202` when access logs are available

Useful rerun examples:

```bash
scripts/demo-trigger-grafana.sh --help
scripts/demo-trigger-grafana.sh --no-inject
scripts/demo-trigger-grafana.sh --count 12 --wait 180
WAIT=90 POLL=10 scripts/demo-trigger-grafana.sh
```

### 4.4 Watch one investigation

Use this after either trigger script returns an `investigation_id`:

```bash
scripts/demo-watch-investigation.sh <investigation_id>
```

Useful rerun examples:

```bash
scripts/demo-watch-investigation.sh <investigation_id> --once
scripts/demo-watch-investigation.sh <investigation_id> --poll 2 --timeout 600
BACKEND_URL=http://localhost:8000 scripts/demo-watch-investigation.sh <investigation_id>
```

What it shows:
- `status`
- `state_snapshot`
- `report`
- report highlights when the run produced one

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
- the Prometheus path returns `report=null` but you were planning to sell it as a report demo
- Grafana does not show the expected firing alert and you have no fresh evidence that the webhook path is still valid

## 6. Fallback guidance

If the environment is shaky:
- fall back to the **Prometheus path** first
- if the report is missing, downgrade the story to lifecycle-only
- do **not** claim the Grafana path proves raw-log ingestion into RCA; it proves the alert webhook path
- do **not** claim Kubernetes-event readiness from this guide; that path is outside the validated live story here

## 7. Short presenter script

A concise way to explain the flow:

> The demo stack emits metrics and logs. Prometheus turns the metric signal into a report-centric RCA trigger, while Alloy plus Loki plus Grafana turn a real log pattern into an alert webhook. RCA receives the alert, creates an investigation, and we inspect that investigation through the backend read API. For the strongest report story, I use the direct Prometheus path; for the live log story, I use the Grafana webhook path.

## 8. Cross-references

- `docs/demo-script.md`
- `docs/demo-operator-cheatsheet.md`
- `docs/demo-report-template.md`

## 9. Unresolved questions

- Which environment will host the rerun: local kind, shared cluster, or narrated evidence-only walkthrough?
- Do you want the presenter to prefer the Prometheus report story every time, or switch to Grafana when the live webhook path is freshly verified?
