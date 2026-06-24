"""observability/event_watcher_runner — LIVE cluster seam for the kubernetes_event watcher.

The live fetch loop: lists Events in the ``demo`` namespace via the Kubernetes client and
feeds them to :func:`observability.event_watcher.forward_events`, which POSTs each as a
valid Story-1.1 envelope to ``POST /api/events/kubernetes`` (source=kubernetes_event).

This is RUNNER GLUE: the ``kubernetes`` client is a RUNTIME dependency of the watcher image,
NOT a project build dependency (it is absent in this dev env — ``kubernetes installed: False``).
The import is therefore lazy (``importlib``) so the package imports + type-checks cleanly
without the client. This runner is NOT unit-tested (no local K8s to exercise it) — it is
correct-by-construction, and the TESTED, agent-free core lives in
:mod:`observability.event_watcher` (``event_to_ingest_payload`` / ``forward_events``).
"""

from __future__ import annotations

import importlib
import os
from typing import Any

from observability.event_watcher import DEMO_NAMESPACE, ForwardStats, forward_events, httpx_post

#: Default RCA backend ingest base URL (Service deployed Story 7.3; overridable by env).
_DEFAULT_INGEST_BASE_URL = "http://rca-backend.rca.svc.cluster.local:8000"


def list_demo_events() -> list[dict[str, object]]:
    """List Events in the ``demo`` namespace via the Kubernetes client (lazy import).

    Returns each event as the dict shape :func:`event_to_ingest_payload` expects (the
    client's ``sanitize_for_serialization`` yields the raw object graph). Raises a clear
    ``RuntimeError`` if the ``kubernetes`` client is not installed in the image.
    """
    try:
        kc: Any = importlib.import_module("kubernetes.client")
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised only with the runtime dep
        raise RuntimeError(
            "the kubernetes client is a runtime dependency of the watcher image, not a project "
            "build dependency; install it in the image (pip install kubernetes) before running"
        ) from exc
    api = kc.CoreV1Api()
    raw = api.list_namespaced_event(namespace=DEMO_NAMESPACE)
    serialize = kc.ApiClient().sanitize_for_serialization
    return [serialize(item) for item in raw.items]


def run_once(ingest_base_url: str | None = None) -> ForwardStats:
    """Fetch demo Events once and forward each to the kubernetes ingest endpoint.

    ``ingest_base_url`` defaults to the ``DEMO_INGEST_URL`` env var (read at call time,
    not import time) so a process can be reconfigured without re-importing.
    """
    base = (
        ingest_base_url
        if ingest_base_url is not None
        else os.getenv("DEMO_INGEST_URL", _DEFAULT_INGEST_BASE_URL)
    )
    return forward_events(list_demo_events(), ingest_base_url=base, post=httpx_post)


def main() -> None:
    """One-shot fetch + forward (the manifest wraps this in a poll cadence)."""
    stats = run_once()
    print(f"event_watcher: forwarded={stats.forwarded} skipped={stats.skipped}")


if __name__ == "__main__":  # pragma: no cover - manifest entrypoint
    main()
