# Integration Execution Checklist

**Project:** 26-rca-aiops  
**Status:** Operator checklist for the remaining live run  
**Purpose:** Give a step-by-step checklist for the real Kubernetes integration run without repeating the broader onboarding docs.

## How to use this checklist

- Run the steps in order.
- Record PASS / FAIL / BLOCKED for each step.
- Do not move forward if a step is BLOCKED and the blocker is unresolved.
- Keep evidence links or command output with each step.

## 1. Host tooling

### Do
```bash
which docker kubectl kind
```

### PASS evidence
- `docker`, `kubectl`, and `kind` all resolve on the execution host.

### FAIL / BLOCKED evidence
- one or more tools are missing from `PATH`.

## 2. Cluster bootstrap

### Do
```bash
./demo/deploy.sh
./observability/deploy.sh
./deploy/deploy.sh
```

### PASS evidence
- each command exits 0
- `kubectl get ns demo observability rca` shows all namespaces
- `kubectl -n demo get deploy`, `kubectl -n observability get deploy`, and `kubectl -n rca get deploy` show ready workloads
- `kubectl -n rca get svc rca-backend` shows the backend service

### FAIL / BLOCKED evidence
- any deploy script exits non-zero
- any namespace, deployment, or service is missing
- the RCA backend image is not loaded into the cluster (ensure `kind load docker-image` succeeds or use a registry push)

### Note
- `deploy/deploy.sh` now includes `kind load docker-image rca-backend:7.3` (uncommented as of Phase 2). On a non-kind cluster, replace this with a registry push.
- The checked-in `deploy/k8s/00-rca-backend.yaml` includes `RCA_CHECKPOINT_DB` and `RCA_HYPOTHESIS_LLM_*` env vars. The `RCA_HYPOTHESIS_LLM_API_URL` uses the WSL2 gateway IP — replace it with the actual host IP or in-cluster proxy address in other environments.

## 3. Runtime mode validation

### Do
Check startup logs and environment for:
- `RCA_CHECKPOINT_DB`
- `RCA_HYPOTHESIS_LLM_ENABLED`
- `RCA_HYPOTHESIS_LLM_PROVIDER`
- `RCA_HYPOTHESIS_LLM_MODEL`
- `RCA_HYPOTHESIS_LLM_API_KEY`
- `RCA_HYPOTHESIS_LLM_API_URL`

The checked-in K8s manifest now includes `RCA_CHECKPOINT_DB` and `RCA_HYPOTHESIS_LLM_*` env vars (updated 2026-07-01). If these are present, the backend runs in durable/full-graph mode with the LLM planner seam enabled.

**LLM planner reachability:** the manifest sets `RCA_HYPOTHESIS_LLM_API_URL` to the WSL2 gateway IP (`http://10.255.255.254:8317`), which is reachable from inside kind pods. This IP is environment-specific — replace it with the actual host IP or in-cluster proxy address in other environments. Do not use `host.docker.internal` in kind on Linux/WSL2 (it does not resolve). See `docs/integration/runtime-and-environment-requirements.md` §3.3 for details.

### PASS evidence
- the team can state whether the backend is in minimal mode or durable/full-graph mode
- if grounded RCA is required, `RCA_CHECKPOINT_DB` is set and the durable path is intentionally active
- if the planner seam is enabled, the provider and model are explicit

### FAIL / BLOCKED evidence
- runtime mode is ambiguous
- the team assumes durable/full-graph mode without proving it
- planner/provider mode is used without explicit env evidence

## 4. Observability and readiness

### Phase 2 resolution notes (2026-07-01)

The three concerns from the initial live run have been resolved:

1. **Loki/Alloy**: both `1/1` ready. Loki uses in-memory ring KV; Alloy uses `v1.8.0` with simplified discovery. See `docs/integration/observability-contract.md` §2.4.
2. **Alertmanager 422**: fixed. The normalizer now unwraps the Alertmanager webhook envelope. Alertmanager-forwarded alerts return `202`. See `docs/integration/alert-payload-mapping.md` §3.
3. **LLM planner**: live and exercised. The API URL uses the WSL2 gateway IP (environment-specific — replace in other environments). The deterministic fallback remains as a safety net. See `docs/integration/runtime-and-environment-requirements.md` §3.3.

### Do
Use the supported trigger path and readiness docs:
- send one supported alert (direct `curl` POST or via Alertmanager — both paths now work)
- poll the investigation by `investigation_id`
- fill out `docs/integration/readiness-checklist.md`

### PASS evidence
- supported alert POST returns `202`
- response includes `investigation_id`
- `GET /api/investigations/{investigation_id}` returns a valid status record
- readiness checklist is completed honestly with PASS / PARTIAL / FAIL / N/A and blockers logged
- service / namespace identity is stable enough for deterministic evidence collection
- metrics, logs, and evidence are queryable for the incident window

### FAIL / BLOCKED evidence
- trigger POST does not return `202`
- investigation cannot be polled
- readiness checklist is incomplete or hand-wavy
- observability data is not queryable in the incident window

## 5. End-to-end RCA proof

### Do
Run one supported alert all the way to terminal RCA output.

### PASS evidence
- alert enters through the documented ingest path
- investigation runs to a defensible terminal state
- final RCA report is grounded and traceable
- report contains non-empty evidence-backed output for the validated path
- citations or raw excerpts point back to real evidence

### FAIL / BLOCKED evidence
- investigation stays partial with no grounded report
- report is empty, uncited, or not evidence-backed
- the flow succeeds only in a minimal wiring sense, not as grounded RCA

## 6. Stop conditions

Stop and mark the run BLOCKED if any of the following happen:
- host tooling is missing
- cluster bootstrap cannot complete
- runtime mode is ambiguous
- observability data is not available
- the alert path cannot reach a real investigation
- the report is not grounded in evidence

## 7. Minimal evidence bundle to save

Save these artifacts for the run record:
- host-tooling check output
- deploy script outputs
- `kubectl` namespace/deployment/service output
- runtime mode evidence from logs/env
- trigger request and `investigation_id`
- polling output for the investigation
- final RCA report output
- completed readiness checklist

## 8. Cross-references

- `docs/integration/index.md`
- `docs/integration/runtime-and-environment-requirements.md`
- `docs/integration/environment-bootstrap-runbook.md`
- `docs/integration/observability-contract.md`
- `docs/integration/readiness-checklist.md`
- `docs/aiops-integrated-acceptance-runbook.md`
- `docs/current-rca-runtime-truth-table.md`
