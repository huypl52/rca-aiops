# RCA backend deploy (Story 7.3 AC2)

Deploys the RCA **agent** (FastAPI `routers/` + LangGraph `graph/`) as Kubernetes Service
`rca-backend`, the sink the Story-7.2 trigger sources POST to. **The agent code is unchanged by
this story** — these artifacts only package the existing packages behind a `uvicorn` entrypoint.

## What this proves (and what it deliberately does NOT)

The deploy proves **wiring**, not working RCA:

- a 7.2 trigger source (or a `chaos.inject` payload) POSTs an alert/event →
  `202 InvestigationAccepted`;
- the backend runs the default dispatcher (`ContextBuilderRunner`, single node) and returns
  `status="success"` / `report=None`.

`report=None` is the **honest** POC result — no green RCA is manufactured. The graph is
non-convergent until the 5-A1 real-transport lands; durable storage (SqliteSaver) is Story 7.4.
Manufacturing a green RCA here would be fake-green; this is not.

## Namespace: `rca` (reconciliation)

The dispatch named "namespace demo", but **every** 7.2 trigger-source URL resolves
`rca-backend` in namespace **`rca`** (`rca-backend.rca.svc.cluster.local:8000` — the grafana
contact point, the prometheus scrape target, the event-watcher default ingest URL). Deploying in
`rca` keeps the existing wiring consistent; deploying in `demo` would have left those URLs
dangling. The agent is a service separate from the demo SUT (`demo`) and the observability stack
(`observability`), so a dedicated `rca` namespace is architecturally clean too. Recorded in the
Story 7.3 CS.

## RBAC: none now (least privilege)

The deployed backend's default dispatcher (`ContextBuilderRunner`) + canned transport
(`FakeReadOnlyTransport` / `StubReadOnlyAdapter`) make **no** cluster API calls — it reads
nothing from K8s. The `rca-backend` ServiceAccount therefore carries **no** ClusterRole.
Read-only `get`/`list`/`watch` RBAC (mirroring
`observability/manifests/00-namespace-rbac.yaml`) is added **with** the 5-A1 real-transport, not
speculatively before.

## Run (cluster-backed host — this POC dev env has no local K8s)

```bash
./deploy/deploy.sh
# equivalently:
docker build -t rca-backend:7.3 -f deploy/Dockerfile .
kubectl apply -f deploy/k8s/00-rca-backend.yaml
kubectl -n rca rollout status deployment/rca-backend
```

## Files

| file | role |
| --- | --- |
| `Dockerfile` | `python:3.12-slim` image; runtime deps; `PYTHONPATH=/app`, `PYTHONHASHSEED=42`; `CMD uvicorn routers.app:app` |
| `k8s/00-rca-backend.yaml` | namespace `rca` + ServiceAccount (no ClusterRole) + Deployment + Service:8000 |
| `deploy.sh` | build + apply + rollout; prints the honest smoke expected output |

## Determinism + chaos

The chaos layer (`chaos/`) is a separate package (a WRITE outside the agent's read-only
perimeter). It reproduces the trigger-source payloads this backend ingests — proven in-process
(`tests/test_chaos_inject.py`) for all 11 §3.7 scenarios, with no cluster. See the Story 7.3 CS.
