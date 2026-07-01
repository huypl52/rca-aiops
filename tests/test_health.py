"""Phase 3 — health endpoint test for Kubernetes probes."""

from fastapi.testclient import TestClient

from routers.app import create_app


def test_health_endpoint_returns_200() -> None:
    app = create_app()
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"


def test_health_endpoint_does_not_check_downstream() -> None:
    """Health endpoint should NOT depend on external services (no coupling)."""
    app = create_app()
    client = TestClient(app)
    # Multiple calls should all succeed (no state accumulation)
    for _ in range(5):
        response = client.get("/health")
        assert response.status_code == 200
