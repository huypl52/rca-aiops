"""CI gate #5 — contract schema preservation self-test (Story 0.2 — AC4/AC5/T4).

Asserts the Pydantic contract models match the spec-derived field vocabulary
in `ci.contract_schema` (single source of truth, NOT derived from the models):

  - `IncidentTrigger` == 18 fields §3.4 + `incident_id` (H3 add-on)
  - `Evidence`        == 9 fields §3.6, tiered (required / optional / derived)

FAIL-on-drift: if a field is added / renamed / removed from either model, the
field-set equality breaks and this test fails → CI gate #5 blocks merge
(AD-13 #5 / AD-6). We never trust "model passes" — a negative test injects a
real drifted model (pydantic `create_model`) and proves the assertion catches
it (lesson: a gate that derives its expected-set from the model itself is
tautological and catches nothing).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pytest
from pydantic import BaseModel, create_model

from ci.contract_schema import (
    EVIDENCE_DERIVED,
    EVIDENCE_OPTIONAL_NULLABLE,
    EVIDENCE_REQUIRED,
    INCIDENT_TRIGGER_GROUPING_FIELDS,
    SPEC_EVIDENCE_FIELDS,
    SPEC_INCIDENT_TRIGGER_FIELDS,
    TRIGGER_SEVERITIES,
    TRIGGER_SIGNAL_TYPES,
    TRIGGER_SOURCES,
)
from models import Evidence, IncidentTrigger, Severity, SignalType, TimestampRange, TriggerSource

EXPECTED_TRIGGER_FIELDS: frozenset[str] = frozenset(SPEC_INCIDENT_TRIGGER_FIELDS) | frozenset(
    INCIDENT_TRIGGER_GROUPING_FIELDS
)
EXPECTED_EVIDENCE_FIELDS: frozenset[str] = frozenset(SPEC_EVIDENCE_FIELDS)


def _assert_contract_fields(model: type[BaseModel], expected: Iterable[str]) -> None:
    """Raise AssertionError unless ``model``'s field-set equals ``expected``.

    Shared by the positive assertions (must pass) and the negative drift tests
    (must raise). Comparing sets catches add / rename / remove uniformly.
    """
    actual = set(model.model_fields.keys())
    expected_set = set(expected)
    assert actual == expected_set, (
        f"contract drift in {model.__name__}:\n"
        f"  expected ({len(expected_set)}): {sorted(expected_set)}\n"
        f"  actual   ({len(actual)}): {sorted(actual)}\n"
        f"  missing  : {sorted(expected_set - actual)}\n"
        f"  extra    : {sorted(actual - expected_set)}"
    )


# ---------------------------------------------------------------------------
# Positive — IncidentTrigger (AC1)
# ---------------------------------------------------------------------------


def test_incident_trigger_field_set_matches_spec_3_4() -> None:
    """IncidentTrigger must expose exactly the 18 §3.4 fields + incident_id."""
    _assert_contract_fields(IncidentTrigger, EXPECTED_TRIGGER_FIELDS)


def test_incident_trigger_has_exactly_18_spec_fields() -> None:
    """The §3.4 portion (excluding the incident_id add-on) is exactly 18 fields."""
    spec_fields = set(IncidentTrigger.model_fields.keys()) - set(INCIDENT_TRIGGER_GROUPING_FIELDS)
    assert len(spec_fields) == 18, (
        f"§3.4 must be 18 fields, got {len(spec_fields)}: {sorted(spec_fields)}"
    )


def test_raw_payload_ref_is_present_row_18() -> None:
    """`raw_payload_ref` is §3.4 row 18 (lesson D-1: 17-vs-18 miscount). It must exist."""
    assert "raw_payload_ref" in IncidentTrigger.model_fields, (
        "raw_payload_ref (§3.4 row 18) missing"
    )
    assert "raw_payload_ref" in SPEC_INCIDENT_TRIGGER_FIELDS


def test_incident_id_is_optional_grouping_addon() -> None:
    """`incident_id` is the optional H3 grouping add-on (FR-2/DEC-1), NOT a §3.4 field."""
    assert "incident_id" in IncidentTrigger.model_fields
    assert "incident_id" not in SPEC_INCIDENT_TRIGGER_FIELDS
    assert "incident_id" in INCIDENT_TRIGGER_GROUPING_FIELDS
    # Optional → not required, defaults to None.
    assert not IncidentTrigger.model_fields["incident_id"].is_required()


# ---------------------------------------------------------------------------
# Positive — IncidentTrigger enums (AC2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("enum_cls", "expected"),
    [
        (TriggerSource, TRIGGER_SOURCES),
        (Severity, TRIGGER_SEVERITIES),
        (SignalType, TRIGGER_SIGNAL_TYPES),
    ],
    ids=["source", "severity", "signal_type"],
)
def test_incident_trigger_enum_domains(enum_cls: type[Any], expected: frozenset[str]) -> None:
    """source / severity / signal_type enum members must match spec §3.4 domains."""
    assert {member.value for member in enum_cls} == set(expected)


# ---------------------------------------------------------------------------
# Positive — Evidence (AC3)
# ---------------------------------------------------------------------------


def test_evidence_field_set_matches_spec_3_6() -> None:
    """Evidence must expose exactly the 9 §3.6 fields."""
    _assert_contract_fields(Evidence, EXPECTED_EVIDENCE_FIELDS)
    assert len(EXPECTED_EVIDENCE_FIELDS) == 9


def test_evidence_required_fields_are_non_null() -> None:
    """Required tier fields must be non-null (no default) — project-context Cat 2."""
    for name in EVIDENCE_REQUIRED:
        assert Evidence.model_fields[name].is_required(), (
            f"required field '{name}' must be non-null"
        )


def test_evidence_optional_nullable_fields_default_none() -> None:
    """Optional-nullable tier fields must default to None."""
    for name in EVIDENCE_OPTIONAL_NULLABLE:
        field = Evidence.model_fields[name]
        assert not field.is_required(), f"optional field '{name}' must not be required"
        assert field.default is None, f"optional-nullable field '{name}' must default to None"


def test_evidence_derived_fields_are_non_null_lists() -> None:
    """Derived tier (supports/contradicts) must be list, defaulting to [] — NEVER null."""
    for name in EVIDENCE_DERIVED:
        field = Evidence.model_fields[name]
        assert field.default_factory is list, (
            f"derived field '{name}' must use default_factory=list ([] non-null)"
        )
        assert not field.is_required(), f"derived field '{name}' must not be required"


def test_timestamp_range_is_start_end() -> None:
    """timestamp_range = {start, end} ISO-8601 UTC; start required, end optional-nullable."""
    fields = TimestampRange.model_fields
    assert set(fields.keys()) == {"start", "end"}
    assert fields["start"].is_required()
    assert not fields["end"].is_required()
    assert fields["end"].default is None


# ---------------------------------------------------------------------------
# Negative — FAIL-on-drift (AC5). Proves gate #5 catches a real drift.
# ---------------------------------------------------------------------------


def test_gate5_catches_added_field_on_trigger() -> None:
    """An invented field added to IncidentTrigger → assertion FAILS (drift caught)."""
    drifted = create_model(
        "DriftedTrigger",
        __base__=IncidentTrigger,
        invented_field=(str | None, None),
    )
    with pytest.raises(AssertionError, match="extra"):
        _assert_contract_fields(drifted, EXPECTED_TRIGGER_FIELDS)


def test_gate5_catches_added_field_on_evidence() -> None:
    """An invented field added to Evidence → assertion FAILS (drift caught)."""
    drifted = create_model(
        "DriftedEvidence",
        __base__=Evidence,
        invented_field=(str | None, None),
    )
    with pytest.raises(AssertionError, match="extra"):
        _assert_contract_fields(drifted, EXPECTED_EVIDENCE_FIELDS)


def test_gate5_catches_removed_field() -> None:
    """A spec field removed from the expected set → assertion FAILS (rename/delete caught)."""
    expected_missing_one = EXPECTED_TRIGGER_FIELDS - {"severity"}
    with pytest.raises(AssertionError, match="missing"):
        _assert_contract_fields(IncidentTrigger, expected_missing_one)


def test_gate5_catches_renamed_field() -> None:
    """A renamed field (drop + add) → assertion FAILS on both missing and extra."""
    renamed = (EXPECTED_TRIGGER_FIELDS - {"severity"}) | {"urgency"}
    with pytest.raises(AssertionError):
        _assert_contract_fields(IncidentTrigger, renamed)
