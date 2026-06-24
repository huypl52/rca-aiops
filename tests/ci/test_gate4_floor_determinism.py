"""CI gate #4 — Floor determinism (AD-13 #4 / AD-12 / DEC-3). Story 4.1.

The deterministic anti-hallucination rule-floor MUST be provably pure + its registry MUST fail-fast on a
malformed schema. This gate asserts BOTH (mirrors the gate #5 lesson: a gate that does NOT inject a
negative case proves nothing — so each violation kind is injected explicitly).

**(a) Pure-function determinism (AD-12).** ``floor_check`` is a PURE function of
``(canonical_trigger, evidence)``:
  - same input → byte-identical ``FloorResult`` across repeated calls (in-process);
  - order-independent count (shuffled evidence → identical verdict);
  - **PYTHONHASHSEED-safe** (the critical one — proof across two independent interpreter processes with
    DIFFERENT hash seeds → identical serialized verdict; a hidden dict-order/set-hash dependency would
    diverge here).
  - AST: ZERO forbidden nondeterminism sources (no random/time/datetime/uuid imported).

**(b) Registry schema-validate-at-load (fail-fast).** ``load_floor_registry`` RAISES ``FloorSchemaError``
for EVERY §2.5 violation kind (parametrized negative injection — unknown op, field outside ENUM,
min_count missing/<1/non-int/bool, source_type missing/empty, matcher missing key / not-a-mapping /
value empty-or-non-str / invalid regex, top-level not-a-mapping, key non-str/empty, bad version). And the
SHIPPED ``config/floor_registry.yaml`` loads cleanly through the loader (schema-validate-on-real-data).

Bind: ``uv run pytest tests/ci/test_gate4_floor_determinism.py -v`` (HARD-FAIL).
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]  # third-party stubs not shipped (consistent w/ pyproject mypy override)

from graph.floor_check import (
    FloorRegistry,
    FloorResult,
    FloorSchemaError,
    build_default_floor_check,
    build_floor_check,
    load_floor_registry,
)

_FLOOR_CHECK_SRC = Path("graph/floor_check.py").read_text(encoding="utf-8")
_FLOOR_REGISTRY_YAML = Path("config/floor_registry.yaml")

# A minimal valid registry used by the determinism probe (registry injected at factory time).
_PROBE_SPECS: dict[str, object] = {
    "HTTPErrorRateSpike": {
        "min_count": 2,
        "source_type": "prometheus",
        "matcher": {"field": "source_name", "op": "regex", "value": r"^checkout"},
    }
}


def _probe_evidence() -> list[dict[str, object]]:
    """A FIXED evidence list for the determinism probe (deterministic content; order varies per test)."""
    one: dict[str, object] = {
        "source_type": "prometheus",
        "source_name": "checkout-prod",
        "query": "up",
        "summary": "error rate spiking",
    }
    other: dict[str, object] = {
        "source_type": "loki",
        "source_name": "checkout-logs",
        "query": '{app="checkout"}',
        "summary": "boom",
    }
    return [one, other, {**one, "source_name": "checkout-canary"}]


def _verdict_tuple(result: FloorResult) -> tuple[object, ...]:
    """Serialize a FloorResult to a hash/order-independent tuple for cross-process comparison."""
    return (result.floor_pass, result.matched_count, result.min_count, result.reason)


# ---------------------------------------------------------------------------
# (a) Pure-function determinism
# ---------------------------------------------------------------------------


def test_same_input_identical_result_across_calls() -> None:
    """(a) Repeated calls on identical input → identical FloorResult (pure function)."""
    checker = build_floor_check(registry=load_floor_registry(_PROBE_SPECS))
    ev = _probe_evidence()
    results = [checker("HTTPErrorRateSpike", ev) for _ in range(10)]
    assert all(_verdict_tuple(r) == _verdict_tuple(results[0]) for r in results)


def test_count_is_order_independent() -> None:
    """(a) Shuffling evidence order does not change the verdict (deterministic count, not order)."""
    checker = build_floor_check(registry=load_floor_registry(_PROBE_SPECS))
    ev = _probe_evidence()
    shuffled = list(reversed(ev))
    assert _verdict_tuple(checker("HTTPErrorRateSpike", ev)) == _verdict_tuple(
        checker("HTTPErrorRateSpike", shuffled)
    )


@pytest.mark.parametrize("seed", [0, 1, 7, 42, 99])
def test_floor_check_is_pythonhashseed_safe(seed: int) -> None:
    """(a) CRITICAL: identical verdict regardless of PYTHONHASHSEED (cross-process; sets/dicts only used
    in ways that must not leak ordering into the output). Run each seed in a FRESH interpreter."""
    code = (
        "import sys; from graph.floor_check import build_floor_check, load_floor_registry; "
        "ev = [{'source_type':'prometheus','source_name':'checkout-prod','query':'up','summary':'x'},"
        "{'source_type':'loki','source_name':'y','query':'z','summary':'w'},"
        "{'source_type':'prometheus','source_name':'checkout-canary','query':'u','summary':'v'}]; "
        "specs = {'HTTPErrorRateSpike':{'min_count':2,'source_type':'prometheus',"
        "'matcher':{'field':'source_name','op':'regex','value':r'^checkout'}}}; "
        "c = build_floor_check(registry=load_floor_registry(specs)); "
        "r = c('HTTPErrorRateSpike', ev); "
        "print(repr((r.floor_pass, r.matched_count, r.min_count, r.reason)))"
    )
    env = {**os.environ, "PYTHONHASHSEED": str(seed)}
    out = subprocess.run(
        [sys.executable, "-c", code], check=True, capture_output=True, text=True, env=env, cwd="."
    )
    expected = "(True, 2, 2, 'pass')"
    assert out.stdout.strip() == expected, (
        f"PYTHONHASHSEED={seed} produced non-deterministic verdict {out.stdout.strip()!r}"
    )


def test_floor_check_ast_has_no_nondeterminism_sources() -> None:
    """(a) AST: floor_check.py imports NO random/time/datetime/uuid (the deterministic backbone)."""
    forbidden = {"random", "time", "datetime", "uuid"}
    tree = ast.parse(_FLOOR_CHECK_SRC)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in forbidden, (
                    f"nondeterministic import: {alias.name}"
                )
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] not in forbidden


# ---------------------------------------------------------------------------
# (b) Registry schema-validate-at-load (parametrized negative injection — fail-fast)
# ---------------------------------------------------------------------------


_GOOD_MATCHER: dict[str, object] = {"field": "source_name", "op": "substring", "value": "x"}


def _good_spec() -> dict[str, object]:
    return {"min_count": 1, "source_type": "prometheus", "matcher": dict(_GOOD_MATCHER)}


@pytest.mark.parametrize(
    ("specs", "label"),
    [
        # operator ENUM
        (
            {
                "T": {
                    **_good_spec(),
                    "matcher": {"field": "source_name", "op": "contains", "value": "x"},
                }
            },
            "unknown op",
        ),
        # field ENUM
        (
            {
                "T": {
                    **_good_spec(),
                    "matcher": {"field": "raw_excerpt", "op": "substring", "value": "x"},
                }
            },
            "field outside ENUM",
        ),
        (
            {
                "T": {
                    **_good_spec(),
                    "matcher": {"field": "confidence", "op": "substring", "value": "x"},
                }
            },
            "field=confidence (float field)",
        ),
        # min_count
        ({"T": {k: v for k, v in _good_spec().items() if k != "min_count"}}, "min_count missing"),
        ({"T": {**_good_spec(), "min_count": 0}}, "min_count < 1"),
        ({"T": {**_good_spec(), "min_count": -3}}, "min_count negative"),
        ({"T": {**_good_spec(), "min_count": 2.0}}, "min_count float"),
        ({"T": {**_good_spec(), "min_count": True}}, "min_count bool True"),
        ({"T": {**_good_spec(), "min_count": "2"}}, "min_count str"),
        # source_type
        (
            {"T": {k: v for k, v in _good_spec().items() if k != "source_type"}},
            "source_type missing",
        ),
        ({"T": {**_good_spec(), "source_type": ""}}, "source_type empty"),
        ({"T": {**_good_spec(), "source_type": None}}, "source_type None"),
        # matcher missing / shape
        ({"T": {k: v for k, v in _good_spec().items() if k != "matcher"}}, "matcher missing"),
        ({"T": {**_good_spec(), "matcher": "not-a-mapping"}}, "matcher not a mapping"),
        (
            {"T": {**_good_spec(), "matcher": {"op": "substring", "value": "x"}}},
            "matcher missing field",
        ),
        (
            {"T": {**_good_spec(), "matcher": {"field": "source_name", "value": "x"}}},
            "matcher missing op",
        ),
        (
            {"T": {**_good_spec(), "matcher": {"field": "source_name", "op": "substring"}}},
            "matcher missing value",
        ),
        (
            {
                "T": {
                    **_good_spec(),
                    "matcher": {"field": "source_name", "op": "substring", "value": ""},
                }
            },
            "value empty",
        ),
        (
            {
                "T": {
                    **_good_spec(),
                    "matcher": {"field": "source_name", "op": "substring", "value": 5},
                }
            },
            "value non-str",
        ),
        # regex MUST compile at load
        (
            {
                "T": {
                    **_good_spec(),
                    "matcher": {"field": "summary", "op": "regex", "value": "([a-z"},
                }
            },
            "invalid regex",
        ),
        # top-level + key shape
        ("not-a-mapping", "top-level not a mapping"),
        (
            [{"min_count": 1, "source_type": "prometheus", "matcher": _GOOD_MATCHER}],
            "top-level a list",
        ),
        ({123: _good_spec()}, "trigger key non-str"),
        ({"": _good_spec()}, "trigger key empty"),
        ({"T": "not-a-mapping"}, "spec not a mapping"),
    ],
)
def test_load_floor_registry_rejects_schema_violation(specs: object, label: str) -> None:
    """(b) EVERY schema-violation kind raises FloorSchemaError at LOAD (fail-fast; never silent)."""
    with pytest.raises(FloorSchemaError):
        load_floor_registry(specs)  # type: ignore[arg-type]
    _ = label  # parametrize id only


@pytest.mark.parametrize("bad_version", [0, -1, "1", 1.5, True])
def test_load_floor_registry_rejects_bad_version(bad_version: object) -> None:
    """(b) Version must be a positive int (reject <=0 / non-int / bool)."""
    with pytest.raises(FloorSchemaError):
        load_floor_registry({}, version=bad_version)  # type: ignore[arg-type]


def test_shipped_floor_registry_yaml_loads_cleanly() -> None:
    """(b) The SHIPPED config/floor_registry.yaml passes load_floor_registry (schema-validate-on-real-data).

    The POC default is EMPTY (D3 content DEFERRED — honest fail-closed-for-all); this proves the shipped
    data + version tag are well-formed under the locked schema (a malformed YAML would be a silent
    production regression caught here, at gate time).
    """
    raw = yaml.safe_load(_FLOOR_REGISTRY_YAML.read_text(encoding="utf-8"))
    assert isinstance(raw, dict), "floor_registry.yaml must parse to a mapping at top level"
    version = raw.get("version", 1)
    floors = raw.get("floors", {})
    assert isinstance(floors, dict), "floor_registry.yaml `floors` must be a mapping"
    # The composition root (4.3) will pass the parsed `floors` mapping to load_floor_registry.
    reg = load_floor_registry(floors, version=int(version) if isinstance(version, int) else 1)
    assert isinstance(reg, FloorRegistry)
    assert reg.version == 1  # POC default version (D3 content deferred)
    assert len(reg.specs) == 0  # EMPTY honest default (no invented rules)


def test_empty_registry_is_honest_fail_closed_for_all() -> None:
    """(b) The shipped EMPTY registry → build_default_floor_check fails-closed for EVERY trigger."""
    checker = build_default_floor_check()
    for trigger in ("HTTPErrorRateSpike", "DNSFailureLogSpike", "PodCrashLooping", ""):
        r = checker(
            trigger,
            [{"source_type": "prometheus", "source_name": "x", "query": "q", "summary": "s"}],
        )
        assert isinstance(r, FloorResult)
        assert r.floor_pass is False
        assert r.reason == "fail-closed: unknown-trigger"
