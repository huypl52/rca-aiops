"""Canonical read-only deny-set (CI gate #1, AD-3 BLOCKER / §3.8).

SINGLE SOURCE OF TRUTH for the read-only boundary vocabulary. Imported by:
  - `ci.gate1_readonly_registry` — CI gate #1 scanner (Story 0.1 skeleton)
  - Story 2.1 read-only tool registry (real enforcement)

Spec §3.8 ground truth (7 forbidden): restart · rollback · scale · delete ·
patch · exec · remediation. The verb set covers all 7 verb-level forms plus the
catch-all `write` = 8 verbs. Command-string forms (kubectl debug/exec/patch,
rollout restart/undo, helm uninstall, terraform destroy, rm -rf) are caught by
WRITE_PATTERNS.
"""

from __future__ import annotations

import re

# Verb-level forbidden names (8). Covers §3.8's 7 forbidden + catch-all `write`.
# Catches `def restart(...)`, `def remediate(...)`, `.scale(...)`, attribute names, etc.
WRITE_VERBS: frozenset[str] = frozenset(
    {
        "write",
        "exec",
        "patch",
        "delete",
        "scale",
        "rollback",
        "restart",
        "remediate",
    }
)

# Command/string-level forbidden patterns. Searched against raw source text.
WRITE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p)
    for p in (
        r"kubectl\s+(debug|exec|patch)",
        r"rollout\s+(restart|undo)",
        r"helm\s+uninstall",
        r"terraform\s+destroy",
        r"\brm\s+-rf\b",
    )
)

__all__ = ["WRITE_VERBS", "WRITE_PATTERNS"]
