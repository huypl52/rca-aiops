# Handoff and Maintenance Guide

**Project:** 26-rca-aiops  
**Status:** Operator and maintainer onboarding guide  
**Purpose:** Give a new operator or maintainer everything needed to bootstrap, verify, troubleshoot, and maintain the RCA system.

## 1. Quick start for a new operator

### 1.1 Read in this order

1. `docs/integration/index.md` — what the integration bundle covers and the verified proof state
2. `docs/current-rca-runtime-truth-table.md` — what the runtime actually does today
3. `docs/production-readiness-gap-assessment.md` — canonical production readiness verdict and gaps
4. `docs/operator-runbook.md` — canonical operator deployment handoff
5. `docs/integration/environment-bootstrap-runbook.md` — how to stand up the environment
6. `docs/integration/execution-checklist.md` — how to run and verify the RCA flow

### 1.2 Bootstrap the environment

```bash
# 1. Install prerequisites (native Ubuntu/WSL2 — no Homebrew)
#    See docs/integration/environment-bootstrap-runbook.md §2

# 2. Deploy in order
./demo/deploy.sh
./observability/deploy.sh
./deploy/deploy.sh

# 3. Verify
kubectl get ns demo observability rca
kubectl -n observability get deploy
kubectl -n rca get deploy rca-backend
kubectl -n rca get svc rca-backend
```

### 1.3 Run the RCA flow

```bash
# Port-forward the backend
kubectl -n rca port-forward svc/rca-backend 8000:8000 &

# Send a supported alert
curl -fsS -X POST http://127.0.0.1:8000/api/alerts/prometheus \
  -H 'content-type: application/json' \
  -d '{"fingerprint":"test-001",
       "startsAt":"2026-07-01T10:00:00Z",
       "labels":{"alertname":"DependencyTimeout","service":"order-service",
                 "severity":"critical","scenario":"dependency_timeout"},
       "annotations":{"summary":"upstream dependency timing out",
                      "description":"order -> payment upstream errors"}}'

# Poll the investigation
curl -fsS http://127.0.0.1:8000/api/investigations/<investigation_id>
```

## 2. Runtime modes

| Mode | Trigger | Behavior |
|---|---|---|
| Minimal (default) | `RCA_CHECKPOINT_DB` unset | `ContextBuilderRunner` — single-node, `status=success`, `report=null` |
| Durable/full-graph | `RCA_CHECKPOINT_DB` set | Full 8-node compiled graph with SQLite checkpointer, grounded RCA output |

The checked-in manifest sets `RCA_CHECKPOINT_DB=/tmp/rca-checkpoint.db`, so the backend runs in durable/full-graph mode by default.

### LLM planner seam

| State | Condition | Behavior |
|---|---|---|
| Disabled | `RCA_HYPOTHESIS_LLM_ENABLED` unset or false | Deterministic rule-based planner |
| Enabled + reachable | `RCA_HYPOTHESIS_LLM_ENABLED=true` + valid API URL + key | LLM-generated hypothesis plans |
| Enabled + unreachable | LLM call fails (DNS, timeout, auth) | Deterministic fallback — graph still converges |

The manifest enables the seam with `RCA_HYPOTHESIS_LLM_API_URL=http://10.255.255.254:8317`. **This IP is WSL2-gateway-specific.** Replace it with the actual host IP or in-cluster proxy address in other environments.

## 3. Environment-specific values to replace

| Value | Where | Replace with |
|---|---|---|
| `10.255.255.254` | `deploy/k8s/00-rca-backend.yaml` env `RCA_HYPOTHESIS_LLM_API_URL` | Host IP or in-cluster proxy service |
| `ccs-internal-managed` | `deploy/k8s/00-rca-backend.yaml` env `RCA_HYPOTHESIS_LLM_API_KEY` | Real API key from a Kubernetes Secret |
| `rca-demo` | `demo/deploy.sh`, `observability/deploy.sh` env `CLUSTER` | Your kind cluster name |
| `/tmp/rca-checkpoint.db` | `deploy/k8s/00-rca-backend.yaml` env `RCA_CHECKPOINT_DB` | PersistentVolume mount path for production |

## 4. Troubleshooting

### Backend pod won't start
- Check `kubectl -n rca describe pod -l app.kubernetes.io/name=rca-backend`
- `ImagePullBackOff`: ensure `kind load docker-image rca-backend:7.3` succeeded
- `CrashLoopBackOff`: check `kubectl -n rca logs deployment/rca-backend` for import or config errors

### Alertmanager 422 errors
- Should not occur after Phase 2 (envelope unwrapping added)
- If they reappear: check `kubectl -n observability logs deployment/alertmanager` for the 422 detail
- Verify `services/normalize.py` has `_unwrap_alertmanager_envelope()`

### Loki won't start
- Check `kubectl -n observability logs deployment/loki`
- Ring errors: verify `common.ring.kvstore.store: inmemory` is present in the Loki ConfigMap
- If using a different Loki version, verify single-binary ring config for that version

### Alloy won't start
- Check `kubectl -n observability describe pod -l app.kubernetes.io/name=alloy`
- Image not found: verify `grafana/alloy:v1.8.0` exists on Docker Hub (Alloy uses `v`-prefixed tags)
- Config errors: check River config syntax for the Alloy version in use

### LLM planner not exercised
- Check `kubectl -n rca exec deployment/rca-backend -- env | grep RCA_HYPOTHESIS_LLM`
- Verify `RCA_HYPOTHESIS_LLM_API_URL` is reachable from inside the cluster
- `host.docker.internal` does not resolve in kind on Linux/WSL2 — use the host IP directly
- The deterministic fallback will mask the failure; check investigation output for LLM-generated queries to confirm the seam is live

### Investigation stays partial
- Poll again: `curl http://127.0.0.1:8000/api/investigations/<id>`
- Check backend logs for exceptions
- Verify `RCA_CHECKPOINT_DB` is set (durable mode required for full graph)

### Grafana stale replica
- `kubectl -n observability get pods -l app.kubernetes.io/name=grafana` may show two pods, one in CrashLoopBackOff
- Delete the old deployment: `kubectl -n observability delete deploy grafana-759cb9c6d6` if the stale replica persists

## 5. Maintenance tasks

### Rebuild the backend image
```bash
docker build -t rca-backend:7.3 -f deploy/Dockerfile .
kind load docker-image rca-backend:7.3 --name rca-demo
kubectl -n rca rollout restart deployment/rca-backend
```

### Update the floor registry
- Edit `config/floor_registry.yaml`
- Add or update rules for new incident classes
- Run tests: `python3 -m pytest tests/ -k floor -v`

### Add a new incident class
1. Add the scenario → canonical mapping in `services/normalize.py` (`_SCENARIO_TO_CANONICAL`)
2. Add the alertname → canonical mapping in `_ALERT_TO_CANONICAL` if applicable
3. Add a floor rule in `config/floor_registry.yaml`
4. Write a test payload and verify ingestion returns 202
5. Run the full E2E flow to validate grounded output

### Clean up the environment
```bash
UNINSTALL=1 ./deploy/deploy.sh
UNINSTALL=1 ./observability/deploy.sh
UNINSTALL=1 ./demo/deploy.sh
kind delete cluster --name rca-demo
```

## 6. Key file map

| Need | File |
|---|---|
| Ingest endpoints | `routers/ingest.py` |
| Payload normalization | `services/normalize.py` |
| Investigation dispatch | `services/dispatch.py` |
| Durable mode wiring | `services/durable.py` |
| Graph compilation | `graph/compiled.py` |
| Hypothesis planner | `graph/nodes/hypothesis_planner.py` |
| LLM seam + fallback | `graph/hypothesis_sources.py` |
| Evidence normalization | `graph/nodes/evidence_normalizer.py` |
| Floor check | `graph/floor_check.py` |
| Floor registry | `config/floor_registry.yaml` |
| Tool execution | `tools/executors.py`, `tools/router.py` |
| RCA report writing | `graph/nodes/rca_writer.py` |
| Investigation read store | `routers/investigations.py` |
| K8s backend manifest | `deploy/k8s/00-rca-backend.yaml` |
| Observability manifests | `observability/manifests/` |

## 7. Test and validation

```bash
# Unit and integration tests
python3 -m pytest tests/ -v

# Specific areas
python3 -m pytest tests/ -k normalize -v
python3 -m pytest tests/ -k floor -v
python3 -m pytest tests/ -k dispatch -v
```

## 8. Cross-references

- `docs/integration/index.md` — integration bundle overview
- `docs/integration/execution-checklist.md` — live run checklist
- `docs/production-readiness-gap-assessment.md` — canonical production-readiness verdict
- `docs/operator-runbook.md` — canonical operator handoff and deployment runbook
- `docs/integration/readiness-gap-assessment.md` — detailed gap analysis
- `docs/integration/integrated-acceptance-runbook.md` — per-target acceptance
- `docs/integration/onboarding-checklist.md` — target onboarding checklist
