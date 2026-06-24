"""Story 6.2 — the binary-conjunction MEASUREMENT INSTRUMENT (SM-1 honest baseline + SM-2 mechanism).

Covers the Story-6.2 DEEP spotlights:

  - **the HONEST BASELINE** — driving the FULL compiled §3.5 graph over all 11 §3.7 scenarios yields the
    5-A1 non-convergence baseline: ``status="partial"`` + ``report=None`` for all 11 → **SM-1 = 0%** with
    per-condition ``{a:11, b:11, c:0, d:0, e:0}``. The headline insight: (a) the inject→Evidence pipeline +
    (b) incident routing are SOUND; (c)/(d)/(e) FAIL because the agent never reaches EXR→ENV→WRT (5-A1).
    SM-1 = 0% IS THE INTENDED DELIVERABLE (NOT a defect; NOT fixed — R1). The honest baseline is the result.
  - **the INSTRUMENT is SOUND** (not weakened — R2/R3): each condition's pass/fail logic is verified on
    CONTROLLED synthetic terminal states, so a reader trusts the conditions WILL correctly fire once the
    graph converges (a future populated floor registry + hypothesis-advance, NOT built here). condition (e)
    is NON-WEAKENED (R2): a None/empty report is (e)=False; only a GROUNDED, correctly-sourced report passes.
  - **the SM-2 MECHANISM** (AD-7 single-authority, D4 no-cutoff) — :func:`calibration_summary` is a pure
    function of ``(assigned, actual)`` pairs; verified on synthetic well/over/under-calibrated pairs; applied
    to the real graph → 0 pairs → honestly ``"blocked"`` (no report-level confidence to calibrate; no
    fabrication of a synthetic verdict).
  - **the determinism prerequisite** — the conjunction blob is byte-stable across repeated in-process runs
    (the decisive cross-``PYTHONHASHSEED`` proof is gate #6, ``tests/ci/test_gate6_conjunction_determinism.py``).

The conjunction evaluator itself lives in :mod:`tests.conjunction_harness` (NOT collected by pytest — the
``test_`` prefix is HERE). This test imports it + asserts its honest output + its mechanism soundness.
"""

from __future__ import annotations

import json

import pytest

from eval import BENCHMARK_SCENARIOS
from eval.scenarios import DEPENDENCY_TIMEOUT
from eval.schema import Scenario
from tests.conjunction_harness import (
    calibration_summary,
    condition_b,
    condition_c,
    condition_d,
    condition_e,
    conjunction_blob,
    evaluate_scenario,
    sm1_overview,
    sm2_calibration,
)

# The 13-key AD-9 spine keys the terminal_state projection carries (the §2F make-or-break payload).
_SPINE_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "incident_id",
        "trigger",
        "context",
        "playbook_hits",
        "hypotheses",
        "plan",
        "tool_calls",
        "evidence",
        "sufficiency",
        "safety_flags",
        "next_action",
        "report",
    }
)


# ---------------------------------------------------------------------------
# The HONEST BASELINE — driving the FULL compiled graph over all 11 (5-A1 non-convergence).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("scenario", BENCHMARK_SCENARIOS, ids=lambda s: s.name)
def test_baseline_scenario_is_partial_with_no_report(scenario: Scenario) -> None:
    """5-A1: the POC graph does NOT converge → ``status="partial"`` + ``report=None`` for every scenario.

    The bounded HYP↔VAL loop (rule-based plans lack VAL's trio → VAL replans; empty floor registry → REF
    fail-closes) exhausts ``max_iterations`` → the honest PARTIAL (Story 4-3 / FR-7 / AD-10 #5), with NO
    report (EXR/ENV/WRT never run). This is the non-convergence the conjunction MEASURES — NOT a defect.
    """
    per_scenario = evaluate_scenario(scenario)
    assert per_scenario["status"] == "partial", (
        f"{scenario.name}: expected status='partial' (5-A1), got {per_scenario['status']!r}"
    )
    terminal_state = per_scenario["terminal_state"]
    assert isinstance(terminal_state, dict), f"{scenario.name}: terminal_state must be a dict"
    assert terminal_state.get("report") is None, (
        f"{scenario.name}: expected report=None (EXR/ENV/WRT never run — 5-A1)"
    )


@pytest.mark.parametrize("scenario", BENCHMARK_SCENARIOS, ids=lambda s: s.name)
def test_baseline_per_condition_is_the_locked_honest_baseline(scenario: Scenario) -> None:
    """The locked per-condition baseline per scenario: a=True, b=True, c/d/e=False (NOT fixed — R1).

    (a) the inject→Evidence PIPELINE is sound (6.1-confirmed); (b) the agent receives the correct incident's
    service; (c)/(d)/(e) FAIL because the agent never reaches EXR→ENV→WRT (the graph does not converge).
    """
    conditions = evaluate_scenario(scenario)["conditions"]
    assert isinstance(conditions, dict), f"{scenario.name}: conditions must be a dict"
    assert conditions["a"] is True, f"{scenario.name}: (a) inject→Evidence pipeline must hold (6.1)"
    assert conditions["b"] is True, (
        f"{scenario.name}: (b) agent must receive the correct incident's service"
    )
    assert conditions["c"] is False, (
        f"{scenario.name}: (c) must fail — EXR never runs (5-A1; honest baseline)"
    )
    assert conditions["d"] is False, (
        f"{scenario.name}: (d) must fail — ENV never runs (5-A1; honest baseline)"
    )
    assert conditions["e"] is False, (
        f"{scenario.name}: (e) must fail — report is None (5-A1; honest baseline)"
    )


def test_sm1_is_zero_with_per_condition_breakdown() -> None:
    """SM-1 = 0% with per-condition ``{a:11, b:11, c:0, d:0, e:0}`` — the honest 5-A1 baseline (R1: NOT fixed).

    The per-condition breakdown quantifies WHERE the gap bites: (a)/(b) hold (pipeline + routing sound),
    (c)/(d)/(e) do not (the agent never executes the EXR→ENV→WRT path). All 11 are scored (A8 ``prod_only``
    MARKS disk/memory; it does NOT exclude them from SM-1).
    """
    per_scenario = [evaluate_scenario(s) for s in BENCHMARK_SCENARIOS]
    sm1 = sm1_overview(per_scenario)
    assert sm1["n"] == 11
    assert sm1["n_pass"] == 0
    assert sm1["sm1"] == 0.0
    assert sm1["per_condition"] == {"a": 11, "b": 11, "c": 0, "d": 0, "e": 0}


def test_sm2_is_blocked_no_report_level_confidence() -> None:
    """SM-2: no reports → 0 calibration pairs → honestly ``"blocked"`` (no fabrication — AD-7/D4).

    The POC graph emits no reports (5-A1) → there is no report-level ``ceiling_confidence`` to read → 0
    ``(assigned, actual)`` pairs → the calibration metric is honestly blocked (NOT a fabricated verdict).
    """
    per_scenario = [evaluate_scenario(s) for s in BENCHMARK_SCENARIOS]
    sm2 = sm2_calibration(per_scenario)
    assert sm2["n_pairs"] == 0
    assert sm2["status"] == "blocked-no-report-level-confidence"
    assert sm2["gap"] is None  # honest: nothing to compute (no fabricated mean/gap)
    assert sm2["mean_assigned"] is None
    assert sm2["mean_actual"] is None


# ---------------------------------------------------------------------------
# The INSTRUMENT is SOUND — conditions fire correctly on CONTROLLED synthetic terminal states (R2/R3).
#
# The honest baseline (above) shows c/d/e=False for all 11 because the graph does not converge. These
# tests verify the CONDITIONS THEMSELVES are correct + non-weakened: on a CONTROLLED terminal state where
# the agent DID execute (synthetic), the conditions correctly pass/fail. So a reader trusts that once the
# graph converges (5-A1 fix — a SEPARATE story, R1), the conjunction will measure it faithfully.
# ---------------------------------------------------------------------------


def test_condition_b_passes_when_service_matches_otherwise_fails() -> None:
    """(b) context.service == scenario.service → True; a different service → False."""
    assert condition_b("order-service", DEPENDENCY_TIMEOUT) is True
    assert condition_b("payment-service", DEPENDENCY_TIMEOUT) is False
    assert condition_b(None, DEPENDENCY_TIMEOUT) is False


def test_condition_c_passes_when_tool_calls_cover_expected() -> None:
    """(c) the agent's tool_calls covering ALL expected adapter_methods → True; missing one → False."""
    expected = {
        ee.adapter_method for ee in DEPENDENCY_TIMEOUT.expected_evidence
    }  # {query_promql, query_loki}
    state_full = {"tool_calls": [{"tool": m} for m in expected]}
    assert condition_c(state_full, DEPENDENCY_TIMEOUT) is True
    # missing the loki call → does NOT cover expected → False.
    state_missing = {"tool_calls": [{"tool": "query_promql"}]}
    assert condition_c(state_missing, DEPENDENCY_TIMEOUT) is False
    # empty tool_calls → False.
    assert condition_c({"tool_calls": []}, DEPENDENCY_TIMEOUT) is False


def test_condition_d_passes_when_evidence_covers_expected() -> None:
    """(d) the agent's gathered evidence covering ALL expected source_types → True; missing one → False."""
    state_full = {
        "evidence": [
            {"source_type": "prometheus"},
            {"source_type": "loki"},
        ]
    }
    assert condition_d(state_full, DEPENDENCY_TIMEOUT) is True
    state_missing = {"evidence": [{"source_type": "prometheus"}]}  # missing loki
    assert condition_d(state_missing, DEPENDENCY_TIMEOUT) is False
    assert condition_d({"evidence": []}, DEPENDENCY_TIMEOUT) is False


def test_condition_e_none_report_is_false() -> None:
    """(e) a None report → False (R2: NOT weakened to 'report exists OR evidence sufficient')."""
    assert condition_e({"report": None}, DEPENDENCY_TIMEOUT) is False
    assert condition_e({}, DEPENDENCY_TIMEOUT) is False  # no report key at all


def test_condition_e_empty_root_cause_is_false() -> None:
    """(e) a report with NO grounded root_cause → False (the agent made no cited claim — R2)."""
    report: dict[str, object] = {"root_cause": [], "evidence_backing": []}
    assert condition_e({"report": report}, DEPENDENCY_TIMEOUT) is False


def test_condition_e_grounded_report_covering_sources_is_true() -> None:
    """(e) a grounded report (≥1 root_cause) whose cited evidence covers the expected sources → True.

    Proves the condition is FORWARD-CORRECT (will fire once the graph converges), NOT weakened.
    """
    report = {
        "root_cause": [{"rank": 1, "hypothesis_id": "H01", "citations": []}],
        "evidence_backing": [
            {"source_type": "prometheus"},
            {"source_type": "loki"},
        ],
    }
    assert condition_e({"report": report}, DEPENDENCY_TIMEOUT) is True


def test_condition_e_grounded_report_missing_a_source_is_false() -> None:
    """(e) a grounded report whose cited evidence does NOT cover an expected source → False.

    Proves (e) is NOT weakened to 'a report exists' — the cited evidence must point at the fault's sources.
    """
    report = {
        "root_cause": [{"rank": 1, "hypothesis_id": "H01", "citations": []}],
        "evidence_backing": [{"source_type": "prometheus"}],  # missing loki
    }
    assert condition_e({"report": report}, DEPENDENCY_TIMEOUT) is False


# ---------------------------------------------------------------------------
# The SM-2 MECHANISM — calibration_summary is a pure function (AD-7 read; D4 no-cutoff). Verified on
# synthetic well/over/under-calibrated pairs (the mechanism is the deliverable; the real-graph application
# is honestly blocked above).
# ---------------------------------------------------------------------------


def test_calibration_summary_empty_pairs_is_blocked() -> None:
    """0 pairs → honestly 'blocked' (no fabricated mean/gap/status)."""
    summary = calibration_summary([])
    assert summary["n_pairs"] == 0
    assert summary["status"] == "blocked-no-report-level-confidence"
    assert summary["gap"] is None


def test_calibration_summary_well_calibrated_has_near_zero_gap() -> None:
    """assigned confidence ≈ actual correctness rate → gap ≈ 0 (well-calibrated)."""
    # assigned [0.9, 0.1], actual [True, False] → mean_assigned 0.5 == mean_actual 0.5 → gap 0.0.
    summary = calibration_summary([(0.9, True), (0.1, False)])
    assert summary["n_pairs"] == 2
    assert summary["mean_assigned"] == pytest.approx(0.5)
    assert summary["mean_actual"] == pytest.approx(0.5)
    assert summary["gap"] == pytest.approx(0.0)
    assert summary["status"] == "ok"


def test_calibration_summary_over_confident_has_positive_gap() -> None:
    """assigned confidence > actual correctness rate → gap > 0 (over-confident)."""
    # assigned [0.9, 0.9], actual [True, False] → mean_assigned 0.9 > mean_actual 0.5 → gap 0.4.
    summary = calibration_summary([(0.9, True), (0.9, False)])
    gap = summary["gap"]
    assert isinstance(gap, float)
    assert gap == pytest.approx(0.4)
    assert gap > 0


def test_calibration_summary_under_confident_has_negative_gap() -> None:
    """assigned confidence < actual correctness rate → gap < 0 (under-confident)."""
    # assigned [0.1, 0.1], actual [True, False] → mean_assigned 0.1 < mean_actual 0.5 → gap -0.4.
    summary = calibration_summary([(0.1, True), (0.1, False)])
    gap = summary["gap"]
    assert isinstance(gap, float)
    assert gap == pytest.approx(-0.4)
    assert gap < 0


# ---------------------------------------------------------------------------
# Determinism prerequisite + blob shape (the decisive cross-PYTHONHASHSEED proof is gate #6).
# ---------------------------------------------------------------------------


def test_conjunction_blob_is_valid_json_with_eleven_scenarios_and_full_spine() -> None:
    """The blob is canonical JSON: sm1 + sm2 + 11 per-scenario rows, each carrying the FULL terminal spine.

    The terminal_state (the §2F payload) carries all 13 AD-9 spine keys per scenario — so gate#6 asserting
    byte-stability genuinely covers the FULL compiled-graph output, not a projection.
    """
    blob = json.loads(conjunction_blob())
    assert set(blob.keys()) >= {"max_iterations", "sm1", "sm2", "per_scenario"}
    assert len(blob["per_scenario"]) == 11
    for row in blob["per_scenario"]:
        assert set(row.keys()) >= {
            "name",
            "status",
            "conditions",
            "pass",
            "ceiling_confidence",
            "terminal_state",
        }
        assert set(row["terminal_state"].keys()) == _SPINE_KEYS, (
            f"terminal_state for {row['name']!r} must carry the full 13-key spine (the §2F payload)"
        )


def test_conjunction_blob_is_within_process_deterministic() -> None:
    """Determinism prerequisite: same scenarios → byte-identical conjunction blob across repeated runs.

    The decisive cross-``PYTHONHASHSEED`` proof is gate #6; this asserts the in-process prerequisite (the
    blob is a pure function of the scenarios — AD-12).
    """
    blobs = [conjunction_blob() for _ in range(3)]
    assert len(set(blobs)) == 1, (
        "the conjunction blob is non-deterministic in-process (AD-12 violation)"
    )
