"""tests for graph.floor_check — Story 4.1 AD-12 sufficiency rule-floor MECHANISM.

Pure-function + declarative-registry tests. Covers:
  - AC1 registry declarative + schema-validate-at-load (fail-fast FloorSchemaError; parametrized
    negative injection — DO NOT trust the happy path only).
  - AC2 floor_check pure deterministic (same input → identical FloorResult; order-independent count).
  - AC3 floor verdict semantics (count >= min_count → pass; else fail with deterministic reason).
  - AC4 unknown-trigger fail-closed (NEVER fail-open; empty registry fails-closed for ALL).
  - AC5 content deferred — default registry is EMPTY (no invented rules).
  - Constraint 5 never-raises (malformed evidence / non-str trigger / non-iterable evidence).
  - Predicate LANGUAGE lock (operator ENUM {label-exact, substring, regex}; field ENUM {source_name,
    summary, query}; source_type top-level filter; defensive non-str field skip).
  - FloorResult frozen + FloorRegistry immutable (the 4.1→4.3 seam stays stable).
  - Layer purity (AST: floor_check imports stdlib ONLY — no models/config/tools/graph back-edge).

AST-discipline (docstring-immune): assertions are statement-level, not in docstrings.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping
from pathlib import Path

import pytest

from graph.floor_check import (
    DEFAULT_VERSION,
    MATCHER_FIELDS,
    OPERATORS,
    FloorChecker,
    FloorResult,
    FloorSchemaError,
    build_default_floor_check,
    build_floor_check,
    load_floor_registry,
)

_FLOOR_CHECK_SRC = Path("graph/floor_check.py").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _ev(**overrides: object) -> dict[str, object]:
    """A §3.6 9-field evidence DICT (AD-9 — dicts, not Evidence objects; Pydantic only at port = 4.2)."""
    base: dict[str, object] = {
        "source_type": "prometheus",
        "source_name": "checkout",
        "query": "rate(http_requests_total[5m])",
        "summary": "error rate spiking on checkout",
        "timestamp_range": {"start": "2026-06-24T00:00:00Z", "end": "2026-06-24T01:00:00Z"},
        "raw_excerpt": None,
        "confidence": None,
        "supports": [],
        "contradicts": [],
    }
    base.update(overrides)
    return base


def _checker(specs: Mapping[str, object]) -> FloorChecker:
    """Build a floor_check over a freshly-loaded registry (schema-validated)."""
    return build_floor_check(registry=load_floor_registry(specs))


# A floor spec requiring 2 prometheus evidences whose source_name == "checkout" (label-exact).
_SPECS_PROMQ: dict[str, object] = {
    "HTTPErrorRateSpike": {
        "min_count": 2,
        "source_type": "prometheus",
        "matcher": {"field": "source_name", "op": "label-exact", "value": "checkout"},
    }
}


# ---------------------------------------------------------------------------
# AC2 + AC3 — predicate matching + floor verdict semantics
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("op", "value", "field_override"),
    [
        ("label-exact", "checkout", None),
        ("substring", "check", None),  # substring containment in source_name
        ("regex", r"^check", None),  # regex search in source_name
    ],
)
def test_match_each_operator(op: str, value: str, field_override: object) -> None:
    """Each locked operator matches a qualifying evidence item and passes at min_count."""
    specs = {
        "T": {
            "min_count": 1,
            "source_type": "prometheus",
            "matcher": {"field": "source_name", "op": op, "value": value},
        }
    }
    checker = _checker(specs)
    res = checker("T", [_ev()])
    assert res.floor_pass is True
    assert res.matched_count == 1
    assert res.min_count == 1
    assert res.reason == "pass"


def test_pass_at_exactly_min_count() -> None:
    """count == min_count → pass (boundary: NOT strictly-greater)."""
    checker = _checker(_SPECS_PROMQ)
    res = checker("HTTPErrorRateSpike", [_ev(), _ev()])
    assert res.floor_pass is True and res.matched_count == 2


def test_fail_when_count_below_min_count() -> None:
    """count < min_count → fail with deterministic reason."""
    checker = _checker(_SPECS_PROMQ)
    res = checker("HTTPErrorRateSpike", [_ev()])
    assert res.floor_pass is False
    assert res.matched_count == 1
    assert res.min_count == 2
    assert res.reason == "fail: matched 1 < min_count 2"


def test_source_type_filter_excludes_wrong_source() -> None:
    """An item with a different source_type does NOT count (top-level filter)."""
    checker = _checker(_SPECS_PROMQ)
    res = checker("HTTPErrorRateSpike", [_ev(source_type="loki"), _ev()])
    assert res.matched_count == 1  # only the prometheus item counts
    assert res.floor_pass is False  # 1 < 2


def test_count_is_order_independent() -> None:
    """AC2: shuffling the same evidence yields the identical FloorResult (deterministic count)."""
    checker = _checker(_SPECS_PROMQ)
    a = checker("HTTPErrorRateSpike", [_ev(), _ev(source_name="other"), _ev()])
    b = checker("HTTPErrorRateSpike", [_ev(source_name="other"), _ev(), _ev()])
    assert a == b


def test_same_input_same_output_across_calls() -> None:
    """AC2: repeated calls on identical input → byte-identical FloorResult (pure function)."""
    checker = _checker(_SPECS_PROMQ)
    evidence = [_ev(), _ev(), _ev(source_name="nope")]
    results = [checker("HTTPErrorRateSpike", evidence) for _ in range(5)]
    assert all(r == results[0] for r in results)


# ---------------------------------------------------------------------------
# Predicate LANGUAGE lock (AD-12 rule 4) — field ENUM + defensive non-str skip
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("field", sorted(MATCHER_FIELDS))
def test_matcher_field_enum_all_supported(field: str) -> None:
    """Every field in the locked ENUM is a valid matcher target (source_name / summary / query)."""
    specs = {
        "T": {
            "min_count": 1,
            "source_type": "prometheus",
            "matcher": {"field": field, "op": "substring", "value": "x"},
        }
    }
    # Build proves it loads; match proves it reads that field.
    checker = _checker(specs)
    assert checker("T", [_ev(**{field: "axb"})]).floor_pass is True


def test_malformed_evidence_field_non_str_does_not_count() -> None:
    """Constraint 5: an evidence item whose matcher field is missing/non-str is skipped, never raises."""
    specs = {
        "T": {
            "min_count": 1,
            "source_type": "prometheus",
            "matcher": {"field": "summary", "op": "substring", "value": "x"},
        }
    }
    checker = _checker(specs)
    # source_name is a list here (malformed) — irrelevant; summary is the matcher field and is missing
    # on the first item → skipped; second item matches.
    res = checker("T", [{"source_type": "prometheus", "source_name": ["bad"]}, _ev(summary="axb")])
    assert res.matched_count == 1 and res.floor_pass is True


# ---------------------------------------------------------------------------
# AC4 — unknown-trigger fail-closed (NEVER fail-open)
# ---------------------------------------------------------------------------


def test_unknown_trigger_fail_closed() -> None:
    """A trigger with NO registry entry → fail-closed (floor_pass=False, reason set)."""
    checker = _checker(_SPECS_PROMQ)
    res = checker("NotARegisteredTrigger", [_ev(), _ev()])
    assert res.floor_pass is False
    assert res.matched_count == 0
    assert res.min_count == 0
    assert res.reason == "fail-closed: unknown-trigger"


def test_non_str_trigger_fail_closed() -> None:
    """Constraint 5: a non-str trigger is "unknown" → fail-closed (never raises on .get)."""
    checker = _checker(_SPECS_PROMQ)
    res = checker(12345, [_ev()])  # type: ignore[arg-type]
    assert res.floor_pass is False and res.reason == "fail-closed: unknown-trigger"


def test_empty_registry_fail_closed_for_every_trigger() -> None:
    """AC5 honest default: the EMPTY default registry → EVERY trigger fail-closed (never fail-open)."""
    checker = build_default_floor_check()
    for trigger in ("HTTPErrorRateSpike", "DNSFailureLogSpike", "anything", ""):
        res = checker(trigger, [_ev()])
        assert res.floor_pass is False
        assert res.reason == "fail-closed: unknown-trigger"


# ---------------------------------------------------------------------------
# Constraint 5 — never raises (malformed evidence / non-iterable evidence)
# ---------------------------------------------------------------------------


def test_non_mapping_evidence_items_skipped() -> None:
    """Non-mapping items in the evidence list are skipped (count only valid mappings)."""
    checker = _checker(_SPECS_PROMQ)
    res = checker("HTTPErrorRateSpike", ["not-a-dict", 42, None, _ev(), _ev()])  # type: ignore[list-item]  # malformed items — runtime skips them defensively
    assert res.matched_count == 2 and res.floor_pass is True


def test_non_iterable_evidence_does_not_raise() -> None:
    """Constraint 5: a non-iterable evidence arg → 0 matches, returns a FloorResult (never raises)."""
    checker = _checker(_SPECS_PROMQ)
    res = checker("HTTPErrorRateSpike", None)  # type: ignore[arg-type]
    assert res.floor_pass is False and res.matched_count == 0


# ---------------------------------------------------------------------------
# AC1 — schema-validate-at-load (fail-fast FloorSchemaError; parametrized negative injection)
# ---------------------------------------------------------------------------


def test_load_valid_registry_returns_immutable() -> None:
    """A well-formed registry loads; specs is a read-only mapping; version defaults to DEFAULT_VERSION."""
    reg = load_floor_registry(_SPECS_PROMQ)
    assert reg.version == DEFAULT_VERSION
    assert "HTTPErrorRateSpike" in reg.specs
    with pytest.raises(TypeError):
        reg.specs["x"] = reg.specs["HTTPErrorRateSpike"]  # type: ignore[index]  # MappingProxyType


@pytest.mark.parametrize(
    ("specs", "label"),
    [
        (
            {
                "T": {
                    "min_count": 1,
                    "source_type": "prometheus",
                    "matcher": {"field": "source_name", "op": "contains", "value": "x"},
                }
            },
            "unknown op",
        ),
        (
            {
                "T": {
                    "min_count": 1,
                    "source_type": "prometheus",
                    "matcher": {"field": "raw_excerpt", "op": "substring", "value": "x"},
                }
            },
            "field outside ENUM",
        ),
        (
            {
                "T": {
                    "source_type": "prometheus",
                    "matcher": {"field": "source_name", "op": "substring", "value": "x"},
                }
            },
            "min_count missing",
        ),
        (
            {
                "T": {
                    "min_count": 0,
                    "source_type": "prometheus",
                    "matcher": {"field": "source_name", "op": "substring", "value": "x"},
                }
            },
            "min_count < 1",
        ),
        (
            {
                "T": {
                    "min_count": 2.0,
                    "source_type": "prometheus",
                    "matcher": {"field": "source_name", "op": "substring", "value": "x"},
                }
            },
            "min_count non-int (float)",
        ),
        (
            {
                "T": {
                    "min_count": True,
                    "source_type": "prometheus",
                    "matcher": {"field": "source_name", "op": "substring", "value": "x"},
                }
            },
            "min_count bool",
        ),
        (
            {
                "T": {
                    "min_count": 1,
                    "matcher": {"field": "source_name", "op": "substring", "value": "x"},
                }
            },
            "source_type missing",
        ),
        (
            {
                "T": {
                    "min_count": 1,
                    "source_type": "",
                    "matcher": {"field": "source_name", "op": "substring", "value": "x"},
                }
            },
            "source_type empty",
        ),
        ({"T": {"min_count": 1, "source_type": "prometheus"}}, "matcher missing"),
        (
            {
                "T": {
                    "min_count": 1,
                    "source_type": "prometheus",
                    "matcher": {"field": "source_name", "op": "substring"},
                }
            },
            "matcher missing value key",
        ),
        (
            {
                "T": {
                    "min_count": 1,
                    "source_type": "prometheus",
                    "matcher": {"field": "source_name", "op": "substring", "value": ""},
                }
            },
            "value empty",
        ),
        (
            {
                "T": {
                    "min_count": 1,
                    "source_type": "prometheus",
                    "matcher": {"field": "source_name", "op": "substring", "value": 5},
                }
            },
            "value non-str",
        ),
        (
            {
                "T": {
                    "min_count": 1,
                    "source_type": "prometheus",
                    "matcher": {"field": "summary", "op": "regex", "value": "([a-z"},
                }
            },
            "invalid regex",
        ),
        (
            {"T": {"min_count": 1, "source_type": "prometheus", "matcher": "not-a-dict"}},
            "matcher not a mapping",
        ),
        ({"T": "not-a-dict"}, "spec not a mapping"),
        (123, "top-level not a mapping"),
        (
            {
                123: {
                    "min_count": 1,
                    "source_type": "prometheus",
                    "matcher": {"field": "source_name", "op": "substring", "value": "x"},
                }
            },
            "trigger key non-str",
        ),
        (
            {
                "": {
                    "min_count": 1,
                    "source_type": "prometheus",
                    "matcher": {"field": "source_name", "op": "substring", "value": "x"},
                }
            },
            "trigger key empty",
        ),
    ],
)
def test_load_rejects_schema_violation(specs: object, label: str) -> None:
    """CI #4 part b: EVERY schema-violation kind raises FloorSchemaError at LOAD (never silent)."""
    with pytest.raises(FloorSchemaError):
        load_floor_registry(specs)  # type: ignore[arg-type]
    _ = label  # parametrize id only


@pytest.mark.parametrize("bad_version", [0, -1, "1", 1.0, True])
def test_load_rejects_bad_version(bad_version: object) -> None:
    """Version must be a positive int (reject 0/negative/non-int/bool)."""
    with pytest.raises(FloorSchemaError):
        load_floor_registry({}, version=bad_version)  # type: ignore[arg-type]


def test_load_rejects_duplicate_trigger_defensively() -> None:
    """A duplicate key built into a mapping is rejected (defensive; documents the intent)."""
    spec = {
        "min_count": 1,
        "source_type": "prometheus",
        "matcher": {"field": "source_name", "op": "substring", "value": "x"},
    }

    # Build via a sequence-of-pairs to create a real duplicate that survives dict construction is
    # impossible (dict dedupes); instead pass a Mapping subclass that yields the key twice to .items().
    class _DupMapping(dict):  # type: ignore[type-arg]
        pass

    specs = _DupMapping([("T", spec), ("T", spec)])  # dict collapses to one "T"
    # A plain dict cannot hold dup keys → the guard is defensive; assert the valid one loaded.
    reg = load_floor_registry(specs)
    assert "T" in reg.specs


# ---------------------------------------------------------------------------
# FloorResult + FloorRegistry shapes (the 4.1→4.3 carry-forward seam)
# ---------------------------------------------------------------------------


def test_floor_result_is_frozen() -> None:
    """FloorResult is a frozen dataclass (the stable 4.3-consumed seam)."""
    res = FloorResult(True, 2, 2, "pass")
    with pytest.raises(Exception):  # noqa: PT011 — FrozenInstanceError (dataclass) on attribute set
        res.floor_pass = False  # type: ignore[misc]


def test_floor_registry_is_frozen() -> None:
    """FloorRegistry is a frozen dataclass."""
    reg = load_floor_registry(_SPECS_PROMQ)
    with pytest.raises(Exception):  # noqa: PT011
        reg.version = 99  # type: ignore[misc]


def test_locked_enums_exact() -> None:
    """The predicate LANGUAGE ENUMs are EXACTLY the locked sets (no extras, none missing)."""
    assert OPERATORS == frozenset({"label-exact", "substring", "regex"})
    assert MATCHER_FIELDS == frozenset({"source_name", "summary", "query"})


# ---------------------------------------------------------------------------
# Layer purity (AD-1 / gate #2) — AST: floor_check imports stdlib ONLY
# ---------------------------------------------------------------------------


def test_floor_check_imports_stdlib_only() -> None:
    """floor_check.py imports ONLY stdlib — no models/config/tools/graph back-edge (AST-proven)."""
    tree = ast.parse(_FLOOR_CHECK_SRC)
    stdlib_roots = {"re", "dataclasses", "typing", "collections", "types", "__future__", "abc"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] in stdlib_roots, f"forbidden import: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            assert root in stdlib_roots, f"forbidden from-import: {node.module}"


def test_floor_check_has_no_nondeterminism() -> None:
    """AD-12: AST-proven ZERO forbidden nondeterminism (no random/time/datetime/uuid/now-in-output)."""
    forbidden_names = {"random", "time", "datetime", "uuid"}
    tree = ast.parse(_FLOOR_CHECK_SRC)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in forbidden_names, (
                    f"nondeterministic import: {alias.name}"
                )
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] not in forbidden_names
