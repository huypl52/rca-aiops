"""Read-only tool registry + 10 §3.6 executors + adapter PORT seam (AD-3 BLOCKER / FR-5).

ONE-WAY (AD-1 / gate #2): MUST NOT import ``graph`` or ``services`` (or ``routers``/``adapters``).
MUST NOT expose write/exec/patch/delete/scale/rollback/restart/remediate — enforced by BOTH:
  - CI gate #1 STATIC AST scan (Story 0-1, ``ci/gate1_readonly_registry.py``), and
  - runtime deny-verb rejection at ``ReadOnlyRegistry.register()`` (Story 2.1).
The deny-set vocabulary is LOCKED in ``ci.denyset`` (8 verbs).

Module-level ``registry`` holds EXACTLY the 10 spec §3.6 tools (built deterministically at import —
AD-12). Story 2.2 plugs the real adapter clients via ``ReadOnlyAdapterPort`` WITHOUT touching this
package; Story 2.3 adds ``executor_router`` dispatch; Evidence normalization is Story 4.2.
"""

from __future__ import annotations

from tools.executors import EXECUTORS
from tools.port import (
    JsonValue,
    RawOutput,
    ReadOnlyAdapterPort,
    StubReadOnlyAdapter,
    TimeWindow,
    ToolExecutor,
)
from tools.registry import ReadOnlyRegistry, ReadOnlyViolation, build_default_registry

# Deterministic module-level registry: the 10 spec §3.6 tools, built once at import (AD-12).
registry: ReadOnlyRegistry = build_default_registry()

__all__ = [
    "EXECUTORS",
    "JsonValue",
    "ReadOnlyAdapterPort",
    "ReadOnlyRegistry",
    "ReadOnlyViolation",
    "RawOutput",
    "StubReadOnlyAdapter",
    "TimeWindow",
    "ToolExecutor",
    "build_default_registry",
    "registry",
]
