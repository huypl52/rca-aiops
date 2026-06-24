"""Story 7.1 — the 5 demo FastAPI services: shared endpoints + topology wiring.

Boots each service in-process with FastAPI's ``TestClient`` (no live cluster needed) and
asserts:
  - shared ``/health`` / ``/`` / ``/metrics`` contract on all 5 services;
  - ``/metrics`` is valid Prometheus text exposition;
  - the REAL inter-service topology is wired: ``order`` calls ``inventory`` + ``payment``
    via the ``call_upstream`` seam, and a fault on ``payment`` degrades the order (the
    §3.7 dependency_timeout headline) — proven with a monkeypatched seam, no HTTP server;
  - the gateway proxies ``create_order`` to ``order``;
  - inventory stock is derived deterministically (no wall-clock / global random).

``call_upstream`` is monkeypatched (not a live socket) so the topology wiring is proven
deterministically. ``_LIVE_SNAPSHOTS`` is cleared per wiring test for a clean baseline.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from demo.app import create_app
from demo.app.factory import _LIVE_SNAPSHOTS, UpstreamResult
from demo.topology import DEPENDENCIES, SERVICE_NAMES


def _client(name: str) -> TestClient:
    return TestClient(create_app(name))


@pytest.mark.parametrize("name", SERVICE_NAMES)
def test_health_contract(name: str) -> None:
    with _client(name) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["service"] == name
        assert body["namespace"] == "demo"


@pytest.mark.parametrize("name", SERVICE_NAMES)
def test_root_reports_locked_topology(name: str) -> None:
    with _client(name) as client:
        body = client.get("/").json()
        assert body["service"] == name
        assert body["namespace"] == "demo"
        assert tuple(body["dependencies"]) == DEPENDENCIES[name]


@pytest.mark.parametrize("name", SERVICE_NAMES)
def test_metrics_is_prometheus_exposition(name: str) -> None:
    with _client(name) as client:
        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/plain")
        text = resp.text
        assert "# HELP demo_requests_total" in text
        assert "# TYPE demo_operations_total counter" in text
        assert "# TYPE demo_healthy gauge" in text
        assert f'demo_healthy{{service="{name}"}} 1' in text


def test_order_wiring_fault_on_payment_degrades_order(monkeypatch: pytest.MonkeyPatch) -> None:
    _LIVE_SNAPSHOTS.clear()
    called: list[str] = []

    def fake_call_upstream(
        target: str, *, path: str, method: str = "GET", json_body: dict[str, object] | None = None
    ) -> UpstreamResult:
        called.append(target)
        ok = target != "payment"  # simulate payment down (the §3.7 dependency_timeout fault)
        return UpstreamResult(target=target, status=200 if ok else 0, ok=ok)

    monkeypatch.setattr("demo.app.factory.call_upstream", fake_call_upstream)

    with _client("order") as client:
        body = client.post(
            "/orders",
            json={"user_id": 7, "sku": "sku-042", "quantity": 2, "amount": 2000},
        ).json()
        metrics = client.get("/metrics").text

    # order really calls BOTH inventory and payment over the topology.
    assert set(called) == {"inventory", "payment"}
    # payment failure degrades the order; inventory still ok.
    assert body["inventory"] is True
    assert body["payment"] is False
    # the degradation is visible in the order's own metrics (upstream error recorded).
    assert "demo_upstream_errors_total" in metrics


def test_gateway_proxies_create_order_to_order(monkeypatch: pytest.MonkeyPatch) -> None:
    _LIVE_SNAPSHOTS.clear()
    called: list[tuple[str, str]] = []

    def fake_call_upstream(
        target: str, *, path: str, method: str = "GET", json_body: dict[str, object] | None = None
    ) -> UpstreamResult:
        called.append((target, method))
        return UpstreamResult(target=target, status=201, ok=True)

    monkeypatch.setattr("demo.app.factory.call_upstream", fake_call_upstream)

    with _client("api-gateway") as client:
        body = client.post(
            "/orders",
            json={"user_id": 1, "sku": "sku-001", "quantity": 1, "amount": 1000},
        ).json()

    assert ("order", "POST") in called
    assert body["upstream"] == "order"
    assert body["ok"] is True


def test_inventory_stock_is_deterministic() -> None:
    _LIVE_SNAPSHOTS.clear()
    with _client("inventory") as client:
        # stock = (int(suffix) * 7) % 100 — pure, no wall-clock / global random.
        assert client.get("/inventory/sku-010").json()["stock"] == 70
        assert client.get("/inventory/sku-003").json()["stock"] == 21
