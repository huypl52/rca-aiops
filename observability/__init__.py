"""observability — the READ-TARGET observation layer for the RCA agent (Story 7.2).

This package is the observability STACK (Prometheus / Alertmanager / Loki + Grafana
Alloy / Grafana Alerting / K8s Event Watcher) standing up as READ TARGETS for the
agent's read-only adapters (Story 2.2). It is INFRA (the observation layer), like
``demo/`` is infra (the SUT). It imports NO RCA-agent code (enforced by the gate #2
``forbidden`` contract in pyproject.toml — see ``tests/ci/test_gate2_observability_boundary.py``).

Boundary (AD-3 — read-only investigator, carried from the agent constraint): the
agent READS evidence FROM this stack; it NEVER writes to it. The stack's OWN writes
(Prometheus TSDB ingest, Loki log shipping, the event watcher's POST to the Story-1.1
ingest endpoint) are the STACK's own data paths, NOT the agent's. The read-only
deny-set (gate #1) binds the agent's investigation tools, not this infra layer.

Three trigger sources (AC2) feed the existing Story-1.1 ingest endpoints:
  - prometheus_alertmanager -> POST /api/alerts/prometheus   (Alertmanager webhook config)
  - grafana_alerting_loki   -> POST /api/alerts/grafana       (Grafana Alerting contact point)
  - kubernetes_event        -> POST /api/events/kubernetes    (this package's event watcher)

The two alert sources are CONFIG-driven (manifests under ``observability/manifests/``).
The kubernetes_event watcher is the one piece of Python here (``event_watcher.py``) — a
PURE, wall-clock-free transform + a never-raise forward loop, testable in-process
without a cluster (this dev env has no local K8s — live deploy is REPORTED, not faked).
"""

from observability.event_watcher import (
    DEMO_NAMESPACE,
    KUBERNETES_INGEST_PATH,
    ForwardStats,
    Poster,
    event_to_ingest_payload,
    forward_events,
    httpx_post,
)

__all__ = [
    "DEMO_NAMESPACE",
    "ForwardStats",
    "KUBERNETES_INGEST_PATH",
    "Poster",
    "event_to_ingest_payload",
    "forward_events",
    "httpx_post",
]
