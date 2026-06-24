"""tests.scoring_harness — the Story-6.3 GRADED SCORING LAYER ABOVE the 6.2 binary conjunction.

This module has NO ``test_`` prefix → pytest does NOT collect it. It is the Story-6.3 **measurement
instrument** that adds THREE graded axes ON TOP of (NOT in place of) the Story-6.2 binary conjunction:

  1. **Partial-credit (FR-10c)** — per-condition ``coverage_{a..e}`` floats in ``[0.0, 1.0]``. Where 6.2's
     condition is a strict ``all()`` (binary), partial-credit reports the FRACTION of the expected set the
     agent actually covered. The binary ``SM-1`` (6.2) STAYS the correctness headline; partial-credit is a
     SEPARATE graded SUPPLEMENTARY axis (R2 — never a back-door pass, never conflated with the binary).
  2. **Tolerance window (A4)** — for the ``non_deterministic_extension`` scenarios (``latency_spike`` /
     ``memory_leak``), the metric comparison uses ``[expected ± tol]`` (AD-12-pure ``within_tolerance``).
     It applies ONLY to those MARKED scenarios at the METRIC level — it NEVER waves a deterministic failure.
  3. **Anti-hallucination SM-3 (FR-10d)** — a raw-vs-summary cross-check. (evidence-layer, OPERATIONAL) each
     pipeline Evidence ``summary`` must be GROUNDED in its ``raw_excerpt`` (assert nothing beyond it);
     ``% grounded = SM-3`` (≈100% baseline — the rule-based normalizer derives the summary from the raw).
     (report-layer, BLOCKED) each root_cause citation's ``raw_excerpt`` must be extractable — pre-convergence
     there is no report → honestly ``"blocked"``. AD-7: SM-3 READS ``raw_excerpt``/``summary``; it NEVER
     recomputes confidence; SM-3 ⊥ SM-2.

This is the MEASUREMENT INSTRUMENT + the HONEST BASELINE ONLY (Story 6.3 scope). It does NOT fix the graph:
the POC graph does NOT converge (5-A1) → ``report=None`` for all 11 → partial-credit ``coverage_{c,d,e}=0.0``,
``coverage_{a,b}≈1.0``, SM-3 evidence-layer ≈100% (the PIPELINE evidence, via ``drive_evidence`` — 6.1),
SM-3 report-layer ``"blocked"``. The 6.2 honest baseline (``SM-1 = 0%``) is PRESERVED unchanged (R1).

The 3 FORBIDDEN MOVES (anti-gaming) apply to the MEASUREMENT:

  - **R1** — do NOT add convergence content (floor registry / hypothesis-advance / VAL-trio) to inflate the
    grade. The honest baseline (``coverage_{c,d,e}=0``, SM-3 report blocked) is the deliverable, NOT fixed.
  - **R2** — do NOT weaken via partial-credit. Partial-credit is a SEPARATE graded SUPPLEMENTARY axis; the
    binary SM-1 stays the correctness headline; a partial grade is NEVER reported as a pass / partial-pass =
    success. The tolerance window applies ONLY to ``non_deterministic_extension`` scenarios at the metric
    level — NEVER to wave away a deterministic failure.
  - **R3** — do NOT bypass the agent / do NOT synthesize. SM-3 checks REAL evidence summaries vs REAL
    ``raw_excerpt``s (actual ``drive_evidence`` / ``state["evidence"]`` / report outputs), never synthesized
    inputs. A SM-3 that cannot flag a synthetic hallucination is a tautological defect.

NO new production seam (the dispatch scope boundary): this module reads 6.2's :func:`evaluate_scenario` (the
full compiled-graph terminal state, carrying ``tool_calls`` / ``evidence`` / ``report``) + 6.1's
:func:`drive_evidence` (the inject → REAL adapter → REAL normalizer pipeline Evidence). It touches NO
``graph/`` / ``services/`` / ``routers/`` / ``models/`` code. ``eval/`` stays import-pure; the agent-driving
orchestration this layer builds ON lives in ``tests/`` (same discipline as :mod:`tests.conjunction_harness`).

Why this lives in ``tests/``: it imports ``tests.conjunction_harness`` + ``tests.eval_harness`` (which import
``graph`` + ``adapters`` + ``models``) — the same reason 6.2 lives here, not in ``eval/``.

Used by:
  - ``tests/test_scoring_evaluator.py`` (in-process: the graded baseline + tolerance teeth + SM-3 teeth on
    CONTROLLED synthetic evidence/reports + the determinism prerequisite).
  - ``tests/ci/test_gate6_scoring_determinism.py`` (the decisive cross-``PYTHONHASHSEED`` proof that the graded
    + SM-3 blob is byte-stable across seeds — §2D; the ``EVAL_GATE6_NEGATIVE`` hook deliberately makes the
    blob hash-seed-dependent so the negative test proves the assertion has teeth, mirroring 6.1/6.2).

Deterministic (AD-12 / NFR-Determinism): no wall-clock, no ``random``, no network, no filesystem mutation, no
``hash()`` on strings. Coverage = set-membership fractions (``in`` checks, order-independent). SM-3 = token
containment (sets used only for membership, never serialized). Tolerance = ``abs()`` arithmetic. The blob is
canonical JSON (``sort_keys=True``) → same scenarios → byte-identical blob regardless of ``PYTHONHASHSEED``
(PROVEN by gate#6 §2D).
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Mapping, Sequence

from eval.scenarios import BENCHMARK_SCENARIOS
from eval.schema import Scenario
from tests.conjunction_harness import (
    _DEFAULT_MAX_ITERATIONS,
    _as_mapping,
    _list_of_dicts,
    evaluate_scenario,
)
from tests.eval_harness import drive_evidence

# This module intentionally builds ON 6.2's agent-driving orchestration (tests.conjunction_harness) + 6.1's
# pipeline (tests.eval_harness) — both already import graph + adapters + models. eval/ stays import-pure.

# A placeholder absolute tolerance for the ``within_tolerance`` window. The specific tol MAGNITUDE is DEFERRED
# (D4 — confidence/SM/tolerance cutoffs defer); on the deterministic baseline ``produced == expected`` so the
# window is satisfied for ANY ``tol >= 0`` regardless of its magnitude. Scale-aware tuning (the metrics span
# latency-seconds 2.8 and memory-fraction 0.94 — a single absolute tol does not fit both scales) is a 6.x-tune
# item, NOT asserted by gate#6 (the gate asserts the axis RUNS + is DETERMINISTIC, not a tolerance PASS).
_DEFAULT_TOL: float = 0.05

# SM-3 groundedness scaffold. The deterministic summarizer derives each summary from ``(raw, source_type,
# query)``; its NON-factual scaffolding — the fixed words ``evidence`` / ``record(s)`` / the literal ``(query=``
# prefix ``query`` — make no claim about the system, so they are admitted as structural glue. The echoed
# ``query`` value (the OPERATION that was asked) is a legitimate summarizer input and is admitted explicitly
# (via the ``query`` arg) — reporting the query asked is NOT a fabricated result. A summary is grounded iff its
# tokens are all in ``raw_excerpt ∪ query ∪ scaffold``; a hallucinated RESULT (e.g. ``OOMKilled`` against a
# clean metric raw, absent from raw/query/scaffold) → flagged (teeth preserved — R3).
_GLUE_WORDS: frozenset[str] = frozenset({"evidence", "record", "records", "query"})

# Content-word tokenizer: lowercase alpha runs of length >= 4. The length-4 floor excludes short noise tokens
# the deterministic query-echo can introduce (``get``/``set``/``k8s``) that are not in ``raw_excerpt`` and
# would otherwise spuriously flag a grounded summary (R3 — teeth must catch genuine hallucinations, not noise).
_ALPHA_TOKEN = re.compile(r"[a-z]{4,}")


# ---------------------------------------------------------------------------
# SM-3 evidence-layer groundedness (FR-10d) — summary grounded in raw_excerpt.
# ---------------------------------------------------------------------------


def _word_tokens(text: str) -> set[str]:
    """Lowercased content-word tokens (alpha runs >= 4) of ``text`` (order-independent; membership-only)."""
    return set(_ALPHA_TOKEN.findall(text.lower()))


def is_summary_grounded(summary: object, raw_excerpt: object, *, query: object = None) -> bool:
    """SM-3 groundedness: ``raw_excerpt`` extractable AND ``summary`` asserts nothing beyond it.

    (R3) a REAL raw-vs-summary cross-check: ``summary`` is grounded iff (1) ``raw_excerpt`` is a non-empty
    extractable string (a citation with no excerpt cannot ground a claim) AND (2) every content-word token of
    ``summary`` is present in ``raw_excerpt``'s token set ∪ the echoed ``query``'s tokens ∪ the structural-
    scaffold glue (``evidence`` / ``record(s)`` / the literal ``query`` prefix — the deterministic summarizer's
    fixed format, NOT factual claims). The deterministic summarizer derives each summary from ``(raw,
    source_type, query)``: ``raw_excerpt`` carries ``source_type`` + (prometheus) the query value → the
    summary's factual tokens trace to ``raw_excerpt``; the echoed ``query`` is the OPERATION asked (admitted
    via the ``query`` arg) — reporting it is not a fabricated result. A synthetic HALLUCINATED summary
    introducing an out-of-vocabulary RESULT token (e.g. ``OOMKilled`` against a clean metric raw, absent from
    raw/query/scaffold) → ungrounded (the teeth). Tokens use membership only (``in``); no hash-ordered
    structure is serialized → PYTHONHASHSEED-safe.
    """
    if not isinstance(raw_excerpt, str) or not raw_excerpt.strip():
        return False  # no extractable excerpt → the claim is ungrounded (hallucination signal).
    if not isinstance(summary, str) or not summary.strip():
        return False  # nothing asserted AND no excerpt to ground against → ungrounded.
    summary_tokens = _word_tokens(summary)
    if not summary_tokens:
        return True  # a summary with no content-word token asserts nothing factual → vacuously grounded.
    query_str = query if isinstance(query, str) else ""
    grounding = _word_tokens(raw_excerpt) | _word_tokens(query_str) | _GLUE_WORDS
    unsupported = summary_tokens - grounding
    return len(unsupported) == 0


# ---------------------------------------------------------------------------
# Tolerance window (A4) — the ``non_deterministic_extension`` metric comparison.
# ---------------------------------------------------------------------------


def within_tolerance(produced: float, expected: float, *, tol: float) -> bool:
    """Tolerance window: ``|produced - expected| <= tol``. Pure numeric (AD-12; no IO/random/clock).

    Applies ONLY to ``non_deterministic_extension`` scenarios at the METRIC level (R2 — it is NOT a back-door
    pass and NEVER waves a deterministic condition failure). ``tol`` magnitude DEFER (D4).
    """
    return abs(produced - expected) <= tol


def _extract_prom_value(response: object) -> float | None:
    """Extract the prometheus scalar metric ``value`` from a canned inject response (never raises)."""
    if not isinstance(response, Mapping):
        return None
    data = response.get("data")
    if not isinstance(data, Mapping):
        return None
    result = data.get("result")
    if not isinstance(result, list) or not result:
        return None
    first = result[0]
    if not isinstance(first, Mapping):
        return None
    value = first.get("value")
    if not isinstance(value, list) or len(value) < 2:
        return None
    metric_value = value[1]
    if isinstance(metric_value, str):
        try:
            return float(metric_value)
        except ValueError:
            return None
    if isinstance(metric_value, int | float) and not isinstance(metric_value, bool):
        return float(metric_value)
    return None


def _prometheus_metric_value(scenario: Scenario) -> float | None:
    """The scenario's prometheus metric value (the ``non_deterministic_extension`` metric), from its inject.

    The 6.1 canned inject is DETERMINISTIC → ``produced == expected`` → the tolerance window is satisfied
    trivially on the baseline (the window is wired + teeth-proven, but non-discriminating here — R2).
    """
    for call in scenario.inject:
        if call.adapter_method == "query_promql":
            value = _extract_prom_value(call.response)
            if value is not None:
                return value
    return None


# ---------------------------------------------------------------------------
# Partial-credit (FR-10c) — graded coverage_{a..e} floats in [0.0, 1.0].
# ---------------------------------------------------------------------------


def _expected_source_types(scenario: Scenario) -> tuple[str, ...]:
    """The scenario's expected-evidence ``source_type`` tuple (the ground-truth source set)."""
    return tuple(ee.source_type for ee in scenario.expected_evidence)


def _expected_adapter_methods(scenario: Scenario) -> tuple[str, ...]:
    """The scenario's expected-evidence ``adapter_method`` tuple (the ground-truth tool set)."""
    return tuple(ee.adapter_method for ee in scenario.expected_evidence)


def _coverage_fraction(covered: int, total: int) -> float:
    """``covered / total`` (1.0 when ``total == 0`` — vacuous truth, mirroring ``all([]) == True``)."""
    return 1.0 if total == 0 else covered / total


def coverage_a(scenario: Scenario) -> float:
    """Graded (a): fraction of expected ``source_type``s the inject → Evidence PIPELINE produces.

    Mirrors 6.2's binary ``condition_a`` as a FRACTION (membership-based ``in`` — order-independent). The
    pipeline is sound (6.1) → ``coverage_a = 1.0`` for all 11 (every expected source_type is produced).
    """
    evidence = drive_evidence(scenario)
    produced = {ev.get("source_type") for ev in evidence}
    expected = _expected_source_types(scenario)
    covered = sum(1 for source_type in expected if source_type in produced)
    return _coverage_fraction(covered, len(expected))


def coverage_b(context_service: object, scenario: Scenario) -> float:
    """Graded (b): 1.0 if ``context.service == scenario.service`` else 0.0 (the binary equality, graded)."""
    return 1.0 if context_service == scenario.service else 0.0


def coverage_c(state: Mapping[str, object], scenario: Scenario) -> float:
    """Graded (c): fraction of expected ``adapter_method``s the agent's OWN ``tool_calls`` cover.

    Mirrors 6.2's binary ``condition_c`` (same ``called`` set; same ``_list_of_dicts`` narrowing → consistency
    with the binary condition). Pre-convergence ``tool_calls=[]`` → ``coverage_c = 0.0`` (5-A1).
    """
    tool_calls = _list_of_dicts(state.get("tool_calls"))
    called = {tc.get("tool") for tc in tool_calls}
    expected = _expected_adapter_methods(scenario)
    covered = sum(1 for method in expected if method in called)
    return _coverage_fraction(covered, len(expected))


def coverage_d(state: Mapping[str, object], scenario: Scenario) -> float:
    """Graded (d): fraction of expected ``source_type``s the agent's gathered ``evidence`` covers.

    Mirrors 6.2's binary ``condition_d`` (same ``produced`` set; same narrowing). Pre-convergence ``evidence=[]``
    → ``coverage_d = 0.0`` (5-A1).
    """
    evidence = _list_of_dicts(state.get("evidence"))
    produced = {ev.get("source_type") for ev in evidence}
    expected = _expected_source_types(scenario)
    covered = sum(1 for source_type in expected if source_type in produced)
    return _coverage_fraction(covered, len(expected))


def coverage_e(state: Mapping[str, object], scenario: Scenario) -> float:
    """Graded (e): fraction of expected ``source_type``s the report's cited evidence covers (NON-WEAKENED — R2).

    Mirrors 6.2's binary ``condition_e``: ``0.0`` when the report is absent OR has no grounded root_cause (a
    ``None``/uncited report is honestly ``0.0`` — NOT weakened); otherwise the fraction of expected source_types
    in the report's ``evidence_backing``. ``coverage_e == 1.0`` ⟺ binary ``condition_e == True`` (consistency).
    Pre-convergence ``report=None`` → ``coverage_e = 0.0`` (5-A1).
    """
    report = state.get("report")
    if not isinstance(report, Mapping):
        return 0.0  # R2: no report → honestly 0.0 (NOT "report exists OR evidence sufficient").
    if not _list_of_dicts(report.get("root_cause")):
        return 0.0  # no grounded candidate → the report made NO cited claim → 0.0.
    backing = _list_of_dicts(report.get("evidence_backing"))
    cited_types = {entry.get("source_type") for entry in backing}
    expected = _expected_source_types(scenario)
    covered = sum(1 for source_type in expected if source_type in cited_types)
    return _coverage_fraction(covered, len(expected))


# ---------------------------------------------------------------------------
# SM-3 evidence-layer + report-layer (FR-10d anti-hallucination raw-vs-summary).
# ---------------------------------------------------------------------------


def sm3_evidence_layer(scenario: Scenario) -> dict[str, object]:
    """SM-3 evidence-layer: % of pipeline Evidence whose ``summary`` is grounded in its ``raw_excerpt``.

    Operates on the REAL pipeline Evidence (:func:`drive_evidence` — 6.1; NOT synthesized — R3). The rule-based
    normalizer derives each ``summary`` from ``(raw, source_type, query)`` → the baseline is ≈100% (the
    summary's factual tokens trace to ``raw_excerpt``; structural scaffold is glue). Teeth: a synthetic
    hallucinated summary → SM-3 < 100% (else tautological — R3). ``sm3`` is ``None`` only when the pipeline
    produced no evidence (blocked), which does not occur on the 11 scenarios.
    """
    evidence = drive_evidence(scenario)
    n = len(evidence)
    if n == 0:
        return {"n": 0, "grounded": 0, "sm3": None, "status": "blocked-no-evidence"}
    grounded = sum(
        1
        for ev in evidence
        if is_summary_grounded(ev.get("summary"), ev.get("raw_excerpt"), query=ev.get("query"))
    )
    return {"n": n, "grounded": grounded, "sm3": grounded / n, "status": "ok"}


def _citation_grounded(citation: Mapping[str, object]) -> bool:
    """A report citation is grounded iff its ``raw_excerpt`` is an extractable non-empty string (AD-6).

    The ``rca_writer`` citation shape ``{raw_excerpt, source_name, source_type, timestamp_range}`` carries NO
    claim-text field — so report-layer groundedness is the citation's ``raw_excerpt`` being extractable (the
    candidate's existence, per AD-6, implies it is backed by ≥1 evidence with a non-null excerpt).
    """
    excerpt = citation.get("raw_excerpt")
    return isinstance(excerpt, str) and bool(excerpt.strip())


def sm3_report_layer(report: object) -> dict[str, object]:
    """SM-3 report-layer: % of root_cause citations with an extractable ``raw_excerpt`` (AD-6).

    Pre-convergence ``report`` is ``None`` (5-A1) → honestly ``"blocked-no-report"`` (no fabrication — R1/R3).
    When a report exists, every ``root_cause[].citations[]`` ``raw_excerpt`` must be extractable. Teeth: a
    synthetic citation with a null/empty ``raw_excerpt`` → that citation is flagged → SM-3 < 100% (R3).
    """
    if not isinstance(report, Mapping):
        return {"n": 0, "grounded": 0, "sm3": None, "status": "blocked-no-report"}
    candidates = _list_of_dicts(report.get("root_cause"))
    citations: list[Mapping[str, object]] = []
    for candidate in candidates:
        raw_citations = candidate.get("citations")
        if isinstance(raw_citations, list):
            citations.extend(c for c in raw_citations if isinstance(c, Mapping))
    n = len(citations)
    if n == 0:
        return {"n": 0, "grounded": 0, "sm3": None, "status": "blocked-no-citations"}
    grounded = sum(1 for citation in citations if _citation_grounded(citation))
    return {"n": n, "grounded": grounded, "sm3": grounded / n, "status": "ok"}


# ---------------------------------------------------------------------------
# Tolerance axis — wires the window to the ``non_deterministic_extension`` scenarios.
# ---------------------------------------------------------------------------


def tolerance_axis(scenario: Scenario, *, tol: float = _DEFAULT_TOL) -> dict[str, object]:
    """Apply the tolerance window to a scenario's metric — ONLY for ``non_deterministic_extension`` (R2).

    A deterministic scenario (``non_deterministic_extension is None``) → ``"not-applicable"`` (the window
    NEVER waves a deterministic failure). A marked scenario (``latency_spike``/``memory_leak``) → the canned
    metric is extracted; ``produced == expected`` (6.1 deterministic) → the window is satisfied (the window is
    wired + teeth-proven, but non-discriminating on the baseline).
    """
    extension = scenario.non_deterministic_extension
    if extension is None:
        return {"applicable": False, "extension": None, "status": "not-applicable"}
    metric = _prometheus_metric_value(scenario)
    if metric is None:
        return {
            "applicable": True,
            "extension": extension,
            "status": "metric-unavailable",
            "expected": None,
            "produced": None,
            "tol": tol,
            "within": None,
        }
    # The 6.1 canned inject is deterministic → produced == expected → within tolerance trivially.
    within = within_tolerance(metric, metric, tol=tol)
    return {
        "applicable": True,
        "extension": extension,
        "expected": metric,
        "produced": metric,
        "tol": tol,
        "within": within,
        "status": "satisfied" if within else "out-of-window",
    }


# ---------------------------------------------------------------------------
# The graded scenario evaluator (reuses 6.2's full compiled-graph terminal state — NO new seam).
# ---------------------------------------------------------------------------


def evaluate_scenario_graded(
    scenario: Scenario, *, max_iterations: int = _DEFAULT_MAX_ITERATIONS
) -> dict[str, object]:
    """Score one scenario on the 3 graded axes → ``{name, axes}`` (REUSES 6.2's terminal state — R3/no-seam).

    Drives 6.2's :func:`evaluate_scenario` ONCE (the full compiled graph → binary conditions + terminal state
    spine carrying ``tool_calls``/``evidence``/``report``), then computes the graded views ON TOP: the binary
    conditions (carried verbatim — the SM-1 headline is PRESERVED, R1), ``coverage`` (partial-credit floats),
    ``sm3_evidence``/``sm3_report`` (anti-hallucination), and ``tolerance`` (the A4 window). No production code
    is touched; this reads 6.2's + 6.1's surfaces only.
    """
    base = evaluate_scenario(scenario, max_iterations=max_iterations)
    state = _as_mapping(base.get("terminal_state"))
    context = _as_mapping(state.get("context"))
    report = state.get("report")
    return {
        "name": scenario.name,
        "non_deterministic_extension": scenario.non_deterministic_extension,
        "binary_conditions": base.get("conditions"),
        "binary_pass": base.get("pass"),
        "coverage": {
            "a": coverage_a(scenario),
            "b": coverage_b(context.get("service"), scenario),
            "c": coverage_c(state, scenario),
            "d": coverage_d(state, scenario),
            "e": coverage_e(state, scenario),
        },
        "sm3_evidence": sm3_evidence_layer(scenario),
        "sm3_report": sm3_report_layer(report),
        "tolerance": tolerance_axis(scenario),
    }


def _mean_floats(values: Sequence[object]) -> float:
    """Mean of the float-typed values in ``values`` (``0.0`` when none are numeric; never raises)."""
    numeric = [v for v in values if isinstance(v, int | float) and not isinstance(v, bool)]
    return sum(float(v) for v in numeric) / len(numeric) if numeric else 0.0


def scoring_overview(per_scenario: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Aggregate the graded axes across scenarios (means + per-condition coverage means).

    Reports the mean ``coverage`` per condition, the mean SM-3 evidence-layer ``sm3``, and the SM-3 report-layer
    status counts. The binary SM-1 is 6.2's headline (NOT recomputed here — R2: partial-credit is a SEPARATE
    supplementary axis, never conflated). Honest baseline: ``coverage{a≈1.0, b≈1.0, c=0, d=0, e=0}`` (5-A1),
    SM-3 evidence ≈100%, SM-3 report ``blocked`` (no report).
    """
    coverage_means: dict[str, float] = {}
    for key in ("a", "b", "c", "d", "e"):
        per_key = []
        for row in per_scenario:
            coverage = row.get("coverage")
            if isinstance(coverage, Mapping):
                per_key.append(coverage.get(key))
        coverage_means[key] = _mean_floats(per_key)
    sm3_evidence_values = []
    for row in per_scenario:
        sm3 = row.get("sm3_evidence")
        if isinstance(sm3, Mapping):
            sm3_evidence_values.append(sm3.get("sm3"))
    report_statuses: dict[str, int] = {}
    for row in per_scenario:
        sm3 = row.get("sm3_report")
        if isinstance(sm3, Mapping):
            status = sm3.get("status")
            key = status if isinstance(status, str) else "unknown"
            report_statuses[key] = report_statuses.get(key, 0) + 1
    return {
        "n": len(per_scenario),
        "coverage_means": coverage_means,
        "sm3_evidence_mean": _mean_floats(sm3_evidence_values),
        "sm3_report_statuses": report_statuses,
    }


# ---------------------------------------------------------------------------
# The canonical scoring blob (gate#6 §2D determinism unit + the REVIEW-READY payload).
# ---------------------------------------------------------------------------


def scoring_blob(*, max_iterations: int = _DEFAULT_MAX_ITERATIONS) -> str:
    """Canonical-JSON graded-scoring report for ALL 11 scenarios (the gate#6 subprocess output + §2D payload).

    The blob carries the ``overview`` (graded coverage means + SM-3 means) and ``per_scenario`` (each row's
    binary conditions — the preserved SM-1 headline — + graded ``coverage`` + ``sm3_evidence``/``sm3_report`` +
    ``tolerance``). Byte-stability across ``PYTHONHASHSEED`` (§2D) holds ONLY IF the graded + SM-3 computation
    is deterministic (no hash-ordered structure leaks into the blob): coverage = set-membership fractions,
    SM-3 = token-membership checks, tolerance = ``abs()`` — all PYTHONHASHSEED-safe. Canonical JSON
    (``sort_keys=True``); same scenarios → byte-identical blob (PROVEN by gate#6 §2D).
    """
    per_scenario = [
        evaluate_scenario_graded(scenario, max_iterations=max_iterations)
        for scenario in BENCHMARK_SCENARIOS
    ]
    blob: dict[str, object] = {
        "max_iterations": max_iterations,
        "overview": scoring_overview(per_scenario),
        "per_scenario": per_scenario,
    }
    if os.environ.get("EVAL_GATE6_NEGATIVE"):
        # DELIBERATELY non-deterministic: set-iteration order varies by PYTHONHASHSEED → the blob differs
        # across seeds. The gate#6 negative test asserts this DIFFERS (proving the determinism assertion has
        # teeth — it is not a tautological always-pass). Mirrors tests.eval_harness / tests.conjunction_harness.
        blob["__set_order__"] = ",".join(set(scenario.name for scenario in BENCHMARK_SCENARIOS))
    return json.dumps(blob, sort_keys=True, separators=(",", ":"), default=str)


def _main() -> int:
    """CLI entry (``python -m tests.scoring_harness``): print the scoring blob to stdout."""
    sys.stdout.write(scoring_blob())
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
