"""Read-only tool registry + defense-in-depth runtime deny-verb check (AD-3 BLOCKER / FR-5).

Story 2.1 — AD-3 (BLOCKER) / AD-13 #1 / AD-12 (determinism).

Holds **exactly the 10 spec §3.6 tools** (built deterministically at import from
``tools.executors.EXECUTORS`` — no wall-clock/random/IO at registration, AD-12), keyed by name.
Two enforcement layers over the SAME locked vocabulary (``ci.denyset.WRITE_VERBS``):

  1. **CI gate #1 (static, Story 0-1)** — AST-scans ``tools/``+``adapters/`` source for any
     ``def``/``async def``/``class``/attribute whose ``.name`` ∈ ``WRITE_VERBS``, plus forbidden
     command-string patterns. HARD-FAIL at merge. Catches source-level violations.
  2. **Runtime deny-verb rejection at ``register()`` (this module, Story 2.1)** — defense-in-depth
     ON TOP of the static scan: refuses to register any tool whose name ∈ ``WRITE_VERBS``. Catches
     DYNAMIC registration the AST cannot see. Belt-and-braces companion to CI gate #1 (AC4).

Both layers pass for a clean registry; either can block a leak.

ONE-WAY (AD-1 / gate #2): imports ``ci.denyset`` (not a contracted layer) + ``tools.executors`` +
``tools.port`` (same layer) + stdlib only. NEVER imports ``routers``/``services``/``graph``/
``adapters``.
"""

from __future__ import annotations

from collections.abc import Iterator

from ci.denyset import WRITE_VERBS
from tools.executors import EXECUTORS
from tools.port import ToolExecutor

# ONE-WAY (AD-1 / gate #2): ci.denyset (not a contracted layer) + tools.* (same layer) + stdlib.
# NEVER imports routers/services/graph/adapters (back-edge forbidden).


class ReadOnlyViolation(Exception):
    """Raised when a deny-verb tool name is registered (defense-in-depth, AD-3 / §3.8).

    This is the RUNTIME companion to CI gate #1's STATIC scan. A tool whose ``name`` ∈
    ``WRITE_VERBS`` can never enter the registry, even via dynamic registration the AST gate
    cannot see.
    """


class ReadOnlyRegistry:
    """Name → read-only executor map. Exactly the spec §3.6 set when built via
    ``build_default_registry()`` (no invented / no missing — AC2 count contract)."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolExecutor] = {}

    def register(self, name: str, executor: ToolExecutor) -> None:
        """Register a read-only executor under ``name``.

        Defense-in-depth (AD-3): rejects any ``name`` ∈ ``ci.denyset.WRITE_VERBS`` with
        ``ReadOnlyViolation`` — the runtime layer on top of CI gate #1's static AST scan. Also
        rejects duplicate names (registry is a 1:1 name→executor map).
        """
        if name in WRITE_VERBS:
            raise ReadOnlyViolation(
                f"refusing to register deny-verb tool '{name}' — read-only boundary (AD-3 / §3.8)."
            )
        if name in self._tools:
            raise ValueError(f"tool '{name}' already registered (duplicate).")
        self._tools[name] = executor

    def lookup(self, name: str) -> ToolExecutor:
        """Return the executor registered under ``name`` (KeyError if absent)."""
        return self._tools[name]

    def names(self) -> list[str]:
        """All registered tool names, deterministically sorted (registration order)."""
        return list(self._tools.keys())

    def items(self) -> Iterator[tuple[str, ToolExecutor]]:
        """Iterate (name, executor) pairs in registration order."""
        return iter(self._tools.items())

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: object) -> bool:
        return name in self._tools


def build_default_registry() -> ReadOnlyRegistry:
    """Build a registry holding EXACTLY the 10 spec §3.6 tools (AC1/AC2 count contract).

    Deterministic (AD-12): registration order follows ``tools.executors.EXECUTORS`` dict order —
    no wall-clock, no random, no IO. The caller asserts ``len == 10`` and the exact name set.
    """
    registry = ReadOnlyRegistry()
    for name, executor in EXECUTORS.items():
        registry.register(name, executor)
    return registry


__all__ = [
    "ReadOnlyRegistry",
    "ReadOnlyViolation",
    "build_default_registry",
]
