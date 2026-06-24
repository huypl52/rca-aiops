# observability/ — the READ-TARGET observation stack (Story 7.2)

The observability stack (**Prometheus / Alertmanager / Loki + Grafana Alloy / Grafana
Alerting / K8s Event Watcher**) standing up as **READ TARGETS** for the RCA agent's
read-only adapters (Story 2.2). It is **INFRA (the observation layer)**, like `demo/` is
infra (the SUT). It bridges **7.1 (the SUT) → the agent**: Prometheus scrapes the demo
services' `/metrics`; Loki + Alloy collect their structured JSON logs; the K8s Event Watcher
watches the `demo` namespace's events.

## The READ-TARGET role (the headline — Story 7.2 LOCK §1)

The stack is a **READ TARGET** for the agent's adapters, **NOT part of the agent**. The agent
(Epics 0–6, **UNCHANGED**, spine-13 frozen) *reads* evidence from it at runtime via its
read-only adapters (2.2); the stack imports/couples to **no** agent code — enforced by the
gate#2 `forbidden` contract (see `tests/ci/test_gate2_observability_boundary.py`).

**Read-only boundary (AD-3):** the agent reads **FROM** the stack; it **never** writes to it.
The stack's own writes (Prometheus TSDB ingest, Loki log shipping, the event watcher POSTing
to the Story-1.1 ingest endpoint) are the **stack's own** data paths, NOT the agent's. The
read-only deny-set (gate#1: no write/exec/patch/delete/scale/rollback/restart/remediate)
binds the **agent's investigation tools**, not this infra layer.

## The 3 trigger sources → Story-1.1 ingest (AC2)

The stack detects an anomaly and POSTs an incident to the **existing** Story-1.1 ingest
endpoints (1.1 endpoints **unchanged** — this is INFRA/config calling them, not an ingest-code
change):

| trigger source          | stack component            | ingest endpoint (Story 1.1)      | implementation      |
|-------------------------|----------------------------|----------------------------------|---------------------|
| `prometheus_alertmanager` | Alertmanager webhook      | `POST /api/alerts/prometheus`    | config (webhook)    |
| `grafana_alerting_loki`   | Grafana Alerting contact pt | `POST /api/alerts/grafana`       | config (webhook)    |
| `kubernetes_event`        | K8s Event Watcher         | `POST /api/events/kubernetes`    | Python (`event_watcher.py`) |

The two alert sources are **config-driven** (Alertmanager `webhook_configs` + Grafana contact
point, in `manifests/`). The `kubernetes_event` watcher is the one Python piece
(`event_watcher.py`) — a **pure, wall-clock-free** transform + a never-raise forward loop,
**testable in-process without a cluster**. Each trigger source produces a payload the 1.1
normalizer accepts → a valid `IncidentTrigger` (proven by round-trip tests).

## AC3 — adapter read path is INHERITED read-only, NOT a deployed real-transport demo

**Zero adapter re-wiring (Story 7.2 LOCK §4).** The agent's adapters (2.2) are read-only **by
construction** (`adapters/readonly.py` + `transport.py`; gate#1 enforces no write-verbs on the
agent's tools). AC3 ("adapter queries read-only") is satisfied by that **inherited capability**,
NOT by deploying a real-transport demo. Wiring the adapters from the eval's `ScenarioTransport`
to real Prometheus/Loki/K8s transports is **deferred to 5-A1**: the graph does not converge
(5-A1, SM-1=0%, measured in Epic 6), so real-transport wiring to a non-converging graph yields
the same honest-empty RCA the canned transport already produces, at high implementation cost.
This story deploys the read **targets**, not the convergence **content**.

## Data flow (7.1 → agent, REAL)

```
demo SUT (ns: demo)                 observability stack (ns: observability)        agent
 5 FastAPI svc ──/metrics──────────► Prometheus ──┐
   (render_prometheus)                             │
                 ──stdout JSON logs──► Alloy ──► Loki ──┐── read-only adapters (2.2) ──► agent
                 ──K8s Events────────► event-watcher ──┘
                                                      │
                            alerts ──► Alertmanager / Grafana Alerting ──webhook──► Story-1.1 ingest
```

## Determinism (AD-12 family)

`observability/event_watcher.py` is **wall-clock-free** (no `time`/`datetime`/`uuid`/`hash()`/
unseeded random; the pure `event_to_ingest_payload` + order-stable `forward_events`). The stack
configs themselves are exempt (stateful infra reality — Prometheus TSDB, Loki store); the
metrics/logs the stack *exposes* come from the 7.1 deterministic demo baseline, so the read
targets surface reproducible content. **7.2 introduces no new determinism gate** (unlike 7.1's
`python -m demo.model` proof).

## Environment caveat (honored, NOT faked)

This dev env has **no local K8s** (`kind`/`k3d`/`minikube`/`kubectl` absent; only `docker`).
Per the dispatch, the deliverable is **authored** here and **verified in-process** by the
Python test suite (`event_to_ingest_payload` / `forward_events` / round-trip → valid
`IncidentTrigger`). The live `kubectl apply` + real scraping (`deploy.sh`) is **not executed**
and **not** claimed green — reported, not invented.

## Deploy (where a kind cluster + the demo SUT exist)

```bash
bash observability/deploy.sh              # apply into ns `observability`, reads ns `demo`
UNINSTALL=1 bash observability/deploy.sh  # teardown
```

The event-watcher image (`observability/Dockerfile.event-watcher`, to be authored with the
image-build story) installs the `observability` package + the `kubernetes` runtime client.
The webhook/contact-point URLs target the **RCA backend Service** (`rca-backend.rca`,
port 8000), deployed in **Story 7.3** — until then the trigger configs are
wired-but-no-sink (a clean hand-off to 7.3).

## Layout

```
observability/
  __init__.py                 # package + read-target-role boundary docstring
  event_watcher.py            # kubernetes_event trigger source (TESTED, agent-free core)
  event_watcher_runner.py     # live cluster seam (lazy kubernetes client; not unit-tested)
  manifests/                  # gate-immune K8s manifests (ns `observability`, reads `demo`)
    00-namespace-rbac.yaml    # Namespace + read-only RBAC (no write verbs)
    10-prometheus.yaml        # metric read target + scrape rules (§3.7 alertnames)
    20-alertmanager.yaml      # prometheus_alertmanager trigger -> /api/alerts/prometheus
    30-loki-alloy.yaml        # log read target (Alloy collects demo stdout -> Loki)
    40-grafana.yaml           # grafana_alerting_loki trigger -> /api/alerts/grafana
    60-event-watcher.yaml     # kubernetes_event trigger -> /api/events/kubernetes
  deploy.sh                   # kind-based deploy (reported, not run in this env)
```

## Deferred (NOT 7.2)

- Real-transport adapter wiring (ScenarioTransport → Prometheus/Loki/K8s) → **5-A1** (post-convergence).
- RCA backend deploy (the `rca-backend` Service the webhooks target) → **Story 7.3**.
- `Dockerfile.event-watcher` + exact component versions / Helm chart → environment (Story 7.2 LOCK — DEFERRED).
