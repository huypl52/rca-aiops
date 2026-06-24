# `demo/` — the 5-microservice SYSTEM-UNDER-INVESTIGATION (Story 7.1)

> **NOT the RCA agent.** This is the demo *victim* system — 5 FastAPI microservices
> (`api-gateway`, `user`, `order`, `inventory`, `payment`) running in a local K8s
> namespace `demo`, emitting metrics/logs/K8s-state that the RCA agent (Epics 0-6,
> unchanged by this story) *investigates* at runtime via read-only adapters.

The read-only-investigator deny-set (gate #1: NO write/exec/patch/delete/scale/
rollback/restart/remediate) **does not apply here** — these are ordinary demo
services that read/write their own state and call each other. That constraint
applies only to the RCA agent.

## Boundary (the headline)

The demo is a **standalone deployable**: it imports **no agent code**
(`graph`/`services`/`routers`/`models`/`adapters`/`tools`/`eval`/`ci`/`config`).
This is enforced two ways:

1. **Build time** — `demo/Dockerfile` installs only `fastapi`/`uvicorn`/`httpx` and
   copies only `demo/` (no agent code enters the image).
2. **Import time** — the import-linter `forbidden` contract in `pyproject.toml`
   (gate #2) hard-fails if any `demo` module imports an agent module, with a negative
   test in `tests/ci/test_gate2_demo_boundary.py`.

## Dependency topology (REAL — supports spec §3.7)

```
api-gateway ──┬─► user
              ├─► inventory
              ├─► payment
              └─► order ──┬─► inventory
                          └─► payment
```

A fault on `payment` degrades `order` (`dependency_timeout`); a fault on `inventory`
degrades `order` (`inventory_reserve_failure`). Leaves (`user`/`inventory`/`payment`)
have no outbound deps. The graph is a DAG (asserted by `tests/test_demo_topology.py`).
See `demo/topology.py` for the locked data + queries.

## Determinism (AD-12 family extended to the demo system)

The "normal traffic" generator (`demo.model.generate_trace`) is a **seed-reproducible
pure function** — same `(seed, n)` → byte-identical trace across `PYTHONHASHSEED`. The
healthy baseline `render_prometheus(replay_trace(generate_trace(seed, n)))` is
byte-stable across `PYTHONHASHSEED={0,1,42}` — proven by the cross-process test
`tests/test_demo_model_determinism.py` (the demo analog of gate #6 §2C). No
unseeded `random`, no `time`/`datetime`, no `hash()`-on-strings, no wall-clock-based
counters in what the model produces. (`demo/runner.py` is wall-clock-free too; live
request pacing lives in the K8s shell entrypoint.)

## Local K8s layout

| Service | DNS / Service name | containerPort | pod `app` label | depends on |
|---|---|---|---|---|
| api-gateway | `api-gateway` | 8080 | `api-gateway` | user, inventory, payment, order |
| user | `user` | 8081 | `user-service` | — |
| order | `order` | 8082 | `order-service` | inventory, payment |
| inventory | `inventory` | 8083 | `inventory` | — |
| payment | `payment` | 8084 | `payment-service` | — |

- **Service/DNS names** use the locked *short* names → inter-service calls
  `http://<service>` (port 80) resolve in-cluster.
- **pod `app` labels** use the spec §3.7 `label_selector` forms (e.g. `order-service`,
  `payment-service`) so a future Story 7.3 chaos/k8s-adapter query resolves the same
  selectors the benchmark injects (`eval/scenarios.py`).
- **`demo.rca/service`** carries the short name (Service selector + topology).

## Deploy

Prerequisites: `docker`, `kind`, `kubectl`.

```bash
./demo/deploy.sh                 # create kind cluster + build + apply + wait + smoke
UNINSTALL=1 ./demo/deploy.sh     # tear down namespace 'demo'
```

All 6 workloads (5 services + `traffic-runner`) share one image (`demo/app:latest`),
built once from `demo/Dockerfile`; the service is selected per-Deployment via
`DEMO_MODULE`/`DEMO_PORT`.

## Observability surface (for Story 7.2)

- **Metrics** — `GET /metrics` on each service: Prometheus text exposition
  (`demo_requests_total`, `demo_operations_total`, `demo_upstream_calls_total`,
  `demo_upstream_errors_total`, `demo_healthy`). Counters/gauges only — no wall-clock.
- **Logs** — structured JSON lines to stdout (`{seq, service, level, event, …}`),
  `sort_keys`, no wall-clock → ready for Loki/Grafana Alloy.
- **K8s state** — emergent from the Deployments: readiness/liveness probes report
  phase/restarts/conditions; events on probe failures.

## ⚠️ Environment note (read before expecting a live cluster)

This repo's development environment has **no local K8s** (`kind`/`k3d`/`minikube`/
`kubectl` absent; only `docker` present). Per the Story 7.1 dispatch, the deliverable
is therefore **authored** here and verified **in-process** by the Python test suite
(FastAPI `TestClient` boots each service; the pure model is proven deterministic) —
the live `kubectl apply`/cluster smoke is **not executed** and is **not** claimed
green. Run `./demo/deploy.sh` in an environment that has `kind`+`kubectl` for the
live cluster.

## What this story does NOT do (deferred)

- Observability stack collection (Prometheus/Loki/K8s) → **Story 7.2**.
- Chaos/fault inject (the 11 §3.7 scenarios) + RCA backend deploy → **Story 7.3**.
- The honest-empty RCA behavior (SM-1=0%, the **5-A1 convergence-content** scope
  decision pending lee) — matters for demo value (7.3) / a future convergence epic,
  **not for 7.1**. The services here are healthy by design.
- `PYTHONHASHSEED=42` is fixed in the container for reproducibility; the code is
  proven correct across `{0,1,42}` by the determinism test.
