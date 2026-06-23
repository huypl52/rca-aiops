"""CI gate #2 negative self-test (Story 0.1 — AC6/T5.3).

Proves the dependency-direction import-linter gate HARD-FAILs on back-edges:
  - injecting `adapters → graph` back-edge → lint-imports exit 1, contract BROKEN
  - clean skeleton                       → lint-imports exit 0, contract KEPT

The import-linter `[tool.importlinter]` layers contract (pyproject.toml) asserts
the one-way chain `routers → services → graph → adapters → tools` and forbids
any back-edge / circular import (AD-1 / AD-2, AD-13 #2). We never trust
"skeleton passes" — the gate must demonstrably catch a real back-edge.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_lint_imports() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "lint-imports"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )


def test_gate2_clean_skeleton_passes() -> None:
    """The Story 0.1 skeleton must keep the layers contract (exit 0)."""
    result = _run_lint_imports()
    assert result.returncode == 0, (
        f"clean skeleton should KEEP contract:\n{result.stdout}\n{result.stderr}"
    )
    assert "KEPT" in result.stdout


def test_gate2_hard_fails_on_back_edge() -> None:
    """Injecting an `adapters → graph` back-edge → contract BROKEN, exit 1 (HARD-FAIL)."""
    violation_file = REPO_ROOT / "adapters" / "_gate2_negative_backedge.py"
    assert not violation_file.exists(), "leftover negative-test artifact from a previous run"

    try:
        violation_file.write_text(
            '"""temporary negative-test artifact — back-edge forbidden by AD-1."""\n'
            "import graph  # noqa: I001  forbidden back-edge adapters -> graph\n",
            encoding="utf-8",
        )
        result = _run_lint_imports()
        assert result.returncode != 0, (
            "gate #2 should HARD-FAIL (exit != 0) on adapters -> graph back-edge:\n"
            f"{result.stdout}\n{result.stderr}"
        )
        assert "BROKEN" in result.stdout
        assert "adapters" in result.stdout
        assert "graph" in result.stdout
    finally:
        if violation_file.exists():
            violation_file.unlink()

    # After cleanup, contract must be KEPT again.
    assert _run_lint_imports().returncode == 0, (
        "cleanup failed: contract still broken after removing artifact"
    )
