"""demo/app/factory — the shared FastAPI app factory for the 5 demo services (Story 7.1).

``create_app(name)`` builds the app for one of the 5 services. Shared endpoints
(``/health``, ``/metrics``, ``/``) + per-service domain routes. Services with
dependencies make live inter-service HTTP calls (httpx) realizing the topology
locked in :mod:`demo.topology`. The factory imports ONLY stdlib + fastapi/httpx +
``demo.*`` — never the agent (enforced by gate #2).
"""

from __future__ import annotations

import itertools
import json
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from demo.model import ServiceSnapshot, render_prometheus
from demo.topology import DEPENDENCIES, NAMESPACE, SERVICE_PORTS, dependencies_of

_UPSTREAM_TIMEOUT: float = 2.0
_LOG_SEQ: itertools.count[int] = itertools.count(start=1)

# Per-service live metric snapshot (one process = one service; the in-process test
# builds all 5 in one process, keyed by name). Request-counters, never wall-clock.
_LIVE_SNAPSHOTS: dict[str, ServiceSnapshot] = {}


def _snapshot(service: str) -> ServiceSnapshot:
    snap = _LIVE_SNAPSHOTS.get(service)
    if snap is None:
        snap = ServiceSnapshot(service=service)
        _LIVE_SNAPSHOTS[service] = snap
    return snap


def _record(service: str, operation: str) -> ServiceSnapshot:
    snap = _snapshot(service)
    snap.requests_total += 1
    snap.operations_total[operation] = snap.operations_total.get(operation, 0) + 1
    return snap


def _record_upstream(snap: ServiceSnapshot, target: str, ok: bool) -> None:
    snap.upstream_calls_total[target] = snap.upstream_calls_total.get(target, 0) + 1
    if not ok:
        snap.upstream_errors_total[target] = snap.upstream_errors_total.get(target, 0) + 1


def log_event(service: str, level: str, event: str, **fields: object) -> None:
    """Emit a structured JSON log line (stdout → Loki in Story 7.2).

    Deterministic content: a monotonic ``seq`` (no wall-clock) + ``sort_keys``.
    """
    payload: dict[str, object] = {
        "seq": next(_LOG_SEQ),
        "service": service,
        "level": level,
        "event": event,
        **fields,
    }
    sys.stdout.write(json.dumps(payload, sort_keys=True) + "\n")
    sys.stdout.flush()


@dataclass(frozen=True, slots=True)
class UpstreamResult:
    """Outcome of one inter-service HTTP call (status 0 = transport failure)."""

    target: str
    status: int
    ok: bool


def _upstream_base(target: str) -> str:
    """In-cluster default ``http://{target}`` (K8s Service port 80); overridable by env."""
    env_key = f"DEMO_UPSTREAM_{target.replace('-', '_').upper()}"
    return os.environ.get(env_key, f"http://{target}")


def call_upstream(
    target: str, *, path: str, method: str = "GET", json_body: dict[str, object] | None = None
) -> UpstreamResult:
    """Make one inter-service HTTP call (synchronous — FastAPI runs sync handlers in a threadpool).

    A transport failure returns ``status=0, ok=False`` (never raises) so a fault on
    ``target`` degrades the caller gracefully rather than crashing it — mirroring
    the agent's Constraint-5 never-raise discipline on the demo side.
    """
    url = f"{_upstream_base(target)}{path}"
    try:
        with httpx.Client(timeout=_UPSTREAM_TIMEOUT) as client:
            resp = client.request(method, url, json=json_body)
    except httpx.HTTPError:
        return UpstreamResult(target=target, status=0, ok=False)
    return UpstreamResult(target=target, status=resp.status_code, ok=resp.is_success)


# --- Request bodies (Pydantic v2; mypy-strict friendly) ----------------------


class ReserveRequest(BaseModel):
    sku: str
    quantity: int = 1


class ChargeRequest(BaseModel):
    amount: int
    sku: str | None = None


class OrderRequest(BaseModel):
    user_id: int
    sku: str
    quantity: int = 1
    amount: int = 0


def create_app(name: str) -> FastAPI:
    """Build the FastAPI app for one of the 5 demo services."""
    if name not in DEPENDENCIES:
        raise ValueError(f"unknown demo service: {name!r}")
    deps = dependencies_of(name)
    port = SERVICE_PORTS[name]

    @asynccontextmanager
    async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # Live-only startup log (deterministic: a monotonic seq, no wall-clock). The
        # lifespan replaces the deprecated @app.on_event("startup") hook.
        log_event(name, "info", "service_started", dependencies=list(deps), port=port)
        yield

    app = FastAPI(
        title=f"demo/{name}",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=_lifespan,
    )

    @app.get("/health")
    def health() -> dict[str, object]:
        return {"status": "ok", "service": name, "namespace": NAMESPACE}

    @app.get("/")
    def root() -> dict[str, object]:
        return {"service": name, "namespace": NAMESPACE, "port": port, "dependencies": list(deps)}

    @app.get("/metrics", response_class=PlainTextResponse)
    def metrics() -> PlainTextResponse:
        return PlainTextResponse(
            content=render_prometheus({name: _snapshot(name)}, service=name),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    if name == "user":
        _user_routes(app)
    elif name == "inventory":
        _inventory_routes(app)
    elif name == "payment":
        _payment_routes(app)
    elif name == "order":
        _order_routes(app)
    elif name == "api-gateway":
        _gateway_routes(app)

    return app


def _user_routes(app: FastAPI) -> None:
    @app.get("/users/{user_id}")
    def get_user(user_id: int) -> dict[str, object]:
        _record("user", "get_user")
        log_event("user", "info", "get_user", user_id=user_id)
        return {"service": "user", "user_id": user_id, "name": f"user-{user_id}"}

    @app.post("/users")
    def create_user() -> dict[str, object]:
        _record("user", "create_user")
        log_event("user", "info", "create_user")
        return {"service": "user", "created": True}


def _inventory_routes(app: FastAPI) -> None:
    @app.get("/inventory/{sku}")
    def get_stock(sku: str) -> dict[str, object]:
        _record("inventory", "get_stock")
        # Deterministic stock from the sku suffix (no wall-clock, no global random).
        suffix = sku.rsplit("-", 1)[-1]
        stock = (int(suffix) * 7) % 100 if suffix.isdigit() else 0
        log_event("inventory", "info", "get_stock", sku=sku)
        return {"service": "inventory", "sku": sku, "stock": stock}

    @app.post("/inventory/reserve")
    def reserve(req: ReserveRequest) -> dict[str, object]:
        _record("inventory", "reserve")
        log_event("inventory", "info", "reserve", sku=req.sku, quantity=req.quantity)
        return {"service": "inventory", "sku": req.sku, "reserved": True}


def _payment_routes(app: FastAPI) -> None:
    @app.post("/payment/charge")
    def charge(req: ChargeRequest) -> dict[str, object]:
        _record("payment", "charge")
        log_event("payment", "info", "charge", amount=req.amount)
        return {"service": "payment", "amount": req.amount, "charged": True}

    @app.post("/payment/refund")
    def refund(req: ChargeRequest) -> dict[str, object]:
        _record("payment", "refund")
        log_event("payment", "info", "refund", amount=req.amount)
        return {"service": "payment", "amount": req.amount, "refunded": True}


def _order_routes(app: FastAPI) -> None:
    @app.post("/orders")
    def create_order(req: OrderRequest) -> dict[str, object]:
        snap = _record("order", "create_order")
        # REAL topology: order calls inventory (reserve) + payment (charge).
        reserve_body: dict[str, object] = {"sku": req.sku, "quantity": req.quantity}
        inv = call_upstream(
            "inventory", path="/inventory/reserve", method="POST", json_body=reserve_body
        )
        _record_upstream(snap, "inventory", inv.ok)
        charge_body: dict[str, object] = {"amount": req.amount, "sku": req.sku}
        pay = call_upstream("payment", path="/payment/charge", method="POST", json_body=charge_body)
        _record_upstream(snap, "payment", pay.ok)
        order_ok = inv.ok and pay.ok
        log_event(
            "order",
            "info" if order_ok else "error",
            "create_order",
            user_id=req.user_id,
            sku=req.sku,
            inventory_ok=inv.ok,
            payment_ok=pay.ok,
        )
        return {
            "service": "order",
            # Deterministic id (ord-sum, NOT hash() — PYTHONHASHSEED-safe; AD-12).
            "order_id": req.user_id * 1000 + (sum(ord(c) for c in req.sku) % 1000),
            "inventory": inv.ok,
            "payment": pay.ok,
        }

    @app.get("/orders/{order_id}")
    def get_order(order_id: int) -> dict[str, object]:
        _record("order", "get_order")
        return {"service": "order", "order_id": order_id, "status": "confirmed"}


def _gateway_routes(app: FastAPI) -> None:
    @app.post("/orders")
    def create_order(req: OrderRequest) -> dict[str, object]:
        snap = _record("api-gateway", "create_order")
        body: dict[str, object] = req.model_dump()
        result = call_upstream("order", path="/orders", method="POST", json_body=body)
        _record_upstream(snap, "order", result.ok)
        log_event("api-gateway", "info", "create_order", upstream_status=result.status)
        return {"service": "api-gateway", "upstream": "order", "ok": result.ok}

    @app.get("/users/{user_id}")
    def get_user(user_id: int) -> dict[str, object]:
        snap = _record("api-gateway", "get_user")
        result = call_upstream("user", path=f"/users/{user_id}", method="GET")
        _record_upstream(snap, "user", result.ok)
        log_event("api-gateway", "info", "get_user", upstream_status=result.status)
        return {"service": "api-gateway", "upstream": "user", "ok": result.ok, "user_id": user_id}

    @app.get("/inventory/{sku}")
    def check_inventory(sku: str) -> dict[str, object]:
        snap = _record("api-gateway", "check_inventory")
        result = call_upstream("inventory", path=f"/inventory/{sku}", method="GET")
        _record_upstream(snap, "inventory", result.ok)
        log_event("api-gateway", "info", "check_inventory", upstream_status=result.status)
        return {"service": "api-gateway", "upstream": "inventory", "ok": result.ok, "sku": sku}


__all__ = [
    "ChargeRequest",
    "OrderRequest",
    "ReserveRequest",
    "UpstreamResult",
    "call_upstream",
    "create_app",
    "log_event",
]
