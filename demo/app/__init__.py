"""demo.app — thin FastAPI shells over the deterministic :mod:`demo.model` (Story 7.1).

The 5 microservices (api-gateway, user, order, inventory, payment) are the
SYSTEM-UNDER-INVESTIGATION, NOT the RCA agent (see :mod:`demo`). Each is a thin
FastAPI app that exposes health/metrics/info + domain routes; the routes that
have dependencies (``order`` → inventory + payment; ``api-gateway`` → all four)
make the REAL inter-service HTTP calls (via httpx), so a fault on a downstream
service degrades its callers — the §3.7 propagation the benchmark needs.

Determinism: the metric VALUES are request-counters incremented from the live
``ServiceSnapshot`` (the same type :mod:`demo.model` replays in the pure test).
The PURE model (:func:`demo.model.healthy_blob`) — not the live HTTP path — is
what the determinism test proves byte-stable; live HTTP timing is the Story 7.3
tolerance concern, not a 7.1 determinism concern.
"""

from __future__ import annotations

from demo.app.factory import create_app

__all__ = ["create_app"]
