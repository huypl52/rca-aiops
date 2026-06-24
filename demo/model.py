"""demo/model — the DETERMINISTIC, SEED-REPRODUCIBLE demo-system core (Story 7.1).

AD-12 (determinism) EXTENDED to the demo system (per leader dispatch): the same
healthy baseline must be reproducible run-to-run so Story 7.3's chaos inject
produces reproducible symptoms. Everything here is a PURE function — no IO, no
wall-clock, no module-global ``random``. The only randomness is a SEEDED
``random.Random(seed)``.

The make-or-break (the demo analog of gate #6 §2C): ::

    render_prometheus(replay_trace(generate_trace(seed, n)))

is BYTE-IDENTICAL across ``PYTHONHASHSEED={0,1,42}`` — proven by the cross-process
test ``tests/test_demo_model_determinism.py`` (spawns ``python -m demo.model``
under several seeds).

Determinism guarantees (audited by the determinism test):
  - output containers are ``tuple``/``dataclass``/sorted-list — never a ``set``/
    ``dict`` whose iteration order is hash-seed-bound;
  - ``random.Random(seed)`` is hash-seed-independent (Mersenne Twister, seed-based);
  - the only iteration over a ``dict`` (``upstream_calls_total``) happens through
    ``sorted(...)`` before it reaches the rendered string.

Stdlib-only. This module imports NOTHING from the agent (enforced by gate #2).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Final

from demo.topology import SERVICE_NAMES, dependencies_of

#: The POC traffic seed (deterministic — AD-12: no wall-clock). The live runner
#: and the determinism test both default to this so the healthy baseline is fixed.
DEFAULT_SEED: Final[int] = 42

#: Per-service operations (SORTED tuples → deterministic ``random.Random.choice``).
#: The live FastAPI routes (:mod:`demo.app.factory`) expose these same operations,
#: so the pure model and the deployed services stay consistent.
OPERATIONS: Final[dict[str, tuple[str, ...]]] = {
    "api-gateway": ("check_inventory", "create_order", "get_user"),
    "inventory": ("get_stock", "reserve"),
    "order": ("create_order", "get_order"),
    "payment": ("charge", "refund"),
    "user": ("create_user", "get_user"),
}

#: Service-sampling weights for the entry-traffic generator (gateway dominates —
#: external traffic enters at the edge). A SORTED (service, weight) tuple → the
#: cumulative-weight array is hash-seed-stable.
_ENTRY_WEIGHTS: Final[tuple[tuple[str, int], ...]] = (
    ("api-gateway", 5),
    ("inventory", 1),
    ("order", 2),
    ("payment", 1),
    ("user", 2),
)


@dataclass(frozen=True, slots=True)
class TraceStep:
    """One deterministic entry-traffic step (frozen → hash-seed-stable in a tuple)."""

    seq: int
    service: str
    operation: str
    user_id: int
    sku: str
    quantity: int
    amount: int


def generate_trace(seed: int = DEFAULT_SEED, n: int = 200) -> tuple[TraceStep, ...]:
    """Generate ``n`` deterministic entry-traffic steps (PURE, seed-reproducible).

    The same ``(seed, n)`` always yields the byte-identical trace across
    ``PYTHONHASHSEED`` (the only entropy is ``random.Random(seed)``; all candidate
    collections are SORTED tuples). This is the "normal traffic" generator whose
    replay produces the reproducible healthy baseline.
    """
    if n < 0:
        raise ValueError(f"n must be >= 0, got {n}")
    rng = random.Random(seed)
    # Deterministic weighted service pick over the SORTED weight tuple.
    total_weight = sum(w for _, w in _ENTRY_WEIGHTS)
    services = tuple(s for s, _ in _ENTRY_WEIGHTS)
    weights = tuple(w for _, w in _ENTRY_WEIGHTS)
    steps: list[TraceStep] = []
    for seq in range(n):
        roll = rng.randrange(total_weight)
        cumulative = 0
        service = services[0]
        for name, weight in zip(services, weights, strict=True):
            cumulative += weight
            if roll < cumulative:
                service = name
                break
        operation = rng.choice(OPERATIONS[service])  # OPERATIONS[service] sorted
        user_id = rng.randint(1, 1000)
        sku = f"sku-{rng.randint(1, 100):03d}"
        quantity = rng.randint(1, 5)
        amount = quantity * 1000 + rng.randint(0, 999)
        steps.append(
            TraceStep(
                seq=seq,
                service=service,
                operation=operation,
                user_id=user_id,
                sku=sku,
                quantity=quantity,
                amount=amount,
            )
        )
    return tuple(steps)


@dataclass(slots=True)
class ServiceSnapshot:
    """Live-or-replayed per-service metric counters (the Prometheus source).

    Counters are REQUEST-count-based (not wall-clock) → deterministic given the
    traffic. ``upstream_errors_total`` is empty in the healthy baseline (Story 7.3
    chaos inject populates it). Mutable: both the pure replay and the live app
    increment a fresh instance.
    """

    service: str
    requests_total: int = 0
    operations_total: dict[str, int] = field(default_factory=dict)
    upstream_calls_total: dict[str, int] = field(default_factory=dict)
    upstream_errors_total: dict[str, int] = field(default_factory=dict)
    healthy: int = 1


def replay_trace(trace: tuple[TraceStep, ...]) -> dict[str, ServiceSnapshot]:
    """Apply ``trace`` to fresh per-service snapshots, propagating calls over the DAG.

    PURE (no HTTP). Each entry step increments its service's request counter, then
    fans out over the dependency DAG: a call ``caller→callee`` increments the
    caller's ``upstream_calls_total[callee]`` and the callee's ``requests_total``
    (a fault on the callee therefore degrades the caller — the §3.7 propagation).
    Counts are additive → the final snapshot values are independent of processing
    order, hence deterministic. Returns a dict keyed by ``SERVICE_NAMES``.
    """
    snapshots: dict[str, ServiceSnapshot] = {s: ServiceSnapshot(service=s) for s in SERVICE_NAMES}
    for step in trace:
        entry = snapshots[step.service]
        entry.requests_total += 1
        entry.operations_total[step.operation] = entry.operations_total.get(step.operation, 0) + 1
        # Fan out over the DAG (LIFO worklist of caller→callee edges). DAG = terminates.
        edges: list[tuple[str, str]] = [
            (step.service, dep) for dep in dependencies_of(step.service)
        ]
        while edges:
            caller, callee = edges.pop()
            caller_snap = snapshots[caller]
            caller_snap.upstream_calls_total[callee] = (
                caller_snap.upstream_calls_total.get(callee, 0) + 1
            )
            callee_snap = snapshots[callee]
            callee_snap.requests_total += 1
            callee_snap.operations_total["inbound"] = (
                callee_snap.operations_total.get("inbound", 0) + 1
            )
            edges.extend((callee, dep) for dep in dependencies_of(callee))
    return snapshots


def render_prometheus(snapshots: dict[str, ServiceSnapshot], *, service: str | None = None) -> str:
    """Render snapshots as Prometheus text exposition (PURE, deterministic ordering).

    ``service=None`` renders all 5 (in ``SERVICE_NAMES`` order); passing a name
    renders one (the live ``/metrics`` endpoint). All multi-valued labels are
    emitted in SORTED order so the string is byte-stable across ``PYTHONHASHSEED``.
    Counters/gauges only — no wall-clock-based values.
    """
    names: tuple[str, ...] = (service,) if service is not None else SERVICE_NAMES
    lines: list[str] = []
    lines.append("# HELP demo_requests_total Total requests received by the service.")
    lines.append("# TYPE demo_requests_total counter")
    lines.append("# HELP demo_operations_total Requests received by the service per operation.")
    lines.append("# TYPE demo_operations_total counter")
    lines.append("# HELP demo_upstream_calls_total Total outbound calls to a dependency.")
    lines.append("# TYPE demo_upstream_calls_total counter")
    lines.append("# HELP demo_upstream_errors_total Total failed outbound calls to a dependency.")
    lines.append("# TYPE demo_upstream_errors_total counter")
    lines.append("# HELP demo_healthy 1 = healthy, 0 = degraded (readiness-derived).")
    lines.append("# TYPE demo_healthy gauge")
    for name in names:
        snap = snapshots[name]
        lines.append(f'demo_requests_total{{service="{name}"}} {snap.requests_total}')
        for op in sorted(snap.operations_total):
            lines.append(
                f'demo_operations_total{{service="{name}",operation="{op}"}} '
                f"{snap.operations_total[op]}"
            )
        for target in sorted(snap.upstream_calls_total):
            lines.append(
                f'demo_upstream_calls_total{{service="{name}",target="{target}"}} '
                f"{snap.upstream_calls_total[target]}"
            )
        for target in sorted(snap.upstream_errors_total):
            lines.append(
                f'demo_upstream_errors_total{{service="{name}",target="{target}"}} '
                f"{snap.upstream_errors_total[target]}"
            )
        lines.append(f'demo_healthy{{service="{name}"}} {snap.healthy}')
    return "\n".join(lines) + "\n"


def healthy_blob(*, seed: int = DEFAULT_SEED, n: int = 200) -> str:
    """The canonical healthy-baseline Prometheus blob (PURE, deterministic).

    ``render_prometheus(replay_trace(generate_trace(seed, n)))`` — the byte-stable
    artifact the determinism test compares across ``PYTHONHASHSEED``. Also the
    ``python -m demo.model`` CLI entrypoint's stdout.
    """
    return render_prometheus(replay_trace(generate_trace(seed, n)))


def _main() -> None:
    """``python -m demo.model`` → print the canonical healthy-baseline blob."""
    import sys

    seed = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SEED
    sys.stdout.write(healthy_blob(seed=seed))


__all__ = [
    "DEFAULT_SEED",
    "OPERATIONS",
    "ServiceSnapshot",
    "TraceStep",
    "generate_trace",
    "healthy_blob",
    "render_prometheus",
    "replay_trace",
]


if __name__ == "__main__":
    _main()
