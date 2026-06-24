"""Story 6.3 — the GRADED SCORING LAYER ABOVE the 6.2 binary conjunction (partial-credit + tolerance + SM-3).

Covers the Story-6.3 DEEP spotlights:

  - **the HONEST BASELINE is PRESERVED (R1)** — driving the FULL compiled §3.5 graph (reused from 6.2) over all
    11 yields the 5-A1 non-convergence baseline: ``report=None`` for all 11 → graded
    ``coverage = {a≈1.0, b=1.0, c=0.0, d=0.0, e=0.0}`` (the binary ``SM-1 = 0%`` headline is UNCHANGED — the
    graded layer is a SEPARATE supplementary axis, R2). SM-3 evidence-layer = **100%** (the rule-based normalizer
    derives each summary from its raw → every pipeline summary is grounded); SM-3 report-layer = ``blocked``
    (no report pre-convergence). The graded gap QUANTIFIES the 5-A1 deficit; it does NOT close it (R1).
  - **the INSTRUMENT is SOUND (not weakened — R2/R3)** — partial-credit ``coverage_{c,d,e}`` + SM-3 groundedness
    + tolerance window are verified on CONTROLLED synthetic states/summaries/reports, so a reader trusts the
    axes WILL correctly fire once the graph converges. The graded coverage is CONSISTENT with the binary
    conditions (``coverage == 1.0`` ⟺ binary ``True``) — no divergence from 6.2.
  - **the TOLERANCE window has teeth but is bounded (R2)** — ``within_tolerance`` catches the metric jitter
    exact-match misses AND a deterministic scenario is ``"not-applicable"`` (the window NEVER waves a
    deterministic failure — it applies ONLY to ``non_deterministic_extension`` scenarios at the metric level).
  - **the SM-3 anti-hallucination has teeth (R3)** — a synthetic HALLUCINATED summary (a fabricated RESULT not
    in raw/query/scaffold) → ungrounded; a citation with a null ``raw_excerpt`` → flagged. A SM-3 that cannot
    flag a synthetic hallucination is a tautological defect.
  - **the determinism prerequisite** — the scoring blob is byte-stable across repeated in-process runs (the
    decisive cross-``PYTHONHASHSEED`` proof is gate #6, ``tests/ci/test_gate6_scoring_determinism.py``).

The scoring evaluator itself lives in :mod:`tests.scoring_harness` (NOT collected by pytest — the ``test_``
prefix is HERE). This test imports it + asserts its honest output + its mechanism soundness.
"""

from __future__ import annotations

import json

import pytest

from eval import BENCHMARK_SCENARIOS
from eval.scenarios import DEPENDENCY_TIMEOUT, LATENCY_SPIKE, MEMORY_LEAK
from eval.schema import Scenario
from tests.conjunction_harness import condition_c, condition_d, condition_e
from tests.eval_harness import drive_evidence
from tests.scoring_harness import (
    _coverage_fraction,
    coverage_b,
    coverage_c,
    coverage_d,
    coverage_e,
    evaluate_scenario_graded,
    is_summary_grounded,
    scoring_blob,
    scoring_overview,
    sm3_evidence_layer,
    sm3_report_layer,
    tolerance_axis,
    within_tolerance,
)

# ---------------------------------------------------------------------------
# The HONEST BASELINE — graded coverage + SM-3 + tolerance over all 11 (5-A1 non-convergence, R1).
#
# The 6.2 binary baseline (SM-1 = 0%, conditions {a:True,b:True,c:False,d:False,e:False}) is PRESERVED
# unchanged (R1). The graded layer reports the SAME gap as fractions + adds the SM-3/tolerance axes — it does
# NOT close the gap (no convergence content added).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("scenario", BENCHMARK_SCENARIOS, ids=lambda s: s.name)
def test_baseline_coverage_is_the_locked_honest_baseline(scenario: Scenario) -> None:
    """Graded ``coverage = {a=1.0, b=1.0, c=0.0, d=0.0, e=0.0}`` for every scenario (5-A1 — R1: NOT fixed).

    The binary conditions are carried VERBATIM (``binary_conditions`` / ``binary_pass``) → the 6.2 SM-1 headline
    is unchanged. The graded floats quantify the SAME gap: (a)/(b) fully covered (pipeline + routing sound),
    (c)/(d)/(e) at 0.0 (the agent never reaches EXR→ENV→WRT — 5-A1). Partial-credit is a SEPARATE supplementary
    axis (R2) — it is NEVER reported as a pass.
    """
    graded = evaluate_scenario_graded(scenario)
    coverage = graded["coverage"]
    assert isinstance(coverage, dict), f"{scenario.name}: coverage must be a dict"
    assert coverage["a"] == pytest.approx(1.0), (
        f"{scenario.name}: coverage(a) must be 1.0 (inject→Evidence pipeline sound — 6.1)"
    )
    assert coverage["b"] == pytest.approx(1.0), (
        f"{scenario.name}: coverage(b) must be 1.0 (correct incident routing)"
    )
    assert coverage["c"] == pytest.approx(0.0), (
        f"{scenario.name}: coverage(c) must be 0.0 — EXR never runs (5-A1; honest baseline)"
    )
    assert coverage["d"] == pytest.approx(0.0), (
        f"{scenario.name}: coverage(d) must be 0.0 — ENV never runs (5-A1; honest baseline)"
    )
    assert coverage["e"] == pytest.approx(0.0), (
        f"{scenario.name}: coverage(e) must be 0.0 — report is None (5-A1; honest baseline)"
    )
    # The 6.2 binary SM-1 headline is PRESERVED (R1) — graded layer carries it verbatim, never overwrites it.
    binary = graded["binary_conditions"]
    assert binary == {"a": True, "b": True, "c": False, "d": False, "e": False}, (
        f"{scenario.name}: binary conditions must be unchanged from 6.2 (SM-1 headline preserved — R1)"
    )
    assert graded["binary_pass"] is False


@pytest.mark.parametrize("scenario", BENCHMARK_SCENARIOS, ids=lambda s: s.name)
def test_baseline_sm3_evidence_layer_is_100_percent(scenario: Scenario) -> None:
    """SM-3 evidence-layer = 100% for every scenario (the rule-based normalizer derives each summary from raw).

    The pipeline Evidence (via ``drive_evidence`` — 6.1; NOT synthesized — R3) has each ``summary`` grounded in
    its ``raw_excerpt`` (the adapter echoes ``source_type`` + ``query`` into raw; the summarizer's format
    scaffold + echoed query are admitted as legitimate). The baseline is ≈100% — the deliverable, NOT a defect.
    """
    sm3 = sm3_evidence_layer(scenario)
    assert sm3["status"] == "ok", f"{scenario.name}: SM-3 evidence-layer must run (not blocked)"
    assert sm3["sm3"] == pytest.approx(1.0), (
        f"{scenario.name}: SM-3 evidence-layer must be 100% (every pipeline summary grounded in its raw)"
    )
    assert sm3["n"] == sm3["grounded"]


@pytest.mark.parametrize("scenario", BENCHMARK_SCENARIOS, ids=lambda s: s.name)
def test_baseline_sm3_report_layer_is_blocked(scenario: Scenario) -> None:
    """SM-3 report-layer = ``"blocked-no-report"`` for every scenario (no report pre-convergence — 5-A1/R1).

    No fabrication (R3): there is no report → no citations to check → honestly blocked. Not a defect; not fixed.
    """
    graded = evaluate_scenario_graded(scenario)
    sm3 = graded["sm3_report"]
    assert isinstance(sm3, dict), f"{scenario.name}: sm3_report must be a dict"
    assert sm3["status"] == "blocked-no-report", (
        f"{scenario.name}: SM-3 report-layer must be blocked (no report pre-convergence — 5-A1)"
    )
    assert sm3["sm3"] is None  # honest: nothing to compute (no fabricated verdict)


@pytest.mark.parametrize("scenario", BENCHMARK_SCENARIOS, ids=lambda s: s.name)
def test_baseline_tolerance_axis(scenario: Scenario) -> None:
    """The tolerance window applies ONLY to ``non_deterministic_extension`` scenarios (R2 bounded).

    ``latency_spike``/``memory_leak`` → ``"satisfied"`` (the 6.1 canned inject is deterministic → produced ==
    expected). Every other scenario → ``"not-applicable"`` (the window NEVER waves a deterministic failure — R2).
    """
    graded = evaluate_scenario_graded(scenario)
    tolerance = graded["tolerance"]
    assert isinstance(tolerance, dict), f"{scenario.name}: tolerance must be a dict"
    extension = scenario.non_deterministic_extension
    if extension is None:
        assert tolerance["applicable"] is False, (
            f"{scenario.name}: tolerance must be not-applicable (deterministic scenario — R2)"
        )
        assert tolerance["status"] == "not-applicable"
    else:
        assert tolerance["applicable"] is True, (
            f"{scenario.name}: tolerance must apply to {extension!r} (marked non_deterministic_extension)"
        )
        assert tolerance["status"] == "satisfied", (
            f"{scenario.name}: tolerance must be satisfied (deterministic canned inject)"
        )
        assert tolerance["within"] is True
        assert (
            tolerance["expected"] == tolerance["produced"]
        )  # 6.1 deterministic → produced == expected


def test_overview_is_the_locked_honest_baseline() -> None:
    """The graded overview: coverage means {a≈1, b≈1, c=0, d=0, e=0}, SM-3 evidence mean 1.0, report blocked.

    Carries-forward the §2F honest baseline at the aggregate level. ``sm3_report_statuses`` =
    ``{blocked-no-report: 11}`` (all 11 blocked — no report pre-convergence).
    """
    per_scenario = [evaluate_scenario_graded(s) for s in BENCHMARK_SCENARIOS]
    overview = scoring_overview(per_scenario)
    assert overview["n"] == 11
    assert overview["coverage_means"] == pytest.approx(
        {"a": 1.0, "b": 1.0, "c": 0.0, "d": 0.0, "e": 0.0}
    )
    assert overview["sm3_evidence_mean"] == pytest.approx(1.0)
    assert overview["sm3_report_statuses"] == {"blocked-no-report": 11}


# ---------------------------------------------------------------------------
# The TOLERANCE window mechanism — teeth (catches jitter exact-match misses) + bounded (R2).
# ---------------------------------------------------------------------------


def test_within_tolerance_catches_jitter_that_exact_match_misses() -> None:
    """``within_tolerance`` admits metric jitter that ``==`` would reject — the A4 window's PURPOSE.

    A latency that jittered 2.8 → 2.94 is NOT an exact match (2.94 == 2.8 is False) but IS within a ±0.2 window.
    Out-of-window jitter (2.8 → 3.5) is rejected. Pure numeric (AD-12).
    """
    assert within_tolerance(2.8, 2.8, tol=0.05) is True  # exact → within
    # the teeth: exact-match rejects the jitter, but the window admits it.
    assert not (2.94 == 2.8)  # exact-match rejects the jitter
    assert within_tolerance(2.94, 2.8, tol=0.2) is True  # the window admits it
    assert within_tolerance(3.5, 2.8, tol=0.2) is False  # out-of-window jitter rejected


def test_within_tolerance_boundary_is_inclusive() -> None:
    """``|produced - expected| == tol`` is the inclusive boundary (within)."""
    # Exact integer-floats avoid binary-float imprecision (e.g. 2.85 - 2.8 == 0.05000000000000026 > 0.05).
    assert within_tolerance(5.0, 3.0, tol=2.0) is True  # diff 2.0 == tol → inclusive boundary
    assert within_tolerance(6.0, 3.0, tol=2.0) is False  # diff 3.0 > tol → out


def test_tolerance_axis_never_applies_to_a_deterministic_scenario() -> None:
    """R2: a deterministic scenario (``non_deterministic_extension is None``) → ``"not-applicable"``.

    The tolerance window is NOT a back-door pass: a deterministic failure is NEVER waved by the window.
    """
    assert tolerance_axis(DEPENDENCY_TIMEOUT)["status"] == "not-applicable"
    assert tolerance_axis(DEPENDENCY_TIMEOUT)["applicable"] is False


def test_tolerance_axis_satisfied_for_the_marked_scenarios() -> None:
    """The window is WIRED for the 2 ``non_deterministic_extension`` scenarios + satisfied on the baseline.

    The 6.1 canned inject is deterministic → ``produced == expected`` → within tolerance (the window is wired +
    teeth-proven, but non-discriminating on the deterministic baseline — R2).
    """
    latency = tolerance_axis(LATENCY_SPIKE)
    assert latency["applicable"] is True
    assert latency["extension"] == "latency_spike"
    assert latency["expected"] == pytest.approx(2.8)
    assert latency["status"] == "satisfied"

    memory = tolerance_axis(MEMORY_LEAK)
    assert memory["applicable"] is True
    assert memory["extension"] == "memory_leak"
    assert memory["expected"] == pytest.approx(0.94)
    assert memory["status"] == "satisfied"


# ---------------------------------------------------------------------------
# The SM-3 anti-hallucination MECHANISM — teeth on CONTROLLED synthetic summaries/citations (R3).
#
# The evidence-layer baseline (100%, above) proves real summaries are grounded. These tests prove SM-3 has
# TEETH: a synthetic HALLUCINATED summary / a citation with a null excerpt → flagged (else tautological — R3).
# ---------------------------------------------------------------------------


_CLEAN_RAW = (
    '{"query": "container_memory_working_set_bytes", '
    '"result": [{"metric": {"__name__": "container_memory_working_set_bytes"}, '
    '"value": [1719216000.0, "0.94"]}], "source_type": "prometheus"}'
)
_FAITHFUL_QUERY = "container_memory_working_set_bytes"


def test_is_summary_grounded_flags_a_synthetic_hallucination() -> None:
    """R3 teeth: a HALLUCINATED summary (a fabricated RESULT not in raw/query/scaffold) → ungrounded.

    The raw is a clean memory metric; the summary fabricates ``OOMKilled`` / ``heap exhaustion`` /
    ``thread deadlock`` — none in raw/query/scaffold → ungrounded. A SM-3 that passed this would be tautological.
    """
    hallucinated = (
        "prometheus evidence: 1 record(s) OOMKilled due to heap exhaustion and thread deadlock"
    )
    assert is_summary_grounded(hallucinated, _CLEAN_RAW, query=_FAITHFUL_QUERY) is False, (
        "a hallucinated result not in raw/query/scaffold MUST be flagged (R3 teeth)"
    )


def test_is_summary_grounded_passes_a_faithful_summary() -> None:
    """A faithful summary (the deterministic summarizer's actual output) → grounded (control)."""
    faithful = "prometheus evidence: 1 record(s) (query=container_memory_working_set_bytes)"
    assert is_summary_grounded(faithful, _CLEAN_RAW, query=_FAITHFUL_QUERY) is True


def test_is_summary_grounded_rejects_unextractable_excerpt() -> None:
    """A citation whose ``raw_excerpt`` is not an extractable non-empty string → ungrounded (hallucination)."""
    assert is_summary_grounded("anything", None, query="q") is False
    assert is_summary_grounded("anything", "", query="q") is False
    assert is_summary_grounded("anything", "   ", query="q") is False
    assert is_summary_grounded("anything", 42, query="q") is False  # non-str → not extractable


def test_is_summary_grounded_vacuous_when_summary_asserts_nothing() -> None:
    """A summary with no content-word token (e.g. just a digit) asserts nothing factual → vacuously grounded."""
    assert is_summary_grounded("42", _CLEAN_RAW, query=_FAITHFUL_QUERY) is True


def test_sm3_evidence_layer_reads_the_real_pipeline_not_synthesized_input() -> None:
    """R3: SM-3 evidence-layer operates on the REAL ``drive_evidence`` pipeline Evidence (same count).

    ``sm3_evidence_layer(scenario).n`` equals ``len(drive_evidence(scenario))`` → SM-3 reads the SAME real
    pipeline evidence 6.1 produces (NOT a synthesized input). A SM-3 on synthesized input would be a bypass.
    """
    sm3 = sm3_evidence_layer(MEMORY_LEAK)  # 3-evidence scenario (prometheus + k8s + loki)
    assert sm3["n"] == len(drive_evidence(MEMORY_LEAK))


def test_sm3_report_layer_flags_a_synthetic_null_excerpt_citation() -> None:
    """R3 teeth (report-layer): a citation with a null ``raw_excerpt`` → that citation is flagged → SM-3 < 100%.

    A synthetic report with 1 grounded citation (non-null excerpt) + 1 ungrounded (null excerpt) → SM-3 = 0.5.
    A SM-3 that passed a null-excerpt citation would be tautological.
    """
    report = {
        "root_cause": [
            {
                "rank": 1,
                "hypothesis_id": "H01",
                "citations": [
                    {
                        "raw_excerpt": "prometheus evidence: 1 record(s)",
                        "source_name": "order-service",
                        "source_type": "prometheus",
                    },
                    {
                        "raw_excerpt": None,  # ungrounded citation (no extractable excerpt)
                        "source_name": "order-service",
                        "source_type": "loki",
                    },
                ],
            }
        ],
        "evidence_backing": [],
    }
    sm3 = sm3_report_layer(report)
    assert sm3["status"] == "ok"
    assert sm3["n"] == 2
    assert sm3["grounded"] == 1
    assert sm3["sm3"] == pytest.approx(0.5)


def test_sm3_report_layer_blocked_when_no_report_or_no_citations() -> None:
    """Pre-convergence honesty: a ``None`` report → ``blocked-no-report``; an empty/uncited report → blocked.

    A ``None``/non-Mapping report → ``blocked-no-report``. A Mapping that is not a real report (empty, or with
    no ``root_cause`` citations) → ``blocked-no-citations``. No fabricated verdict in either case.
    """
    assert sm3_report_layer(None)["status"] == "blocked-no-report"
    assert sm3_report_layer({})["status"] == "blocked-no-citations"  # Mapping, no root_cause
    assert (
        sm3_report_layer({"root_cause": [], "evidence_backing": []})["status"]
        == "blocked-no-citations"
    )


# ---------------------------------------------------------------------------
# The PARTIAL-CREDIT MECHANISM — graded coverage on CONTROLLED synthetic states (R2 — non-weakened).
#
# The honest baseline shows coverage_{c,d,e}=0 because the graph does not converge. These verify the graded
# coverage FUNCTIONS are correct + NON-WEAKENED on controlled states where the agent DID execute (synthetic).
# ---------------------------------------------------------------------------


def test_coverage_b_is_graded_equality() -> None:
    """coverage(b): ``context.service == scenario.service`` → 1.0; otherwise 0.0 (the binary equality, graded)."""
    assert coverage_b("order-service", DEPENDENCY_TIMEOUT) == 1.0
    assert coverage_b("payment-service", DEPENDENCY_TIMEOUT) == 0.0
    assert coverage_b(None, DEPENDENCY_TIMEOUT) == 0.0


def test_coverage_c_is_the_graded_fraction() -> None:
    """coverage(c): fraction of expected adapter_methods the agent's ``tool_calls`` cover.

    DEPENDENCY_TIMEOUT expects ``{query_promql, query_loki}``. Covering one → 0.5; both → 1.0; none → 0.0.
    """
    state_half = {"tool_calls": [{"tool": "query_promql"}]}
    assert coverage_c(state_half, DEPENDENCY_TIMEOUT) == pytest.approx(0.5)
    state_full = {"tool_calls": [{"tool": m} for m in ("query_promql", "query_loki")]}
    assert coverage_c(state_full, DEPENDENCY_TIMEOUT) == pytest.approx(1.0)
    assert coverage_c({"tool_calls": []}, DEPENDENCY_TIMEOUT) == pytest.approx(0.0)


def test_coverage_d_is_the_graded_fraction() -> None:
    """coverage(d): fraction of expected source_types the agent's gathered ``evidence`` covers."""
    state_half = {"evidence": [{"source_type": "prometheus"}]}
    assert coverage_d(state_half, DEPENDENCY_TIMEOUT) == pytest.approx(0.5)
    state_full = {"evidence": [{"source_type": "prometheus"}, {"source_type": "loki"}]}
    assert coverage_d(state_full, DEPENDENCY_TIMEOUT) == pytest.approx(1.0)
    assert coverage_d({"evidence": []}, DEPENDENCY_TIMEOUT) == pytest.approx(0.0)


def test_coverage_e_none_report_is_zero() -> None:
    """coverage(e): a None/absent report → 0.0 (R2 — NOT weakened to 'report exists OR evidence sufficient')."""
    assert coverage_e({"report": None}, DEPENDENCY_TIMEOUT) == 0.0
    assert coverage_e({}, DEPENDENCY_TIMEOUT) == 0.0


def test_coverage_e_empty_root_cause_is_zero() -> None:
    """coverage(e): a report with NO grounded root_cause → 0.0 (the report made no cited claim — R2)."""
    report: dict[str, object] = {"root_cause": [], "evidence_backing": []}
    assert coverage_e({"report": report}, DEPENDENCY_TIMEOUT) == 0.0


def test_coverage_e_grounded_report_covering_sources_is_full() -> None:
    """coverage(e): a grounded report whose cited evidence covers ALL expected → 1.0 (forward-correct, R2)."""
    report = {
        "root_cause": [{"rank": 1, "hypothesis_id": "H01", "citations": []}],
        "evidence_backing": [{"source_type": "prometheus"}, {"source_type": "loki"}],
    }
    assert coverage_e({"report": report}, DEPENDENCY_TIMEOUT) == pytest.approx(1.0)


def test_coverage_e_grounded_report_missing_a_source_is_partial() -> None:
    """coverage(e): a grounded report covering HALF the expected → 0.5 (graded, NOT all-or-nothing)."""
    report = {
        "root_cause": [{"rank": 1, "hypothesis_id": "H01", "citations": []}],
        "evidence_backing": [{"source_type": "prometheus"}],  # missing loki
    }
    assert coverage_e({"report": report}, DEPENDENCY_TIMEOUT) == pytest.approx(0.5)


def test_coverage_fraction_vacuous_when_no_expected() -> None:
    """``_coverage_fraction(0, 0) == 1.0`` — vacuous truth (mirrors ``all([]) == True``); never ZeroDivision."""
    assert _coverage_fraction(0, 0) == 1.0
    assert _coverage_fraction(3, 4) == pytest.approx(0.75)


@pytest.mark.parametrize(
    ("state", "label"),
    [
        ({"tool_calls": []}, "empty"),
        ({"tool_calls": [{"tool": "query_promql"}]}, "half"),
        ({"tool_calls": [{"tool": "query_promql"}, {"tool": "query_loki"}]}, "full"),
    ],
)
def test_coverage_c_consistent_with_binary_condition_c(
    state: dict[str, object], label: str
) -> None:
    """The graded layer is CONSISTENT with the 6.2 binary: ``coverage_c == 1.0`` ⟺ ``condition_c == True``.

    (§6 carry-forward): the graded coverage reads the SAME ``called`` set (via the shared ``_list_of_dicts``
    narrowing) as the binary condition → no divergence. Partial-credit 1.0 is exactly the binary pass.
    """
    graded = coverage_c(state, DEPENDENCY_TIMEOUT)
    binary = condition_c(state, DEPENDENCY_TIMEOUT)
    assert (graded == pytest.approx(1.0)) == binary, (
        f"graded coverage_c must equal 1.0 iff binary condition_c is True (label={label})"
    )


@pytest.mark.parametrize(
    ("state", "label"),
    [
        ({"evidence": []}, "empty"),
        ({"evidence": [{"source_type": "prometheus"}]}, "half"),
        ({"evidence": [{"source_type": "prometheus"}, {"source_type": "loki"}]}, "full"),
    ],
)
def test_coverage_d_consistent_with_binary_condition_d(
    state: dict[str, object], label: str
) -> None:
    """The graded layer is CONSISTENT with 6.2: ``coverage_d == 1.0`` ⟺ ``condition_d == True``."""
    graded = coverage_d(state, DEPENDENCY_TIMEOUT)
    binary = condition_d(state, DEPENDENCY_TIMEOUT)
    assert (graded == pytest.approx(1.0)) == binary, (
        f"graded coverage_d must equal 1.0 iff binary condition_d is True (label={label})"
    )


@pytest.mark.parametrize(
    ("report", "label"),
    [
        (None, "no-report"),
        ({"root_cause": [], "evidence_backing": []}, "empty-root-cause"),
        (
            {
                "root_cause": [{"rank": 1, "hypothesis_id": "H01", "citations": []}],
                "evidence_backing": [{"source_type": "prometheus"}],
            },
            "partial",
        ),
        (
            {
                "root_cause": [{"rank": 1, "hypothesis_id": "H01", "citations": []}],
                "evidence_backing": [{"source_type": "prometheus"}, {"source_type": "loki"}],
            },
            "full",
        ),
    ],
)
def test_coverage_e_consistent_with_binary_condition_e(report: object, label: str) -> None:
    """The graded layer is CONSISTENT with 6.2: ``coverage_e == 1.0`` ⟺ ``condition_e == True``."""
    state = {"report": report}
    graded = coverage_e(state, DEPENDENCY_TIMEOUT)
    binary = condition_e(state, DEPENDENCY_TIMEOUT)
    assert (graded == pytest.approx(1.0)) == binary, (
        f"graded coverage_e must equal 1.0 iff binary condition_e is True (label={label})"
    )


# ---------------------------------------------------------------------------
# Determinism prerequisite + blob shape (the decisive cross-PYTHONHASHSEED proof is gate #6).
# ---------------------------------------------------------------------------


def test_scoring_blob_is_valid_json_with_eleven_rows_and_overview() -> None:
    """The blob is canonical JSON: ``overview`` + 11 per-scenario rows, each carrying the graded axes."""
    blob = json.loads(scoring_blob())
    assert set(blob.keys()) >= {"max_iterations", "overview", "per_scenario"}
    assert len(blob["per_scenario"]) == 11
    for row in blob["per_scenario"]:
        assert set(row.keys()) >= {
            "name",
            "binary_conditions",
            "binary_pass",
            "coverage",
            "sm3_evidence",
            "sm3_report",
            "tolerance",
        }
        assert set(row["coverage"].keys()) == {"a", "b", "c", "d", "e"}
    overview = blob["overview"]
    assert overview["n"] == 11
    assert overview["sm3_report_statuses"] == {"blocked-no-report": 11}


def test_scoring_blob_is_within_process_deterministic() -> None:
    """Determinism prerequisite: same scenarios → byte-identical scoring blob across repeated runs (AD-12).

    The decisive cross-``PYTHONHASHSEED`` proof is gate #6; this asserts the in-process prerequisite (the blob
    is a pure function of the scenarios — coverage = membership fractions, SM-3 = token membership, tolerance =
    ``abs()``; no hash-ordered structure leaks into the canonical-JSON blob).
    """
    blobs = [scoring_blob() for _ in range(3)]
    assert len(set(blobs)) == 1, (
        "the scoring blob is non-deterministic in-process (AD-12 violation)"
    )
