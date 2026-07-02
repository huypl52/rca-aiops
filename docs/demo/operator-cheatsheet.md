# Demo Operator Cheatsheet

**Project:** 26-rca-aiops  
**Status:** Command-first operator cheat sheet  
**Purpose:** Give the presenter one place for the practical demo checks and commands.

For validated-path truth, GO / NO-GO policy, and fallback rules, use `docs/demo/guide.md`.

This cheatsheet assumes the **full Kubernetes-backed demo environment**. A healthy local FastAPI process on `localhost:8000` is useful for smoke checks, but it is not enough to claim Mode B or Mode C demo readiness.

Default replay path for operators:
```bash
export RCA_HYPOTHESIS_LLM_API_KEY=<your-key>
export RCA_HYPOTHESIS_LLM_API_URL=<your-llm-endpoint>
scripts/demo-mode-b.sh
```

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
kubectl config current-context
kubectl cluster-info
kubectl get ns demo observability rca
```

Expected:
- all three binaries resolve on the execution host
- `kubectl` points at the intended demo context
- the cluster API is reachable
- namespaces `demo`, `observability`, and `rca` exist

If `kubectl cluster-info` fails, stop there. Do not reinterpret the problem as a missing namespace or a bad demo service.

Helper scripts:
- `scripts/demo-preflight.sh` — GO / NO-GO readiness check
- `scripts/demo-trigger-prometheus.sh` — send the validated `DependencyTimeout` trigger and print the `investigation_id`
- `scripts/demo-trigger-grafana.sh` — drive the live Grafana Loki trigger path
- `scripts/demo-watch-investigation.sh` — poll one investigation to terminal status and summarize the report surface

## 3. Deploy order

For the default replay, prefer:

```bash
scripts/demo-mode-b.sh
```

Manual order when debugging:

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
kubectl -n rca port-forward deploy/rca-backend 18000:8000
curl http://127.0.0.1:18000/health
```

Important:
- in this section, `127.0.0.1:18000` is expected to be the cluster-backed `port-forward`
- using a replay-owned port avoids colliding with an unrelated local FastAPI on port 8000

Expected:
```json
{"status":"ok"}
```

## 5.1 UI sanity check

```bash
curl -I http://127.0.0.1:18000/ui/
curl http://127.0.0.1:18000/ui/app.js
```

Expected:
- `/ui/` returns `200`
- `/ui/app.js` returns the shipped static client bundle
- opening `http://127.0.0.1:18000/ui/` uses the same origin as `/api`

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
curl -X POST http://127.0.0.1:18000/api/alerts/prometheus \
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
curl http://127.0.0.1:18000/api/investigations/<investigation_id>
```

Preferred helper:
```bash
scripts/demo-watch-investigation.sh <investigation_id>
```

Fast interpretation:
- `status=running` → keep polling
- `status=success` + `report=null` → lifecycle demo succeeded, full RCA report was not demonstrated
- `status=success` + non-null `report` → validated report-centric path succeeded
- current verified Grafana DNS rerun reached this state too, but still treat Mode B as the steadier report story
- `status=partial` → show the honest partial result
- `status=failed` → stop and record blocker

## 9. Common demo blockers

### Missing secret
`deploy/deploy.sh` requires `rca-backend-secrets` in namespace `rca`.
If the secret is absent, export `RCA_HYPOTHESIS_LLM_API_KEY` and `RCA_HYPOTHESIS_LLM_API_URL` before replay so the deploy script can create it automatically.

### Wrong deployment order
The observability layer expects the demo SUT first, and trigger sources expect the RCA backend DNS target.

### Wrong expectation of runtime mode
A healthy `202` + `investigation_id` response does not prove the full cluster-backed demo ran. It may only prove that a local backend on `localhost:8000` accepted the request.

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
