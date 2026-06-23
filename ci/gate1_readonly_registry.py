"""CI gate #1 — read-only registry scanner (AD-13 #1 / AD-3 BLOCKER).

HARD-FAIL: if any tool/adapter source exposes a forbidden write/exec/patch/...
verb (method/function/attribute name) or a forbidden command-string pattern,
this script exits non-zero and blocks merge. NOT skippable, NOT opt-out
(AD-13 #1). Enforcement is at the code/registry level, NOT via LLM (AD-3).

Usage (CI step):
    uv run python ci/gate1_readonly_registry.py [--root .]

Exit code 0 = clean; 1 = violation found (HARD-FAIL).

This is the Story 0.1 SKELETON: it scans source statically. Story 2.1 wires
this against the real tool registry.
"""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path

# Ensure the repo root is importable so `ci.denyset` resolves both under
# `uv run` (project installed) and when run as a bare script.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ci.denyset import WRITE_PATTERNS, WRITE_VERBS  # noqa: E402

# Packages whose source is scanned for read-only violations (AD-3).
SCANNED_PACKAGES: tuple[str, ...] = ("adapters", "tools")


@dataclass(frozen=True)
class Violation:
    """A single read-only boundary violation."""

    file: Path
    line: int
    col: int
    kind: str  # "verb:<name>" or "pattern:<regex>"
    detail: str

    def render(self) -> str:
        return f"{self.file}:{self.line}:{self.col}  GATE#1 HARD-FAIL  {self.kind}: {self.detail}"


def _write_verb_hit(node: ast.AST) -> tuple[str, int, int, str] | None:
    """Return (verb, lineno, col, node_type_name) if ``node`` is a forbidden write-verb, else None.

    Narrowing is done per-branch so lineno/col_offset are type-safe (all four node
    kinds expose them). Catches def/async-def/class ``.name`` and attribute ``.attr``.
    """
    if isinstance(node, ast.Attribute):
        if node.attr in WRITE_VERBS:
            return node.attr, node.lineno, node.col_offset, type(node).__name__
        return None
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        if node.name in WRITE_VERBS:
            return node.name, node.lineno, node.col_offset, type(node).__name__
    return None


def scan_file(path: Path) -> list[Violation]:
    """Scan a single Python source file for read-only violations."""
    violations: list[Violation] = []
    source = path.read_text(encoding="utf-8")

    # 1. AST: forbidden verb names on def / async def / attribute / class.
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        # Syntax errors are not this gate's concern (ruff/mypy catch them).
        return violations

    for node in ast.walk(tree):
        hit = _write_verb_hit(node)
        if hit is not None:
            name, line, col, type_name = hit
            violations.append(
                Violation(
                    file=path,
                    line=line,
                    col=col,
                    kind=f"verb:{name}",
                    detail=f"forbidden write-verb '{name}' on {type_name}",
                )
            )

    # 2. Regex: forbidden command-string patterns, line by line.
    # Iterate `source.splitlines()` so line numbers stay correct even with
    # multibyte (UTF-8) source — earlier this counted newlines via a byte
    # offset into the char string, which over-counted on non-ASCII content.
    for lineno, text in enumerate(source.splitlines(), start=1):
        for pat in WRITE_PATTERNS:
            m = pat.search(text)
            if m:
                violations.append(
                    Violation(
                        file=path,
                        line=lineno,
                        col=m.start(),
                        kind=f"pattern:{pat.pattern}",
                        detail=f"forbidden command pattern {pat.pattern!r}",
                    )
                )
                break

    return violations


def collect_python_files(root: Path) -> list[Path]:
    """Collect all .py files under the SCANNED_PACKAGES within root."""
    files: list[Path] = []
    for pkg in SCANNED_PACKAGES:
        pkg_dir = root / pkg
        if not pkg_dir.is_dir():
            continue
        for path in sorted(pkg_dir.rglob("*.py")):
            files.append(path)
    return files


def run(root: Path) -> list[Violation]:
    """Scan all scanned-package source under root; return all violations."""
    all_violations: list[Violation] = []
    for path in collect_python_files(root):
        all_violations.extend(scan_file(path))
    return all_violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CI gate #1: read-only registry (HARD-FAIL).")
    parser.add_argument("--root", default=".", help="repo root (default: cwd)")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    violations = run(root)

    if not violations:
        print(
            f"✓ CI gate #1 (read-only registry): PASS — scanned {len(SCANNED_PACKAGES)} packages, no violations."
        )
        return 0

    print(f"✗ CI gate #1 (read-only registry): HARD-FAIL — {len(violations)} violation(s):")
    for v in violations:
        print(f"  {v.render()}")
    print("\nRead-only boundary (AD-3 / §3.8) violated. Merge blocked.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
