"""Story 7.1 — demo topology is the locked 5-microservice DAG (supports spec §3.7).

These are the executable invariants behind ``demo/topology.py``:
  - the 5 LOCKED service names + the locked dependency edges;
  - the graph is a DAG (acyclic) with a valid deterministic deploy order;
  - the §3.7 microservice labels (``order-service``/``payment-service``/``user-service``
    /``inventory`` — node/CoreDNS labels are infra, not microservices) all map to a demo
    service, so the benchmark scenarios can target real pods;
  - the headline §3.7 propagation is REAL: a fault on ``payment`` (or ``inventory``)
    degrades ``order``, and surfaces at the edge gateway.

Pure + stdlib-only. This test imports only ``demo.topology`` — never the agent.
"""

from __future__ import annotations

import pytest

from demo.topology import (
    DEPENDENCIES,
    NAMESPACE,
    SECTION_37_LABEL_TO_SERVICE,
    SERVICE_NAMES,
    SERVICE_PORTS,
    callers_of,
    covers_section_37_services,
    dependencies_of,
    has_cycle,
    is_leaf,
    reachable_from,
    topological_order,
)


def test_service_names_locked() -> None:
    assert SERVICE_NAMES == ("api-gateway", "user", "order", "inventory", "payment")
    # tuple, not a set — iteration order is hash-seed-stable (AD-12 analog).
    assert isinstance(SERVICE_NAMES, tuple)


def test_namespace_is_single_tenant_demo() -> None:
    assert NAMESPACE == "demo"  # single-tenant POC (multi-tenant = prod D10, OUT)


def test_dependencies_locked() -> None:
    assert DEPENDENCIES == {
        "api-gateway": ("inventory", "order", "payment", "user"),
        "order": ("inventory", "payment"),
        "user": (),
        "inventory": (),
        "payment": (),
    }
    # every value is a SORTED tuple (hash-seed-stable iteration), never a set.
    assert all(isinstance(v, tuple) for v in DEPENDENCIES.values())


def test_ports_are_distinct_and_locked() -> None:
    assert SERVICE_PORTS == {
        "api-gateway": 8080,
        "user": 8081,
        "order": 8082,
        "inventory": 8083,
        "payment": 8084,
    }
    assert len(set(SERVICE_PORTS.values())) == len(SERVICE_PORTS)


def test_graph_is_a_dag() -> None:
    assert has_cycle() is False


def test_topological_order_is_a_valid_deploy_order() -> None:
    order = topological_order()
    assert set(order) == set(SERVICE_NAMES)
    assert len(order) == len(SERVICE_NAMES)
    pos = {svc: i for i, svc in enumerate(order)}
    for src, deps in DEPENDENCIES.items():
        for dep in deps:
            assert pos[dep] < pos[src], f"{dep} must deploy before its dependent {src}"


def test_leaves_and_internal_nodes() -> None:
    for leaf in ("user", "inventory", "payment"):
        assert is_leaf(leaf) is True
        assert dependencies_of(leaf) == ()
    for internal in ("api-gateway", "order"):
        assert is_leaf(internal) is False


def test_callers_match_the_edges() -> None:
    assert callers_of("payment") == ("api-gateway", "order")
    assert callers_of("inventory") == ("api-gateway", "order")
    assert callers_of("user") == ("api-gateway",)
    assert callers_of("order") == ("api-gateway",)


def test_reachable_sets() -> None:
    assert reachable_from("api-gateway") == ("inventory", "order", "payment", "user")
    assert reachable_from("order") == ("inventory", "payment")
    assert reachable_from("user") == ()
    assert reachable_from("inventory") == ()
    assert reachable_from("payment") == ()


def test_unknown_service_raises() -> None:
    with pytest.raises(KeyError):
        dependencies_of("does-not-exist")


def test_section_37_microservice_labels_are_covered() -> None:
    # The 4 §3.7 *microservice* labels map 1:1 to demo services. (demo-node-1 is a node,
    # coredns is DNS infra — neither is a microservice; handled by Story 7.2/7.3.)
    assert SECTION_37_LABEL_TO_SERVICE == {
        "order-service": "order",
        "payment-service": "payment",
        "user-service": "user",
        "inventory": "inventory",
    }
    assert covers_section_37_services() is True
    for mapped in SECTION_37_LABEL_TO_SERVICE.values():
        assert mapped in SERVICE_NAMES


def test_section_37_fault_propagation_is_real() -> None:
    # Headline §3.7 dependency_timeout: a fault on payment must degrade order …
    assert "order" in callers_of("payment")
    # … and surface at the edge gateway (order is reachable from api-gateway).
    assert "order" in reachable_from("api-gateway")
    # inventory_reserve_failure: a fault on inventory degrades order too.
    assert "order" in callers_of("inventory")
