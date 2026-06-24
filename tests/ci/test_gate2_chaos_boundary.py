"""CI gate #2 negative self-test for the Story 7.3 CHAOS-vs-AGENT boundary.

Mirrors ``tests/ci/test_gate2_observability_boundary.py`` (Story 7.2) and
``tests/ci/test_gate2_demo_boundary.py`` (Story 7.1). The Story 7.3 ``forbidden``
import-linter contract (pyproject.toml) asserts that NO ``chaos`` module imports any
RCA-agent module (``routers``/``services``/``graph``/``adapters``/``tools``/``models``/
``eval``/``ci``/``config``) — chaos is the §3.7 fault injector, a WRITE outside the
agent's read-only perimeter (benchmark/infra, parallel to ``demo``/``observability``).
We never trust "contract passes": the gate must demonstrably catch a real chaos→agent import.

  - clean chaos package                       → contract KEPT, exit 0
  - injecting `chaos → graph`                 → contract BROKEN, exit != 0 (HARD-FAIL)
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


def test_chaos_boundary_clean_passes() -> None:
    """The Story 7.3 chaos package must keep the forbidden contract (exit 0)."""
    result = _run_lint_imports()
    assert result.returncode == 0, (
        f"clean chaos package should KEEP the boundary contract:\n{result.stdout}\n{result.stderr}"
    )
    assert "KEPT" in result.stdout


def test_chaos_boundary_hard_fails_on_agent_import() -> None:
    """Injecting a `chaos → graph` import → contract BROKEN, exit != 0 (HARD-FAIL)."""
    violation_file = REPO_ROOT / "chaos" / "_gate2_negative_agent_import.py"
    assert not violation_file.exists(), "leftover negative-test artifact from a previous run"

    try:
        violation_file.write_text(
            '"""temporary negative-test artifact — chaos must not import the agent."""\n'
            "import graph  # noqa: I001  forbidden chaos -> agent (graph) import\n",
            encoding="utf-8",
        )
        result = _run_lint_imports()
        assert result.returncode != 0, (
            "gate #2 should HARD-FAIL (exit != 0) on a chaos -> graph import:\n"
            f"{result.stdout}\n{result.stderr}"
        )
        assert "BROKEN" in result.stdout
        assert "chaos" in result.stdout
        assert "graph" in result.stdout
    finally:
        if violation_file.exists():
            violation_file.unlink()

    # After cleanup, contract must be KEPT again.
    assert _run_lint_imports().returncode == 0, (
        "cleanup failed: contract still broken after removing artifact"
    )
