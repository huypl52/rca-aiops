"""CI gate #2 negative self-test for the Story 7.1 DEMO-vs-AGENT boundary.

Mirrors ``tests/ci/test_gate2_deps.py``. The Story 7.1 ``forbidden`` import-linter
contract (pyproject.toml) asserts that NO ``demo`` module imports any RCA-agent module
(``routers``/``services``/``graph``/``adapters``/``tools``/``models``/``eval``/``ci``/
``config``) — the demo is a standalone SYSTEM-UNDER-INVESTIGATION. We never trust
"contract passes": the gate must demonstrably catch a real demo→agent import.

  - clean demo package                       → contract KEPT, exit 0
  - injecting `demo → graph`                 → contract BROKEN, exit != 0 (HARD-FAIL)
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


def test_demo_boundary_clean_passes() -> None:
    """The Story 7.1 demo package must keep the forbidden contract (exit 0)."""
    result = _run_lint_imports()
    assert result.returncode == 0, (
        f"clean demo package should KEEP the boundary contract:\n{result.stdout}\n{result.stderr}"
    )
    assert "KEPT" in result.stdout


def test_demo_boundary_hard_fails_on_agent_import() -> None:
    """Injecting a `demo → graph` import → contract BROKEN, exit != 0 (HARD-FAIL)."""
    violation_file = REPO_ROOT / "demo" / "_gate2_negative_agent_import.py"
    assert not violation_file.exists(), "leftover negative-test artifact from a previous run"

    try:
        violation_file.write_text(
            '"""temporary negative-test artifact — demo must not import the agent."""\n'
            "import graph  # noqa: I001  forbidden demo -> agent (graph) import\n",
            encoding="utf-8",
        )
        result = _run_lint_imports()
        assert result.returncode != 0, (
            "gate #2 should HARD-FAIL (exit != 0) on a demo -> graph import:\n"
            f"{result.stdout}\n{result.stderr}"
        )
        assert "BROKEN" in result.stdout
        assert "demo" in result.stdout
        assert "graph" in result.stdout
    finally:
        if violation_file.exists():
            violation_file.unlink()

    # After cleanup, contract must be KEPT again.
    assert _run_lint_imports().returncode == 0, (
        "cleanup failed: contract still broken after removing artifact"
    )
