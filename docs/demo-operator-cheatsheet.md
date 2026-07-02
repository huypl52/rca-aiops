# Demo Operator Cheatsheet

**Project:** 26-rca-aiops  
**Status:** Short operator cheat sheet  
**Purpose:** Give the presenter one place for the practical demo checks and commands.

## 1. Use this sheet for

Use this only for the current live demo story:
- trigger A: `DependencyTimeout`
- service A: `order-service`
- path A: direct Prometheus alert → investigation → cited RCA report
- trigger B: `DNSFailureLogSpike`
- service B: `user`
- path B: live Grafana Loki alert → backend ingest acceptance

If runtime mode differs, downgrade to lifecycle-only or re-rehearse before presenting.

## 2. Demo scope decision

Pick one before the session starts:
- **Mode A — lifecycle demo only**
- **Mode B — validated direct Prometheus demo with cited RCA report**
- **Mode C — validated live Grafana Loki trigger demo**

Do not promise Mode B unless the rehearsed Prometheus path still returns a non-null `report`.
Do not promise Mode C unless the Grafana rule has already been re-verified as a real live alert path on the chosen environment.

## 3. Host/tooling checks

```bash
which docker kubectl kind
```

Expected:
- all three resolve on the execution host

Helper scripts (run on the demo host; thin bash, no deps beyond `kubectl`/`curl`):
- `scripts/demo-preflight.sh` — checks `demo`/`observability`/`rca` namespaces, key deployments, and `rca-backend` `/health`, then prints a GO / NO-GO summary (exit 0 = GO). Replaces the manual §5/§6 checks.
- `scripts/demo-trigger-prometheus.sh` — POSTs the validated `DependencyTimeout` payload (§8, Mode B), prints HTTP status + `investigation_id`, and the next poll command. Backend URL override: `-u URL` or `RCA_BACKEND_URL` (default `http://localhost:8000`).

## 4. Deploy order

```bash
./demo/deploy.sh
./observability/deploy.sh
./deploy/deploy.sh
```

Expected:
- all scripts exit 0 where applicable
- namespaces `demo`, `observability`, `rca` exist
- workloads are ready enough for the Prometheus path
- Grafana is expected to provision and can now support the validated live Loki-trigger demo path
- Kubernetes-event path is not a live-success claim in this environment

## 5. Fast sanity checks

```bash
kubectl get ns demo observability rca
kubectl -n demo get deploy
kubectl -n observability get deploy
kubectl -n rca get deploy
kubectl -n rca get svc rca-backend
```

If you need to inspect observability readiness, check Prometheus first for the report-centric path, then Grafana for the live log-trigger path.

## 6. Backend health check

```bash
kubectl -n rca port-forward deploy/rca-backend 8000:8000
curl http://localhost:8000/health
```

Expected:
```json
{"status":"ok"}
```

## 7. Runtime mode check

```bash
kubectl -n rca exec deploy/rca-backend -- env | grep RCA_
```

What to look for:
- `RCA_CHECKPOINT_DB`
- `RCA_HYPOTHESIS_LLM_ENABLED`
- `RCA_HYPOTHESIS_LLM_PROVIDER`
- `RCA_HYPOTHESIS_LLM_MODEL`
- `RCA_HYPOTHESIS_LLM_API_URL`

Interpretation:
- if `RCA_CHECKPOINT_DB` is present and the Prometheus rehearsal path still works, use Mode B
- if Grafana is healthy and the Loki rule is firing real alerts with `service=user`, Mode C is available
- if Grafana is erroring or absent, keep Grafana out of the live narrative
- if backend `/metrics` still returns 404, do not claim backend self-metrics as part of the demo

## 8. Send the demo trigger

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

## 9. Poll the investigation

```bash
curl http://localhost:8000/api/investigations/<investigation_id>
```

What to show:
- `status`
- `state_snapshot`
- `report`

Interpretation:
- `status=running`: keep polling
- `status=success` + `report=null`: lifecycle demo succeeded, full RCA report was not demonstrated
- `status=success` + non-null `report`: validated live path succeeded
- `status=partial`: show the honest partial result and do not switch to Grafana or Kubernetes-event claims
- `status=failed`: stop and record blocker

## 10. If the report is present, highlight only these fields

- `root_cause`
- `evidence_backing`
- `confidence`
- `open_questions`
- `uncertainty`
- `remediation`

Call out:
- evidence citations matter more than prose
- remediation stays empty in this POC

## 11. If the report is absent, say this clearly

Use wording close to this:

> The current environment proved supported ingestion and investigation lifecycle, but this run did not execute the validated cited RCA output path. We do not fabricate a report where the runtime did not produce one.

## 12. Common demo blockers

### Missing secret
`deploy/deploy.sh` requires `rca-backend-secrets` in namespace `rca`.

### Wrong deployment order
The observability layer expects the demo SUT first, and trigger sources expect the RCA backend DNS target.

### Wrong expectation of runtime mode
A healthy `202` + `investigation_id` response does not prove the full graph ran.

### Grafana regression
If Grafana regresses on the day, fall back to the Prometheus path. Do not keep the Grafana claim unless the active alert and backend `202` are visible again.

### Kubernetes-event path not grounded
The current rehearsal did not validate a stakeholder-safe Kubernetes-event RCA report.

### No local cluster tooling
If `kind` or `kubectl` is missing, switch to a narrated evidence walkthrough instead of pretending it is live.

## 13. Minimal evidence bundle to keep after the demo

- tooling check output
- deploy outputs
- namespace/deployment output
- runtime env output
- trigger request and response
- poll response(s)
- final verdict: lifecycle-only success, validated direct Prometheus success, validated live Grafana trigger success, partial, failed, or blocked

## 14. Cross-references

- `docs/demo-script.md`
- `docs/integration/environment-bootstrap-runbook.md`
- `docs/integration/execution-checklist.md`
- `docs/operator-runbook.md`

## Unresolved questions

- Which exact RCA backend manifest/image tag will be used in the live demo?
- Will the presenter have cluster-admin access, or only namespace-scoped access?
- Is there a saved known-good `investigation_id` example for fallback narration?
