# Demo Operator Cheatsheet

**Project:** 26-rca-aiops  
**Status:** Command-first operator cheat sheet  
**Purpose:** Give the presenter one place for the practical demo checks and commands.

For validated-path truth, GO / NO-GO policy, and fallback rules, use `docs/demo/guide.md`.

## 1. Demo mode decision

Pick one before the session starts:
- **Mode A — lifecycle demo only**
- **Mode B — validated direct Prometheus demo with cited RCA report**
- **Mode C — validated live Grafana Loki trigger demo**

Quick rule:
- use Mode B when the Prometheus rehearsal path is still green
- use Mode C when the Grafana alert path is freshly re-verified
- downgrade to Mode A when the environment is unstable

## 2. Host/tooling checks

```bash
which docker kubectl kind
```

Expected:
- all three resolve on the execution host

Helper scripts:
- `scripts/demo-preflight.sh` — GO / NO-GO readiness check
- `scripts/demo-trigger-prometheus.sh` — send the validated `DependencyTimeout` trigger and print the `investigation_id`
- `scripts/demo-trigger-grafana.sh` — drive the live Grafana Loki trigger path
- `scripts/demo-watch-investigation.sh` — poll one investigation to terminal status and summarize the report surface

## 3. Deploy order

```bash
./demo/deploy.sh
./observability/deploy.sh
./deploy/deploy.sh
```

Expected:
- namespaces `demo`, `observability`, `rca` exist
- workloads are ready enough for the Prometheus path
- Grafana is provisioned enough for the Loki-trigger path

## 4. Fast sanity checks

```bash
kubectl get ns demo observability rca
kubectl -n demo get deploy
kubectl -n observability get deploy
kubectl -n rca get deploy
kubectl -n rca get svc rca-backend
```

## 5. Backend health check

```bash
kubectl -n rca port-forward deploy/rca-backend 8000:8000
curl http://localhost:8000/health
```

Expected:
```json
{"status":"ok"}
```

## 6. Runtime mode check

```bash
kubectl -n rca exec deploy/rca-backend -- env | grep RCA_
```

What to look for:
- `RCA_CHECKPOINT_DB`
- `RCA_HYPOTHESIS_LLM_ENABLED`
- `RCA_HYPOTHESIS_LLM_PROVIDER`
- `RCA_HYPOTHESIS_LLM_MODEL`
- `RCA_HYPOTHESIS_LLM_API_URL`

Fast interpretation:
- if `RCA_CHECKPOINT_DB` is present and the Prometheus rehearsal path still works, Mode B is viable
- if Grafana is healthy and the Loki rule is firing real alerts with `service=user`, Mode C is viable
- if backend `/metrics` still returns 404, do not claim backend self-metrics in the room

## 7. Send the demo trigger

### Mode B — direct Prometheus trigger

```bash
curl -X POST http://localhost:8000/api/alerts/prometheus \
  -H 'content-type: application/json' \
  -d '{"fingerprint":"demo-dependency-timeout-001","startsAt":"2026-07-01T10:00:00Z","labels":{"alertname":"DependencyTimeout","service":"order-service","severity":"critical","scenario":"dependency_timeout","namespace":"demo"},"annotations":{"summary":"upstream dependency timing out","description":"order -> payment upstream errors"}}'
```

Expected:
- HTTP `202`
- body contains `investigation_id`

### Mode C — live Grafana Loki trigger

Cause matching logs, then confirm Grafana created the live alert:
- `alertname=DNSFailureLogSpike`
- `service=user`
- backend access log shows `POST /api/alerts/grafana` → `202`

## 8. Poll the investigation

```bash
curl http://localhost:8000/api/investigations/<investigation_id>
```

Preferred helper:
```bash
scripts/demo-watch-investigation.sh <investigation_id>
```

Fast interpretation:
- `status=running` → keep polling
- `status=success` + `report=null` → lifecycle demo succeeded, full RCA report was not demonstrated
- `status=success` + non-null `report` → validated report-centric path succeeded
- `status=partial` → show the honest partial result
- `status=failed` → stop and record blocker

## 9. Common demo blockers

### Missing secret
`deploy/deploy.sh` requires `rca-backend-secrets` in namespace `rca`.

### Wrong deployment order
The observability layer expects the demo SUT first, and trigger sources expect the RCA backend DNS target.

### Wrong expectation of runtime mode
A healthy `202` + `investigation_id` response does not prove the full graph ran.

### Grafana regression
If Grafana regresses on the day, fall back to the Prometheus path.

### Kubernetes-event path not grounded
Do not present Kubernetes-event as a stakeholder-safe live-success story here.

### No local cluster tooling
If `kind` or `kubectl` is missing, switch to a narrated evidence walkthrough instead of pretending it is live.

## 10. Minimal evidence bundle to keep after the demo

- tooling check output
- deploy outputs
- namespace/deployment output
- runtime env output
- trigger request and response
- poll response(s)
- final verdict

## 11. Cross-references

- `docs/demo/guide.md`
- `docs/demo/presenter-script.md`
- `docs/integration/environment-bootstrap-runbook.md`
- `docs/operator-runbook.md`

## Unresolved questions

- Which exact RCA backend manifest/image tag will be used in the live demo?
- Will the presenter have cluster-admin access, or only namespace-scoped access?
- Is there a saved known-good `investigation_id` example for fallback narration?
