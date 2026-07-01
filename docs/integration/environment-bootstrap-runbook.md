# Environment Bootstrap Runbook

**Project:** 26-rca-aiops  
**Status:** Command-level bootstrap guide  
**Purpose:** Give operators a practical sequence for standing up the current Kubernetes-backed environment around the RCA backend.

## 1. What this runbook is for

Use this runbook when you want a **real cluster-backed environment** for RCA integration work, not just docs-only onboarding.

The authored environment has three layers:
- `demo` — the system under investigation
- `observability` — Prometheus, Alertmanager, Loki, Alloy, Grafana, event watcher
- `rca` — the RCA backend service

This runbook is Kubernetes-first.

Important scope note:
- this repo currently ships authored K8s manifests and deploy scripts
- it does **not** currently ship a checked-in docker-compose environment for the same flow

## 2. Prerequisites

Minimum prerequisites on the machine or host that will run the environment:
- `docker`
- `kind`
- `kubectl`

### Native Ubuntu/WSL install (recommended for this repo)

This repo's execution host is Ubuntu 24.04 on WSL2. Install the tools natively — do **not** use Homebrew/Linuxbrew on this path.

```bash
# docker: already available on this host (/home/vtit/bin/docker)
# If not present, use the official Docker Engine apt repo (not Docker Desktop)

# kubectl: download the Linux binary from the Google CDN mirror
curl -fsSL -o /tmp/kubectl "https://storage.googleapis.com/kubernetes-release/release/v1.30.0/bin/linux/amd64/kubectl"
sudo install -m 0755 /tmp/kubectl /usr/local/bin/kubectl

# kind: download the Linux binary from GitHub releases
curl -fsSL -o /tmp/kind "https://github.com/kubernetes-sigs/kind/releases/download/v0.24.0/kind-linux-amd64"
sudo install -m 0755 /tmp/kind /usr/local/bin/kind
```

Verify:
```bash
which docker kubectl kind
```

All three must resolve on `PATH` before proceeding to the bootstrap steps.

If the native download path is unreachable (e.g. network constraints), the fallback is to obtain the binaries from a local mirror or pre-provisioned host — not Homebrew.

Current host check in this session:
- `docker`: available
- `kind`: available
- `kubectl`: available

Recommended:
- a shell environment that can build local images
- enough local resources for the demo, observability stack, and backend together

If you are running commands through Claude Code in this session, use the `!` prefix so command output lands directly in the conversation.

## 3. Bootstrap order

Bring the environment up in this order:

1. `demo` namespace and demo services
2. `observability` namespace and read-target stack
3. `rca` namespace and backend
4. trigger-path and investigation-path verification
5. optional durable/full-graph and provider-backed planner wiring

Do not reverse the order casually:
- the observability layer expects the demo SUT to exist
- the observability trigger sources target `rca-backend.rca.svc.cluster.local:8000`

## 4. Step 1 — Deploy the demo SUT

Purpose:
- stand up the system under investigation in namespace `demo`

Repo asset:
- `demo/deploy.sh`

Command:

```bash
! ./demo/deploy.sh
```

What this script does:
- ensures a kind cluster exists
- builds `demo/app:latest`
- loads the image into kind
- applies `demo/k8s/`
- waits for rollouts
- does a small `/health` smoke via port-forward

Expected outcome:
- namespace `demo` exists
- deployments for `api-gateway`, `user`, `order`, `inventory`, `payment` are ready
- the traffic runner is present

See:
- `demo/README.md`
- `demo/k8s/`

## 5. Step 2 — Deploy the observability stack

Purpose:
- stand up the read-target observability components in namespace `observability`

Repo asset:
- `observability/deploy.sh`

Command:

```bash
! ./observability/deploy.sh
```

What this script does:
- ensures the kind cluster exists
- applies the demo SUT first if needed
- builds `observability/event-watcher:latest`
- loads it into kind
- applies `observability/manifests/`
- waits for rollouts
- performs a Prometheus scrape smoke check and exits non-zero if `demo` targets do not appear

Expected outcome:
- namespace `observability` exists
- deployments for `prometheus`, `alertmanager`, `loki`, `alloy`, `grafana`, and `event-watcher` are ready
- the stack can read the `demo` namespace

Key authored trigger paths in this layer:
- Alertmanager → `POST /api/alerts/prometheus`
- Grafana Alerting → `POST /api/alerts/grafana`
- event watcher → `POST /api/events/kubernetes`

See:
- `observability/README.md`
- `observability/manifests/20-alertmanager.yaml`
- `observability/manifests/40-grafana.yaml`
- `observability/manifests/60-event-watcher.yaml`

## 6. Step 3 — Deploy the RCA backend

Purpose:
- stand up the backend service in namespace `rca`

Repo asset:
- `deploy/deploy.sh`

Command:

```bash
! ./deploy/deploy.sh
```

Expected outcome:
- namespace `rca` exists
- deployment `rca-backend` is ready
- service `rca-backend` exists on port `8000`
- in-cluster DNS `rca-backend.rca.svc.cluster.local:8000` resolves

Important honesty note:
- the checked-in backend deploy proves wiring by default
- it does **not** automatically prove the richer validated grounded RCA path unless the environment also enables the durable/full-graph mode
- `deploy/deploy.sh` now includes `kind load docker-image rca-backend:7.3` (uncommented as of Phase 2). On a non-kind cluster, replace this with a registry push.
- `deploy/k8s/00-rca-backend.yaml` includes `RCA_CHECKPOINT_DB` and `RCA_HYPOTHESIS_LLM_*` env vars. The backend runs in durable/full-graph mode with the LLM planner seam enabled. The `RCA_HYPOTHESIS_LLM_API_URL` uses the WSL2 gateway IP — replace it with the actual host IP or in-cluster proxy address in other environments.

See:
- `deploy/README.md`
- `deploy/k8s/00-rca-backend.yaml`

## 7. Step 4 — Verify the environment basics

Run these checks after deployment.

### 7.1 Namespace check

```bash
! kubectl get ns demo observability rca
```

### 7.2 Rollout check

```bash
! kubectl -n demo get deploy
! kubectl -n observability get deploy
! kubectl -n rca get deploy
```

### 7.3 RCA service check

```bash
! kubectl -n rca get svc rca-backend
```

### 7.4 Observability wiring check

Good sanity checks include:

```bash
! kubectl -n observability get svc prometheus alertmanager loki grafana
! kubectl -n observability get deploy event-watcher
```

## 8. Step 5 — Verify ingest and investigation flow

### 8.1 Send a supported trigger

Use a supported ingest path, for example Prometheus alert ingestion.

Command pattern:

```bash
! curl -fsS -X POST http://127.0.0.1:8000/api/alerts/prometheus \
  -H 'content-type: application/json' \
  -d '{...}'
```

In a real cluster-backed setup you may instead port-forward or use an environment-specific ingress URL.

The important expected result is:
- HTTP `202`
- response body includes `investigation_id`

### 8.2 Poll the investigation

Command pattern:

```bash
! curl -fsS http://127.0.0.1:8000/api/investigations/<investigation_id>
```

Expected result:
- investigation record exists
- status is returned
- state snapshot is present
- report may be `null` or non-null depending on runtime mode and actual graph path

## 9. Step 6 — Enable the richer RCA path intentionally

If your goal is to reproduce the validated durable/full-graph RCA path, do not stop at a successful backend deployment.

You also need to wire:
- `RCA_CHECKPOINT_DB` for durable/full-graph mode
- provider-backed planner env vars if that mode is desired

Minimum practical interpretation:
- without `RCA_CHECKPOINT_DB`, you should assume minimal/default backend behavior
- with `RCA_CHECKPOINT_DB`, you can expect the durable/full-graph path to be wired in
- with the provider env enabled, you can exercise the planner seam that was live-validated on the seeded demo path

See:
- `docs/integration/runtime-and-environment-requirements.md`
- `docs/llm-hypothesis-planner-runtime-profile.md`

## 10. Environment outcomes to distinguish clearly

### Wiring-ready only
This means:
- namespaces are up
- services are reachable
- trigger POST returns `202`
- investigation polling works

This does **not** by itself mean grounded RCA is proven.

### RCA-ready on the richer path
This means:
- wiring-ready conditions are met
- durable/full-graph mode is intentionally enabled
- observability stack is actually feeding usable evidence
- the chosen scenario can progress from alert to investigation to grounded report

## 11. Common mistakes to avoid

- assuming backend deploy alone equals validated RCA
- assuming docker-only local setup equals the authored integrated environment
- enabling trigger sources without confirming the backend sink URL
- treating minimal-mode `success` as proof of grounded RCA quality
- skipping namespace/service verification before debugging payloads

## 12. Cross-references

- `docs/integration/runtime-and-environment-requirements.md`
- `docs/integration/observability-contract.md`
- `docs/integration/readiness-checklist.md`
- `docs/aiops-integrated-acceptance-runbook.md`
- `demo/README.md`
- `observability/README.md`
- `deploy/README.md`
