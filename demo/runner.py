"""demo/runner — the DETERMINISTIC live "normal traffic" driver (Story 7.1).

Generates the seed-reproducible trace (:func:`demo.model.generate_trace`) and
replays it against the LIVE services over HTTP — driving the metrics/logs/K8s-state
the observability stack (Story 7.2) collects. The REQUEST PATTERN is deterministic
(same seed → same request sequence); the live OUTCOMES depend on service health
(non-deterministic timing/outcomes are the Story 7.3 tolerance concern, not a 7.1
determinism concern).

Wall-clock-free: no ``time``/``random``/``hash``-on-strings. Any request-pacing
loop lives in the K8s Deployment's shell entrypoint (not here), so this module's
trace logic stays pure + PYTHONHASHSEED-safe.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass

import httpx

from demo.model import DEFAULT_SEED, TraceStep, generate_trace


def _base_for(service: str) -> str:
    """In-cluster default ``http://{service}`` (K8s Service port 80); env-overridable."""
    env_key = f"DEMO_UPSTREAM_{service.replace('-', '_').upper()}"
    return os.environ.get(env_key, f"http://{service}")


def route_for(step: TraceStep) -> tuple[str, str, dict[str, object] | None]:
    """Map a trace step to ``(method, path, json_body)`` against the live service.

    Pure + deterministic. Mirrors the routes registered in :mod:`demo.app.factory`.
    """
    op = step.operation
    if op == "get_user":
        return "GET", f"/users/{step.user_id}", None
    if op == "create_user":
        return "POST", "/users", None
    if op == "get_stock":
        return "GET", f"/inventory/{step.sku}", None
    if op == "check_inventory":
        return "GET", f"/inventory/{step.sku}", None
    if op == "reserve":
        return "POST", "/inventory/reserve", {"sku": step.sku, "quantity": step.quantity}
    if op == "charge":
        return "POST", "/payment/charge", {"amount": step.amount, "sku": step.sku}
    if op == "refund":
        return "POST", "/payment/refund", {"amount": step.amount, "sku": step.sku}
    if op == "create_order":
        body: dict[str, object] = {
            "user_id": step.user_id,
            "sku": step.sku,
            "quantity": step.quantity,
            "amount": step.amount,
        }
        return "POST", "/orders", body
    if op == "get_order":
        return "GET", f"/orders/{step.user_id}", None
    raise KeyError(f"no route for operation: {op!r}")


@dataclass(frozen=True, slots=True)
class RunSummary:
    """Outcome counts of one live replay (live outcomes are non-deterministic)."""

    n: int
    ok: int
    failed: int


def run_live(trace: tuple[TraceStep, ...], *, timeout: float = 2.0) -> RunSummary:
    """Replay ``trace`` over HTTP against the live services (cluster must be up)."""
    ok = 0
    failed = 0
    with httpx.Client(timeout=timeout) as client:
        for step in trace:
            method, path, body = route_for(step)
            url = f"{_base_for(step.service)}{path}"
            try:
                resp = client.request(method, url, json=body)
                if resp.is_success:
                    ok += 1
                else:
                    failed += 1
            except httpx.HTTPError:
                failed += 1
    return RunSummary(n=len(trace), ok=ok, failed=failed)


def main(argv: list[str] | None = None) -> int:
    """``python -m demo.runner [--seed N] [--n N] [--dry-run]`` — replay one batch."""
    parser = argparse.ArgumentParser(
        prog="demo.runner", description="deterministic demo traffic driver"
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--n", type=int, default=200, help="number of traffic steps")
    parser.add_argument(
        "--dry-run", action="store_true", help="print the deterministic trace, do not call HTTP"
    )
    args = parser.parse_args(argv)
    trace = generate_trace(seed=args.seed, n=args.n)
    if args.dry_run:
        for step in trace:
            method, path, _ = route_for(step)
            sys.stdout.write(f"{step.service}\t{method}\t{path}\n")
        return 0
    summary = run_live(trace)
    sys.stdout.write(f"seed={args.seed} n={summary.n} ok={summary.ok} failed={summary.failed}\n")
    return 0 if summary.failed == 0 else 1


__all__ = ["RunSummary", "main", "route_for", "run_live"]


if __name__ == "__main__":
    raise SystemExit(main())
