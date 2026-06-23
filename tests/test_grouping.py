"""Story 1-2 — incident grouping H3: 1-trigger-1-investigation + idempotent trigger_id + 202.

Covers the grouping-specific ACs (service-level normalize behavior is in
`test_ingest_normalize.py` and is UNCHANGED by 1-2):
  - AC1 — H3 1:1: distinct trigger_id → distinct investigation_id; registry 1:1.
  - AC2 — Idempotent on `trigger_id` (AD-10 #1): re-send → SAME investigation_id,
    registry size does NOT grow (runtime proof).
  - AC3 — Router returns `202 Accepted + {investigation_id}` (wraps 1-1 normalizer).
  - AC4 — `incident_id == investigation_id` (H3 POC contract lock) set on the trigger.
  - AC5 — Non-blocking 202 (async contract); scope kept (no graph/worker/read-store).
  - AC6 — Reject path does NOT mint an investigation_id.
  - AC7 — gate #2 one-way: grouping in `services/`, no graph/adapters/tools import.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from models import IncidentTrigger
from routers.app import create_app
from services.grouping import (
    InvestigationRegistry,
    default_registry,
    group,
    reset_registry,
)
from services.normalize import normalize_grafana, normalize_prometheus

# --- shared raw payloads (mirror test_ingest_normalize.py shapes) ---------------------------

PROM_DEP_TIMEOUT: dict[str, object] = {
    "fingerprint": "fp-dep-timeout-001",
    "status": "firing",
    "labels": {
        "alertname": "DependencyTimeout",
        "severity": "critical",
        "service": "order-service",
        "namespace": "demo",
        "scenario": "dependency_timeout",
    },
    "annotations": {
        "summary": "order-service dependency timeout",
        "description": "Downstream dependency timeout firing on order-service",
    },
    "startsAt": "2026-06-24T10:00:00Z",
    "endsAt": "2026-06-24T10:05:00Z",
}

PROM_PAYMENT_FAILURE: dict[str, object] = {
    "fingerprint": "fp-payment-002",
    "status": "firing",
    "labels": {
        "alertname": "PaymentFailureHigh",
        "severity": "critical",
        "service": "payment-service",
        "namespace": "demo",
        "scenario": "payment_failure",
    },
    "annotations": {
        "summary": "payment failure rate high",
        "description": "payment_failed_total above threshold",
    },
    "startsAt": "2026-06-24T10:00:00Z",
}


@pytest.fixture(autouse=True)
def _isolate_registry() -> Iterator[None]:
    """Reset the shared in-process registry between tests (idempotency store isolation)."""
    reset_registry()
    yield
    reset_registry()


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


def _is_uuid_v4(value: str) -> bool:
    return (
        re.match(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
            value,
        )
        is not None
    )


# ---------------------------------------------------------------------------
# AC1 — H3 1:1: distinct trigger_id → distinct investigation_id; registry 1:1.
# ---------------------------------------------------------------------------


def test_distinct_triggers_open_distinct_investigations() -> None:
    t_a = normalize_prometheus(dict(PROM_DEP_TIMEOUT))  # trigger_id fp-dep-timeout-001
    t_b = normalize_prometheus(dict(PROM_PAYMENT_FAILURE))  # trigger_id fp-payment-002

    id_a = group(t_a)
    id_b = group(t_b)

    assert id_a != id_b  # H3: no collapse to a shared investigation
    assert _is_uuid_v4(id_a) and _is_uuid_v4(id_b)
    # Registry is 1:1: exactly one investigation per distinct trigger_id.
    registry = default_registry()
    assert len(registry) == 2
    assert registry.investigation_id_for("fp-dep-timeout-001") == id_a
    assert registry.investigation_id_for("fp-payment-002") == id_b


def test_registry_is_one_to_one_not_merge() -> None:
    # D9 / FR-2: NO multi-trigger merge. Three distinct trigger_ids → three distinct
    # investigation_ids; the registry never maps two trigger_ids to one investigation.
    registry = InvestigationRegistry()
    ids = {registry.get_or_open(f"fp-{i:03d}") for i in range(3)}
    assert len(ids) == 3
    assert len(registry) == 3


# ---------------------------------------------------------------------------
# AC2 — Idempotent on trigger_id (AD-10 #1): runtime proof (registry size + identical id).
# ---------------------------------------------------------------------------


def test_resend_same_trigger_id_is_idempotent_no_new_investigation() -> None:
    # Re-send the same trigger_id (Alertmanager retry / dedupe path) N times → the SAME
    # investigation_id, and the registry does NOT grow (no new investigation opened).
    trigger = normalize_prometheus(dict(PROM_DEP_TIMEOUT))

    registry = default_registry()
    assert len(registry) == 0
    first = group(trigger)
    assert len(registry) == 1

    # Re-send the same trigger_id several times (fresh normalize → same trigger_id).
    for _ in range(4):
        resend = normalize_prometheus(dict(PROM_DEP_TIMEOUT))
        again = group(resend)
        assert again == first  # AD-10 #1: identical investigation_id
        assert resend.incident_id == first

    assert len(registry) == 1  # runtime proof: NO new investigation minted on re-send


def test_registry_instance_get_or_open_is_idempotent() -> None:
    # Pure registry-level idempotency (independent of the module singleton).
    registry = InvestigationRegistry()
    a = registry.get_or_open("fp-x")
    b = registry.get_or_open("fp-x")
    assert a == b
    assert len(registry) == 1
    assert "fp-x" in registry
    assert registry.investigation_id_for("fp-x") == a


def test_lookup_only_does_not_mint() -> None:
    registry = InvestigationRegistry()
    assert registry.investigation_id_for("never-seen") is None
    assert len(registry) == 0  # lookup did not create an entry


# ---------------------------------------------------------------------------
# AC4 — incident_id == investigation_id (H3 POC contract lock) set on the trigger.
# ---------------------------------------------------------------------------


def test_group_sets_incident_id_equal_to_investigation_id() -> None:
    trigger = normalize_grafana(
        {
            "fingerprint": "fp-dns-001",
            "labels": {
                "alertname": "DNSFailureLogSpike",
                "severity": "warning",
                "service": "user-service",
                "namespace": "demo",
                "scenario": "dns_failure",
            },
            "annotations": {"summary": "DNS spike", "description": "DNS logs surging"},
            "startsAt": "2026-06-24T10:00:00Z",
        }
    )
    assert trigger.incident_id is None  # normalize never sets it (pre-group)

    investigation_id = group(trigger)

    # H3 POC: incident_id and investigation_id are ONE grouping identifier.
    assert trigger.incident_id == investigation_id
    assert trigger.incident_id is not None
    assert _is_uuid_v4(investigation_id)


def test_incident_trigger_18_field_contract_unchanged() -> None:
    # gate #5 no-regression: grouping SETS incident_id (H3 add-on) but does NOT add a
    # §3.4 field. The 18 §3.4 fields stay exactly 18; incident_id is the separate H3 add-on.
    trigger = normalize_prometheus(dict(PROM_DEP_TIMEOUT))
    group(trigger)
    spec_fields = set(IncidentTrigger.model_fields.keys()) - {"incident_id"}
    assert len(spec_fields) == 18  # §3.4 = 18 (incident_id NOT counted — lesson D-1)
    assert trigger.incident_id is not None  # H3 add-on set, but not a §3.4 field


# ---------------------------------------------------------------------------
# AC3 + AC5 — Router: 202 Accepted + {investigation_id}; non-blocking (no graph side-effect).
# ---------------------------------------------------------------------------


def test_endpoint_success_returns_202_with_investigation_id(client: TestClient) -> None:
    resp = client.post("/api/alerts/prometheus", json=PROM_DEP_TIMEOUT)
    assert resp.status_code == 202, resp.text  # AD-10 #2 async contract (upgrades 1-1's 200)
    body = resp.json()
    assert set(body.keys()) == {"investigation_id"}
    assert _is_uuid_v4(body["investigation_id"])


def test_http_resend_same_trigger_id_returns_same_investigation_id(
    client: TestClient,
) -> None:
    # End-to-end idempotency through the registry: same raw payload (same fingerprint) →
    # same investigation_id across two HTTP requests in the same process.
    first = client.post("/api/alerts/prometheus", json=PROM_DEP_TIMEOUT).json()
    second = client.post("/api/alerts/prometheus", json=PROM_DEP_TIMEOUT).json()
    assert first["investigation_id"] == second["investigation_id"]
    assert len(default_registry()) == 1  # one investigation, not two


def test_http_distinct_triggers_return_distinct_investigation_ids(
    client: TestClient,
) -> None:
    a = client.post("/api/alerts/prometheus", json=PROM_DEP_TIMEOUT).json()
    b = client.post("/api/alerts/prometheus", json=PROM_PAYMENT_FAILURE).json()
    assert a["investigation_id"] != b["investigation_id"]
    assert len(default_registry()) == 2


def test_handler_does_not_import_graph_layer() -> None:
    # AC5 scope: the 202 is non-blocking and the grouping layer never reaches the graph.
    # The ingest router + grouping service MUST NOT import graph/adapters/tools (gate #2),
    # so by construction no graph/node can be invoked from the ingest path in this story.
    import routers.ingest as ingest_mod
    import services.grouping as grouping_mod

    def imported_roots(source: str) -> set[str]:
        tree = ast.parse(source)
        roots: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots.add(node.module.split(".")[0])
        return roots

    for module in (ingest_mod, grouping_mod):
        assert module.__file__ is not None
        roots = imported_roots(Path(module.__file__).read_text(encoding="utf-8"))
        forbidden = roots & {"graph", "adapters", "tools"}
        assert not forbidden, f"{module.__name__} imports forbidden layer(s): {forbidden}"


# ---------------------------------------------------------------------------
# AC6 — Reject path does NOT mint an investigation_id (grouping not reached on invalid).
# ---------------------------------------------------------------------------


def test_reject_on_missing_field_does_not_open_investigation(client: TestClient) -> None:
    raw = dict(PROM_DEP_TIMEOUT)
    raw.pop("fingerprint", None)  # trigger_id source removed → reject at normalizer
    resp = client.post("/api/alerts/prometheus", json=raw)
    assert resp.status_code == 422
    assert resp.json()["code"] == "missing_required_field"
    # Grouping layer was never reached: registry empty (no investigation minted).
    assert len(default_registry()) == 0


def test_reject_on_unknown_canonical_does_not_open_investigation(
    client: TestClient,
) -> None:
    raw = {
        "fingerprint": "fp-mystery",
        "labels": {"alertname": "MysteryAlert", "severity": "warning", "service": "svc"},
        "annotations": {"summary": "s", "description": "d"},
        "startsAt": "2026-06-24T10:00:00Z",
    }
    resp = client.post("/api/alerts/prometheus", json=raw)
    assert resp.status_code == 422
    assert resp.json()["code"] == "unknown_canonical_trigger"
    assert len(default_registry()) == 0
    assert "fp-mystery" not in default_registry()


# ---------------------------------------------------------------------------
# AC7 — gate #2 one-way: routers + services.grouping import only allowed layers.
# (Mirrors test_ingest_normalize.test_routers_module_does_not_import_forbidden_layers.)
# ---------------------------------------------------------------------------


def test_services_grouping_does_not_import_forbidden_layers() -> None:
    import services.grouping as grouping_mod

    assert grouping_mod.__file__ is not None
    tree = ast.parse(Path(grouping_mod.__file__).read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    forbidden = roots & {"routers", "graph", "adapters", "tools"}
    assert not forbidden, f"services.grouping imports forbidden layer(s): {forbidden}"
