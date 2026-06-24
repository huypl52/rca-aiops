"""demo/topology — the 5-microservice dependency graph (Story 7.1).

LOCKED (per leader dispatch): the 5 named FastAPI services — ``api-gateway``,
``user``, ``order``, ``inventory``, ``payment`` — are the SYSTEM-UNDER-
INVESTIGATION (the demo victim system). They are a STANDALONE deployable that
imports NO agent code (``graph``/``services``/``routers``/``models``/``adapters``/
``tools``/``eval``/``ci``/``config``); the read-only-investigator deny-set (gate #1)
does NOT apply to them.

The topology is REAL so the spec §3.7 fault scenarios are meaningful — a fault on
``payment`` must actually affect ``order`` (``dependency_timeout``), a fault on
``inventory`` must affect ``order`` (``inventory_reserve_failure``)::

    api-gateway ──┬─► user
                  ├─► inventory
                  ├─► payment
                  └─► order ──┬─► inventory
                              └─► payment

``user`` / ``inventory`` / ``payment`` are leaves. The graph is a DAG (acyclic) —
asserted by ``tests/test_demo_topology.py``.

Determinism: STDLIB-ONLY + PURE (no IO, no wall-clock, no unseeded random). The
topology is static data — the demo-system analog of the agent's AD-12 discipline.
"""

from __future__ import annotations

from typing import Final

#: The 5 demo microservices (LOCKED names — referenced by spec §3.7 scenarios and
#: the 6.x ``root_cause.faulty_service`` labels). A frozen TUPLE = stable order
#: (PYTHONHASHSEED-safe; never a set/dict whose iteration order is hash-seed-bound).
SERVICE_NAMES: Final[tuple[str, ...]] = (
    "api-gateway",
    "user",
    "order",
    "inventory",
    "payment",
)

#: Outbound dependency edges (who calls whom over HTTP). A fault on a target
#: degrades its callers — this is what makes the §3.7 ``dependency_timeout`` /
#: ``inventory_reserve_failure`` scenarios REAL. Leaves (user/inventory/payment)
#: have no outbound deps; ``order`` depends on inventory + payment; ``api-gateway``
#: fans out to all four. Sorted tuples keep the data hash-seed-stable.
DEPENDENCIES: Final[dict[str, tuple[str, ...]]] = {
    "api-gateway": ("inventory", "order", "payment", "user"),
    "order": ("inventory", "payment"),
    "user": (),
    "inventory": (),
    "payment": (),
}

#: Fixed HTTP port per service (deterministic — not ephemeral/random). The K8s
#: ``Service`` exposes port 80 → ``targetPort`` below (see ``demo/k8s/*.yaml``);
#: inter-service calls in-cluster use ``http://{service}`` (port 80).
SERVICE_PORTS: Final[dict[str, int]] = {
    "api-gateway": 8080,
    "user": 8081,
    "order": 8082,
    "inventory": 8083,
    "payment": 8084,
}

#: The single POC tenant (spec §3.7 / NFR-Scope; multi-tenant = prod D10 — OUT).
NAMESPACE: Final[str] = "demo"

#: spec §3.7 scenario ``service``/``faulty_service`` labels (some ``-service``
#: suffixed, some bare) → the demo service they target. Every §3.7 service-level
#: label maps to one of the 5 demo services (node/CoreDNS labels are infra, not
#: microservices — handled by Story 7.2/7.3). DERIVED from ``eval/scenarios.py``.
SECTION_37_LABEL_TO_SERVICE: Final[dict[str, str]] = {
    "order-service": "order",
    "payment-service": "payment",
    "user-service": "user",
    "inventory": "inventory",
}


def dependencies_of(service: str) -> tuple[str, ...]:
    """The outbound dependencies of ``service`` (sorted tuple; empty for leaves)."""
    if service not in DEPENDENCIES:
        raise KeyError(f"unknown demo service: {service!r}")
    return DEPENDENCIES[service]


def is_leaf(service: str) -> bool:
    """``True`` iff ``service`` has no outbound dependency (user/inventory/payment)."""
    return len(dependencies_of(service)) == 0


def callers_of(service: str) -> tuple[str, ...]:
    """The services that depend on ``service`` (its inbound callers), sorted."""
    if service not in DEPENDENCIES:
        raise KeyError(f"unknown demo service: {service!r}")
    return tuple(sorted(src for src, deps in DEPENDENCIES.items() if service in deps))


def reachable_from(service: str) -> tuple[str, ...]:
    """All services transitively reachable from ``service`` (excluding itself), sorted.

    Used to prove the §3.7 fan-out: a fault deep in the DAG must surface at the
    gateway. Pure, deterministic (BFS over the sorted DAG).
    """
    if service not in DEPENDENCIES:
        raise KeyError(f"unknown demo service: {service!r}")
    seen: set[str] = set()
    frontier: list[str] = list(dependencies_of(service))
    while frontier:
        current = frontier.pop()
        if current in seen:
            continue
        seen.add(current)
        frontier.extend(dependencies_of(current))
    return tuple(sorted(seen))


def has_cycle() -> bool:
    """``True`` iff the dependency graph has a cycle (Kahn's algorithm, deterministic).

    The topology is a DAG by construction; this is the executable proof (a cycle
    would make fault propagation non-terminating + the deploy order undefined).
    """
    # In-degree per node over the directed edges caller → dependency.
    in_degree: dict[str, int] = {s: 0 for s in SERVICE_NAMES}
    for src in SERVICE_NAMES:
        for dep in DEPENDENCIES[src]:
            in_degree[dep] += 1
    # Seed with all zero-in-degree nodes, SORTED for determinism.
    queue: list[str] = sorted(s for s, d in in_degree.items() if d == 0)
    visited = 0
    while queue:
        current = queue.pop(0)
        visited += 1
        newly_ready: list[str] = []
        for dep in DEPENDENCIES[current]:
            in_degree[dep] -= 1
            if in_degree[dep] == 0:
                newly_ready.append(dep)
        queue.extend(sorted(newly_ready))
    return visited != len(SERVICE_NAMES)


def topological_order() -> tuple[str, ...]:
    """A deterministic deploy order (dependencies before dependents), via Kahn.

    Leaves deploy first so dependents' readiness probes can reach them: a node is
    emitted only once all ITS OWN dependencies are already placed. Ties are broken by
    SORTED name (PYTHONHASHSEED-safe).
    """
    # remaining_deps[node] = count of its own still-unplaced dependencies (NOT its callers).
    remaining_deps: dict[str, int] = {s: len(DEPENDENCIES[s]) for s in SERVICE_NAMES}
    # callers[node] = the services that depend on it (emitting a node unblocks its callers).
    callers: dict[str, list[str]] = {s: [] for s in SERVICE_NAMES}
    for src in SERVICE_NAMES:
        for dep in DEPENDENCIES[src]:
            callers[dep].append(src)
    order: list[str] = []
    queue: list[str] = sorted(s for s, d in remaining_deps.items() if d == 0)
    while queue:
        current = queue.pop(0)
        order.append(current)
        newly_ready: list[str] = []
        for caller in callers[current]:
            remaining_deps[caller] -= 1
            if remaining_deps[caller] == 0:
                newly_ready.append(caller)
        queue.extend(sorted(newly_ready))
    return tuple(order)


def covers_section_37_services() -> bool:
    """Every §3.7 service-level label maps to a demo service (topology supports §3.7)."""
    return all(label in SERVICE_NAMES for label in SECTION_37_LABEL_TO_SERVICE.values())


__all__ = [
    "DEPENDENCIES",
    "NAMESPACE",
    "SECTION_37_LABEL_TO_SERVICE",
    "SERVICE_NAMES",
    "SERVICE_PORTS",
    "callers_of",
    "covers_section_37_services",
    "dependencies_of",
    "has_cycle",
    "is_leaf",
    "reachable_from",
    "topological_order",
]
