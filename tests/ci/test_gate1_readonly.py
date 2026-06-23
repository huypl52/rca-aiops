"""CI gate #1 negative self-test (Story 0.1 — AC5/T4.3).

Proves the read-only registry gate HARD-FAILs on violations:
  - injecting `def scale(...)` (verb)        → gate exit 1
  - injecting `def restart(...)` (verb)      → gate exit 1
  - injecting `def remediate(...)` (verb)    → gate exit 1
  - injecting a command-string pattern       → gate exit 1
  - clean skeleton                           → gate exit 0

We never trust "skeleton passes" — the gate must demonstrably catch a real
write-leak. Files are created under a temp copy of the scanned packages so the
real repo tree is untouched.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

# Path to the gate script (run via `uv run python` so the `ci` package imports).
REPO_ROOT = Path(__file__).resolve().parents[2]
GATE_SCRIPT = REPO_ROOT / "ci" / "gate1_readonly_registry.py"


# The gate scans these real packages by default; this test asserts the current
# skeleton is clean (no false positives).
def test_gate1_clean_skeleton_passes() -> None:
    """The Story 0.1 skeleton must pass gate #1 (no write-verbs present)."""
    result = subprocess.run(
        [sys.executable, str(GATE_SCRIPT), "--root", str(REPO_ROOT)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, (
        f"clean skeleton should PASS gate #1:\n{result.stdout}\n{result.stderr}"
    )
    assert "PASS" in result.stdout


@pytest.mark.parametrize(
    "bad_source",
    [
        # verb-level — §3.8 forbidden forms
        "def scale(self, n: int) -> None: ...\n",
        "def restart(self) -> None: ...\n",
        "def remediate(self) -> None: ...\n",
        "def rollback(self) -> None: ...\n",
        "def exec(self, cmd: str) -> None: ...\n",
        # command-string pattern
        "def lookup() -> str:\n    return 'kubectl exec -it pod -- sh'\n",
    ],
    ids=[
        "verb-scale",
        "verb-restart",
        "verb-remediate",
        "verb-rollback",
        "verb-exec",
        "pattern-kubectl-exec",
    ],
)
def test_gate1_hard_fails_on_violation(tmp_path: Path, bad_source: str) -> None:
    """Injecting a forbidden write-verb/pattern into a scanned package → gate exit 1 (HARD-FAIL)."""
    # Build a fake repo root with an `adapters` package containing the bad file.
    adapters = tmp_path / "adapters"
    adapters.mkdir()
    (adapters / "__init__.py").write_text(
        '"""fake adapters for negative test."""\n', encoding="utf-8"
    )
    (adapters / "_bad.py").write_text(bad_source, encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(GATE_SCRIPT), "--root", str(tmp_path)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 1, (
        f"gate #1 should HARD-FAIL on:\n{bad_source}\n--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    assert "HARD-FAIL" in result.stdout


def test_denyset_has_eight_verbs() -> None:
    """WRITE_VERBS must contain exactly the 8 §3.8-covering verbs (regression guard)."""
    from ci.denyset import WRITE_VERBS

    assert len(WRITE_VERBS) == 8
    # §3.8's 7 forbidden verb forms + catch-all write.
    for required in (
        "write",
        "exec",
        "patch",
        "delete",
        "scale",
        "rollback",
        "restart",
        "remediate",
    ):
        assert required in WRITE_VERBS, f"missing §3.8 verb: {required}"
