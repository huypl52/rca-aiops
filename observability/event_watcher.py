"""observability/event_watcher — the ``kubernetes_event`` trigger source (Story 7.2).

One of the 3 trigger sources (AC2): watches Kubernetes Events in the ``demo``
namespace (``BackOff``/``OOMKilled``/``DeploymentReplicasNotUpdated`` — the §3.7
``crashloopbackoff``/``oom``/``bad_deployment_config`` surfaces) and POSTs each as a
valid Story-1.1 envelope to ``POST /api/events/kubernetes`` (source=kubernetes_event).

READ-TARGET infra (AD-3): the agent reads FROM the observation layer; it never writes
to it. This module imports NO agent code (gate #2 ``forbidden`` contract). The K8s
Event *read* (list/watch) is the watcher's OWN read — the read-only-investigator
deny-set (gate #1) binds the AGENT's tools, not this infra watcher.

Determinism (AD-12): :func:`event_to_ingest_payload` is a PURE, wall-clock-free
transform (no random / time / uuid / ``hash()``); :func:`forward_events` is order-stable.
The live cluster fetch is split out so the transform + forward path are testable
in-process WITHOUT a cluster — this dev env has no local K8s (kind/k3d/minikube/
kubectl absent), so the live watch is the runner's documented seam (see the README +
``observability/manifests/60-event-watcher.yaml``), and this module carries NO
``kubernetes`` import (the client is not a project dependency).

Never-raise (mirrors the agent's Constraint-5 on the infra side): a single bad event
or a failed POST is counted and skipped, never fatal to the watch loop.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol

import httpx

#: The Story-1.1 ingest endpoint this trigger source targets (source=kubernetes_event).
KUBERNETES_INGEST_PATH: str = "/api/events/kubernetes"

#: The namespace the watcher reads Events from (the 7.1 SUT namespace).
DEMO_NAMESPACE: str = "demo"

#: POST timeout for forwarding an event to the ingest endpoint (seconds).
_FORWARD_TIMEOUT: float = 2.0


class Poster(Protocol):
    """A callable that POSTs a JSON body to a URL and returns the HTTP status (0 = transport failure)."""

    def __call__(self, url: str, *, json: object) -> int: ...


@dataclass(frozen=True, slots=True)
class ForwardStats:
    """Aggregate outcome of one :func:`forward_events` pass."""

    forwarded: int
    skipped: int


def _as_mapping(value: object) -> Mapping[str, object]:
    """Return ``value`` as a mapping, else an empty mapping (no raise on bad shape)."""
    return value if isinstance(value, Mapping) else {}


def event_to_ingest_payload(event: Mapping[str, object]) -> dict[str, object]:
    """Pure, deterministic Kubernetes Event -> Story-1.1 ingest payload.

    Builds the payload shape :func:`services.normalize.normalize_kubernetes` reads
    (this module does NOT import that normalizer — the test round-trips through it):
    ``metadata.uid`` (trigger_id), ``reason`` (alert_name + canonical derivation),
    ``message`` (description), ``lastTimestamp``/``eventTime`` (started_at),
    ``involvedObject.name`` / ``labels.service`` (service), ``type`` (severity),
    ``labels``/``annotations``. No value coercion that would mask a malformed event
    — required fields pass through; the normalizer's validate-on-ingress (AD-9) is the
    single authority. If ``labels.service`` is absent it is seeded from
    ``involvedObject.name`` so the normalizer's service resolution succeeds.
    """
    metadata = _as_mapping(event.get("metadata"))
    labels_out: dict[str, object] = dict(
        _as_mapping(event.get("labels")) or _as_mapping(metadata.get("labels"))
    )
    involved = _as_mapping(event.get("involvedObject"))
    involved_name = involved.get("name")
    if isinstance(involved_name, str) and involved_name and "service" not in labels_out:
        labels_out = {**labels_out, "service": involved_name}
    return {
        "metadata": dict(metadata),
        "reason": event.get("reason", ""),
        "message": event.get("message", ""),
        "type": event.get("type", ""),
        "lastTimestamp": event.get("lastTimestamp", ""),
        "eventTime": event.get("eventTime", ""),
        "involvedObject": dict(involved),
        "labels": labels_out,
        "annotations": dict(
            _as_mapping(event.get("annotations")) or _as_mapping(metadata.get("annotations"))
        ),
    }


def httpx_post(url: str, *, json: object) -> int:
    """Default :class:`Poster`: POST via httpx, return status (0 on transport failure).

    Never raises — a transport failure returns 0 so :func:`forward_events` counts the
    event as skipped rather than aborting the watch (mirrors Constraint-5).
    """
    try:
        with httpx.Client(timeout=_FORWARD_TIMEOUT) as client:
            resp = client.post(url, json=json)
    except httpx.HTTPError:
        return 0
    return resp.status_code


def forward_events(
    events: Iterable[Mapping[str, object]],
    *,
    ingest_base_url: str,
    post: Poster,
) -> ForwardStats:
    """Transform + POST each event to the kubernetes ingest endpoint; never raises.

    Each event is mapped via :func:`event_to_ingest_payload` and POSTed to
    ``{ingest_base_url}{KUBERNETES_INGEST_PATH}``. A 2xx response counts as forwarded;
    any other status, a raising poster, or a transport failure (status 0) counts as
    skipped. A single bad event never aborts the watch loop.
    """
    url = ingest_base_url.rstrip("/") + KUBERNETES_INGEST_PATH
    forwarded = 0
    skipped = 0
    for event in events:
        payload = event_to_ingest_payload(event)
        try:
            status = post(url, json=payload)
        except Exception:
            skipped += 1
            continue
        if 200 <= status < 300:
            forwarded += 1
        else:
            skipped += 1
    return ForwardStats(forwarded=forwarded, skipped=skipped)


__all__ = [
    "DEMO_NAMESPACE",
    "ForwardStats",
    "KUBERNETES_INGEST_PATH",
    "Poster",
    "event_to_ingest_payload",
    "forward_events",
    "httpx_post",
]
