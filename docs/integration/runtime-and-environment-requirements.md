# Runtime and Environment Requirements

**Project:** 26-rca-aiops  
**Status:** Current-runtime environment guide  
**Purpose:** Explain what real environment must exist around the RCA backend so another team can integrate the RCA agents meaningfully.

## 1. Scope and stance

This document describes the **documented environment path today** for integrating the RCA backend into a real environment.

It is intentionally narrow:
- it describes the current runtime and authored deployment assets
- it is Kubernetes-first, not docker-compose-first
- it separates minimal backend wiring from the richer durable/full-graph RCA path
- it does not claim arbitrary target stacks are already certified

Use this doc together with:
- `docs/current-rca-runtime-truth-table.md`
- `docs/integration/environment-bootstrap-runbook.md`
- `docs/integration/observability-contract.md`
- `docs/integration/readiness-checklist.md`
- `docs/aiops-integrated-acceptance-runbook.md`

## 2. Environment model today

The authored environment in this repo is split into three concerns:

Current host check in this session:
- `docker`: available
- `kubectl`: available
- `kind`: available

All three tools are installed natively via Linux binaries (Ubuntu 24.04 WSL2). See `docs/integration/environment-bootstrap-runbook.md` for the native install commands.

### 2.1 `demo` namespace — system under investigation
This is the target workload analogue.

It contains the demo microservices whose alerts, metrics, logs, and events can drive investigations.

See:
- `demo/README.md`
- `demo/k8s/`

### 2.2 `observability` namespace — read-target observability stack
This is the observation layer the RCA backend reads from or receives triggers from.

Current authored components include:
- Prometheus
- Alertmanager
- Loki
- Grafana Alloy
- Grafana Alerting
- Kubernetes event watcher

See:
- `observability/README.md`
- `observability/manifests/`

### 2.3 `rca` namespace — RCA backend
This is where the RCA backend service is deployed.

Current authored backend service identity:
- `rca-backend`
- port `8000`
- in-cluster DNS: `rca-backend.rca.svc.cluster.local:8000`

See:
- `deploy/README.md`
- `deploy/k8s/00-rca-backend.yaml`

## 3. Runtime mode matrix

The most important operational truth is that simply deploying the backend does **not** automatically mean the validated grounded RCA path is active.

### 3.1 Minimal/default mode
Current default behavior without durable wiring:
- backend accepts triggers
- dispatcher uses the minimal runner path
- investigation lifecycle still exists
- this path is useful for wiring verification
- it is not the same as the richer validated RCA path

This is still the default when `RCA_CHECKPOINT_DB` is unset.

See:
- `services/durable.py`
- `routers/app.py`
- `docs/current-rca-runtime-truth-table.md`

### 3.2 Durable/full-graph RCA mode
The richer path requires explicit environment wiring.

Current documented gate:
- `RCA_CHECKPOINT_DB`

When set, the backend wires:
- durable SQLite checkpointing
- compiled graph runner
- cross-restart resume support

Without it, the backend remains on the minimal path.

See:
- `services/durable.py`
- `checkpoints/README.md`

### 3.3 Provider-backed planner seam
The planner LLM seam is opt-in, not default.

Useful environment toggles include:
- `RCA_HYPOTHESIS_LLM_ENABLED`
- `RCA_HYPOTHESIS_LLM_PROVIDER`
- `RCA_HYPOTHESIS_LLM_MODEL`
- `RCA_HYPOTHESIS_LLM_API_KEY`
- `RCA_HYPOTHESIS_LLM_API_URL`
- `OPENAI_API_URL`
- `OPENAI_API_MODEL`
- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`

Important scope note:
- if this seam is disabled or misconfigured, the planner falls back to deterministic behavior
- enabling the seam does not convert the whole RCA runtime into an LLM-native agent

In-cluster LLM planner reachability (resolved in Phase 2, 2026-07-01):
- the manifest now sets `RCA_HYPOTHESIS_LLM_API_URL=http://10.255.255.254:8317` — the WSL2 gateway IP, which is reachable from inside kind pods
- `host.docker.internal` does **not** resolve inside kind on Linux/WSL2; do not use it for in-cluster env vars
- the LLM planner seam is live: Phase 2 E2E proof shows LLM-generated hypothesis plans (e.g. `http_client_requests_total` with timeout/5xx code filters) that differ from the deterministic fallback's fixed query set
- the deterministic fallback in `graph/hypothesis_sources.py` remains as a safety net for provider timeout, error, or malformed output

**Environment-specific note:** the IP `10.255.255.254` is the WSL2 gateway address on this host. In other environments (bare metal, cloud VM, production), replace it with the actual host IP or an in-cluster proxy service address. Do not hardcode this IP in production deployments.

See:
- `graph/hypothesis_sources.py`
- `docs/llm-hypothesis-planner-runtime-profile.md`

## 4. Environment variables that matter most

| Variable | Meaning today | Needed for |
|---|---|---|
| `RCA_CHECKPOINT_DB` | Enables durable/full-graph RCA wiring | Validated durable RCA path |
| `RCA_HYPOTHESIS_LLM_ENABLED` | Turns on the provider-backed planner seam | Optional planner mode |
| `RCA_HYPOTHESIS_LLM_PROVIDER` | Chooses planner provider family | Optional planner mode |
| `RCA_HYPOTHESIS_LLM_MODEL` | Explicit planner model override | Optional planner mode |
| `RCA_HYPOTHESIS_LLM_API_KEY` | Explicit planner API key override | Optional planner mode |
| `RCA_HYPOTHESIS_LLM_API_URL` | Explicit planner API base override | Optional planner mode |
| `OPENAI_API_URL` | OpenAI-compatible base URL fallback | OpenAI-compatible planner mode |
| `OPENAI_API_MODEL` | OpenAI-compatible model fallback | OpenAI-compatible planner mode |
| `OPENAI_API_KEY` | OpenAI-compatible auth fallback | OpenAI-compatible planner mode |
| `ANTHROPIC_API_KEY` | Anthropic auth fallback | Anthropic planner mode |
| `DEMO_INGEST_URL` | Event watcher / observability-side sink URL | K8s event trigger path |

Interpretation:
- minimal backend boot does not require the full planner env set
- validated durable/full-graph RCA requires `RCA_CHECKPOINT_DB`
- provider-backed planning requires its own env gate and credentials

## 5. Ingress paths and operational endpoints

### 5.1 Supported ingest endpoints today
Current operator-facing ingress paths are:
- `POST /api/alerts/prometheus`
- `POST /api/alerts/grafana`
- `POST /api/events/kubernetes`

These are the supported ways external trigger sources hand incidents to the backend.

See:
- `routers/ingest.py`

### 5.2 Investigation polling endpoint
Operational read path today:
- `GET /api/investigations/{investigation_id}`

This is the current way to poll investigation status and inspect the bounded state snapshot/report.

See:
- `routers/investigations.py`

### 5.3 In-cluster backend service endpoint
The authored environment assumes a backend service reachable inside the cluster as:
- `http://rca-backend.rca.svc.cluster.local:8000`

That service identity is already referenced by the authored observability stack wiring.

See:
- `deploy/README.md`
- `observability/README.md`

## 6. Observability dependencies around the backend

The RCA backend is not useful in isolation. A meaningful integration environment needs surrounding observability components.

Current authored stack assumes:
- metrics source via Prometheus
- metric-alert trigger source via Alertmanager
- log source via Loki + Alloy
- log-alert trigger source via Grafana Alerting
- Kubernetes event trigger source via the event watcher

These are **read targets** or trigger sources for the agent, not pieces of the agent itself.

See:
- `observability/README.md`
- `observability/manifests/10-prometheus.yaml`
- `observability/manifests/20-alertmanager.yaml`
- `observability/manifests/30-loki-alloy.yaml`
- `observability/manifests/40-grafana.yaml`
- `observability/manifests/60-event-watcher.yaml`

## 7. Kubernetes-first, not compose-first

The documented environment path in this repo is Kubernetes-backed.

Current authored assets include:
- Kubernetes manifests for the backend
- Kubernetes manifests for the demo SUT
- Kubernetes manifests for the observability stack
- deploy scripts for those layers

Current repo limitation:
- there is no checked-in `docker-compose.yml` or equivalent compose bundle that represents the same end-to-end environment

So the safe statement is:
- Kubernetes-backed deployment is the documented path today
- docker-only local development is not the same thing as the authored integrated environment

## 8. Startup verification for a real environment

Use this as a short operator runbook after the environment is deployed.

### 8.1 Kubernetes layer
Verify:
- `demo`, `observability`, and `rca` namespaces exist where applicable
- deployments are ready
- services exist
- in-cluster DNS for the backend service is resolvable

### 8.2 Backend wiring layer
Verify:
- the backend is reachable on port `8000`
- the expected ingest routes are exposed
- logs/config clearly show whether `RCA_CHECKPOINT_DB` is set
- if durable RCA is expected, the environment explicitly provides the checkpoint DB path and storage

### 8.3 Trigger path verification
Verify:
- a supported trigger POST returns `202`
- response body includes `investigation_id`
- the corresponding `GET /api/investigations/{id}` path returns a valid status record

### 8.4 Mode verification
Verify separately whether the environment is only:
- minimal/wiring-ready

or actually:
- durable/full-graph RCA-ready

Do not assume the second from the first.

## 9. What this doc safely claims

Safe claims:
- the current authored environment is Kubernetes-first
- the backend service and ingress endpoints are concrete today
- the minimal path and durable/full-graph path are different runtime realities
- planner/provider behavior is env-gated and optional

Unsafe claims:
- the repo already ships a turnkey compose-based integration environment
- any backend deployment automatically enables grounded RCA behavior
- any target stack with alerts alone is ready for RCA acceptance
- broad production readiness is already certified

## 10. Recommended reading after this doc

1. `docs/integration/observability-contract.md`
2. `docs/integration/alert-payload-mapping.md`
3. `docs/integration/examples.md`
4. `docs/integration/readiness-checklist.md`
5. `docs/aiops-integrated-acceptance-runbook.md`

## Cross-references

- `docs/current-rca-runtime-truth-table.md`
- `docs/integration-readiness-gap-assessment.md`
- `docs/llm-hypothesis-planner-runtime-profile.md`
- `deploy/README.md`
- `observability/README.md`
- `demo/README.md`
