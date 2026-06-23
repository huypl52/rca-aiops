"""Package smoke test (Story 0.1 — AC1/AC8).

Asserts every scaffolded Python package imports cleanly. This is the ONLY
business-level test in Story 0.1: the scaffold must be importable end-to-end
with no business logic (Constrain AC8 — contract models live in Story 0.2).
"""

import importlib

import pytest

# Python packages created by the scaffold (Story 0.1).
# playbooks/ and checkpoints/ are DATA dirs (no __init__.py) — intentionally excluded.
PACKAGES = [
    "routers",
    "services",
    "graph",
    "adapters",
    "tools",
    "models",
    "eval",
    "config",
    "ci",
]


@pytest.mark.parametrize("pkg", PACKAGES)
def test_package_imports(pkg: str) -> None:
    """Each scaffolded package must be importable and expose a docstring."""
    module = importlib.import_module(pkg)
    assert module.__doc__, f"package {pkg} missing responsibility docstring (AC1)"


def test_one_way_chain_packages_all_importable() -> None:
    """The 5 architectural layers of the one-way chain must all import (AD-1)."""
    for layer in ("routers", "services", "graph", "adapters", "tools"):
        importlib.import_module(layer)
