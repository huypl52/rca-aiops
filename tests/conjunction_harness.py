"""tests/conjunction_harness — the Story-6.2 binary-conjunction MEASUREMENT INSTRUMENT (NOT a pytest test).

This module has NO ``test_`` prefix → pytest does NOT collect it. It is the Story-6.2 **full-agent
conjunction evaluator**: it drives the REAL compiled §3.5 graph (via :func:`build_default_compiled_runner`'s
``adapter`` seam, wired to a ``ScenarioTransport``-backed :class:`~adapters.readonly.CompositeReadOnlyAdapter`)
per scenario to its terminal state, then checks the **5 §3.7 conjunction conditions** (a/b/c/d/e),
computes **SM-1** (the % of the 11 scenarios where ALL 5 hold, + a per-condition breakdown quantifying
WHERE the gap bites), and runs the **SM-2 calibration mechanism** (the correlation between the agent's
ASSIGNED report confidence and its ACTUAL report correctness — read, never recomputed; AD-7).

This is the **MEASUREMENT INSTRUMENT + the HONEST BASELINE ONLY** (Story 6.2 scope). It does NOT fix the
graph: the POC graph does NOT converge (5-A1 — the rule-based plans lack VAL's trio; the floor registry is
empty so REF fail-closes; the HYP↔VAL loop is bounded → ``status="partial"``, ``report=None``). Condition
(e) (``report → faulty_service``) therefore FAILS for all 11 → **SM-1 = 0% IS THE INTENDED DELIVERABLE**
(the honest baseline), NOT a defect. The 3 FORBIDDEN MOVES apply to the MEASUREMENT:

  - **R1** — do NOT add convergence content (populate the floor registry / hypothesis-advance) to make (e)
    pass. That is 5-A1, a SEPARATE story.
  - **R2** — do NOT weaken condition (e) to "report exists OR evidence sufficient". Condition (e) is
    ``report → faulty_service``: a ``None``/uncited report is honestly (e)=False (no weakening).
  - **R3** — do NOT bypass the agent. This evaluator drives the FULL compiled graph (the agent's OWN tool
    selection via EXR, OWN evidence via ENV, OWN report via WRT). It does NOT shortcut inject→normalizer
    (that is 6.1 condition *a* alone) and does NOT hand-feed tool_calls.

**SM-2 (AD-7 single-authority + D4 defer):** the numeric confidence is the authority. The evaluator READS
``report.confidence.ceiling_confidence`` (projected by the writer from the reflector's sufficiency) — it
NEVER recomputes it. The calibration metric is a PURE function of ``[(assigned_confidence,
actual_report_correctness)]`` pairs (mean_assigned, mean_actual, gap). NO pass/fail confidence cutoff is
hardcoded (D4 — threshold/cutoff defer). Pre-convergence there are no reports → 0 pairs → the calibration
is honestly **"blocked-no-report-level-confidence"** (no fabrication).

Why this lives in ``tests/`` (NOT ``eval/``): it imports ``graph`` + ``adapters`` + ``models`` to drive the
full agent — ``eval/`` is import-restricted to ``ci.contract_schema`` + stdlib (pure DATA). The agent-
driving orchestration lives here, where any import is allowed (the SAME discipline as
:mod:`tests.eval_harness`).

Used by:
  - ``tests/test_conjunction_evaluator.py`` (in-process: the per-condition baseline + the SM-2 mechanism
    on synthetic well/over/under-calibrated pairs + the determinism prerequisite).
  - ``tests/ci/test_gate6_conjunction_determinism.py`` (the decisive cross-``PYTHONHASHSEED`` proof that
    the FULL-graph conjunction blob is byte-stable across seeds — §2F; the ``EVAL_GATE6_NEGATIVE`` env
    hook deliberately makes the blob hash-seed-dependent so the negative test proves the assertion has
    teeth, mirroring :mod:`tests.eval_harness`).

Deterministic (AD-12 / NFR-Determinism): no wall-clock, no ``random``, no network, no filesystem mutation,
no ``hash()`` on strings. The conjunction blob is canonical JSON (``sort_keys=True``) → same scenarios →
byte-identical blob regardless of ``PYTHONHASHSEED`` (PROVEN by gate#6).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import Mapping, Sequence
from typing import cast

from eval.scenarios import BENCHMARK_SCENARIOS
from eval.schema import Scenario
from graph.compiled import CompiledGraphRunner, build_default_compiled_runner
from graph.state import JsonValue
from models import IncidentTrigger, Severity, SignalType, TriggerSource
from tests.eval_harness import build_adapter, drive_evidence

# This module intentionally imports graph + adapters + models to drive the FULL agent (the eval→agent
# routing the eval/ data layer is forbidden from doing). eval/ stays import-pure (ci.contract_schema +
# stdlib).

# The 5 §3.7 binary-conjunction conditions, in §3.7 order (a stable tuple for iteration + per-condition
# breakdown). ``pass = a ∧ b ∧ c ∧ d ∧ e``.
_CONDITIONS: tuple[str, ...] = ("a", "b", "c", "d", "e")

# The dispatcher lifetime cap the harness drives the graph with. The terminal state is INVARIANT to this
# (upsert-by-id is position-stable; the bounded HYP↔VAL loop converges to the same partial state well under
# the cap) — 5 → recursion_limit 40 (5 × _NODES_PER_ITERATION 8). A deterministic POC choice; tuning defer.
_DEFAULT_MAX_ITERATIONS: int = 5

# Fixed ISO-8601 UTC trigger start (AD-12: no wall-clock). Matches the inject window every scenario uses.
_TIME_WINDOW_START: str = "2026-06-24T10:00:00Z"


# ---------------------------------------------------------------------------
# Agent-driving seam (R3 — drive the FULL compiled graph; no bypass).
# ---------------------------------------------------------------------------


def build_trigger_dump(scenario: Scenario) -> dict[str, JsonValue]:
    """Build the scenario's 18-field ``IncidentTrigger`` + dump it — the shape fed to the graph.

    Production (``routers/ingest.py``) feeds ``trigger.model_dump()`` to ``dispatch`` → the graph. The
    harness feeds the SAME shape: ``model_dump()`` (Python mode; StrEnum members are ``str`` subclasses →
    JSON-safe, matching the AD-9 spine the dispatcher stores). Mirrors the Story-6.1 ``_build_trigger``
    field-for-field so the conjunction drives the agent FAITHFULLY (R3 — no bypass; the agent receives the
    exact incident shape production sends).
    """
    trigger = IncidentTrigger(
        trigger_id=f"tr-conj-{scenario.name}",
        source=TriggerSource(scenario.trigger_source),
        signal_type=SignalType(scenario.signal_type),
        canonical_trigger=scenario.canonical_trigger,
        alert_name=scenario.canonical_trigger,
        severity=Severity(scenario.severity),
        title=f"{scenario.canonical_trigger} on {scenario.service}",
        description=scenario.supporting_evidence,
        service=scenario.service,
        affected_services=[scenario.service],
        symptom=scenario.canonical_trigger,
        namespace=scenario.namespace,
        started_at=_TIME_WINDOW_START,
        ends_at=None,
        labels={
            "service": scenario.service,
            "namespace": scenario.namespace,
            "scenario": scenario.name,
        },
        annotations={
            "summary": scenario.canonical_trigger,
            "description": scenario.supporting_evidence,
        },
        raw_payload={"scenario": scenario.name},
        raw_payload_ref=None,
    )
    # model_dump() returns dict[str, Any] (StrEnum members, not mode="json" strings) → JSON-safe via the
    # str-subclass invariant. cast narrows Any → JsonValue for the typed return.
    return cast("dict[str, JsonValue]", dict(trigger.model_dump()))


def build_scenario_runner(scenario: Scenario) -> CompiledGraphRunner:
    """Wire the compiled runner with the scenario's ScenarioTransport-backed adapter (the 6.2 seam).

    Drives the SAME compiled §3.5 graph the dispatcher would (``build_default_compiled_runner``), but with
    the ``adapter`` seam wired to a :class:`~adapters.readonly.CompositeReadOnlyAdapter` over the scenario's
    canned inject (via :func:`tests.eval_harness.build_adapter`). So the agent's OWN tool selection (EXR)
    + OWN evidence (ENV) + OWN report (WRT) through the compiled graph is what's measured — NOT a shortcut
    (R3 — conjunction forbids bypassing the agent).
    """
    return build_default_compiled_runner(adapter=build_adapter(scenario))


def run_scenario(
    scenario: Scenario, max_iterations: int = _DEFAULT_MAX_ITERATIONS
) -> dict[str, object]:
    """Drive the FULL agent to terminal for one scenario → ``{"status", "state"}`` (the terminal spine).

    The terminal ``state`` is the FULL ``InvestigationState`` projection (all 13 spine keys) — carrying the
    ``tool_calls`` (condition c), ``evidence`` (condition d), and ``report`` (condition e) the AD-9-bounded
    ``run()`` port deliberately omits. Driven via :meth:`CompiledGraphRunner.run_terminal_state` (the 6.2
    sibling of the dispatcher port; both share the singular ``_drive_to_terminal`` — no logic divergence).
    """
    runner = build_scenario_runner(scenario)
    trigger = build_trigger_dump(scenario)
    terminal = asyncio.run(
        runner.run_terminal_state(trigger, f"conj-{scenario.name}", max_iterations)
    )
    return cast("dict[str, object]", dict(terminal))


# ---------------------------------------------------------------------------
# Defensive state readers (never-raise per the graph-layer spirit; arbitrary Mapping → narrowed views).
# ---------------------------------------------------------------------------


def _terminal_state(terminal: Mapping[str, object]) -> dict[str, object]:
    """Narrow ``terminal["state"]`` to a dict (``{}`` when absent/non-dict). Never raises."""
    state = terminal.get("state")
    return state if isinstance(state, dict) else {}


def _list_of_dicts(value: object) -> list[Mapping[str, object]]:
    """Narrow ``value`` to a list of Mapping (``[]`` when not a list / non-Mapping items). Never raises."""
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, Mapping)]


def _as_mapping(value: object) -> Mapping[str, object]:
    """Narrow ``value`` to a Mapping (``{}`` when absent/non-Mapping). Never raises."""
    return value if isinstance(value, Mapping) else {}


# ---------------------------------------------------------------------------
# The 5 §3.7 conjunction conditions (a/b/c/d/e).
# ---------------------------------------------------------------------------


def condition_a(scenario: Scenario) -> bool:
    """**(a)** the inject → Evidence PIPELINE produces routable evidence covering the expected sources.

    Story-6.1 domain: the canned inject driven through the REAL adapter + REAL evidence_normalizer (no
    synthesized evidence — Epic-4 K2) routably produces Evidence whose ``source_type`` set COVERS the
    scenario's ``expected_evidence`` source_types. This is the PIPELINE check (NO agent) — the precondition
    the agent would build on; 6.2 conditions (c)/(d) measure whether the AGENT, through the compiled graph,
    actually realizes this routability. Honest baseline: (a)=11 (the inject pipeline is sound — 6.1-confirmed).
    """
    evidence = drive_evidence(scenario)
    if not evidence:
        return False
    produced = {ev.get("source_type") for ev in evidence}
    # Membership-filter (NOT set-subtraction): ``produced`` is set[object] (dict.get → object); ``set[str]
    # - set[object]`` would trip strict-mypy's invariant ``__sub__``. The ``in`` check is type-safe
    # (set.__contains__ accepts object) and reads identically (mirrors the 6.1 test).
    return all(expected.source_type in produced for expected in scenario.expected_evidence)


def condition_b(context_service: object, scenario: Scenario) -> bool:
    """**(b)** the agent received the correct incident — ``context.service == scenario.service``.

    The trigger ``source`` / ``canonical_trigger`` correctness is STRUCTURAL: the harness feeds the
    scenario's OWN trigger (built in :func:`build_trigger_dump`), verified by construction. The agent-facing
    observable is ``context.service`` (``incident_context_builder`` reads ``trigger.service``); the round-trip
    ``scenario.service → trigger → ICB → context.service`` holding proves the incident was correctly modeled
    AND received by the agent. Honest baseline: (b)=11 (the agent receives the right incident's service).
    """
    return context_service == scenario.service


def condition_c(state: Mapping[str, object], scenario: Scenario) -> bool:
    """**(c)** the agent's OWN ``tool_calls`` (via EXR) COVER the expected adapter methods.

    The agent's executed read-only tool calls (appended through the EXR node, deduped by
    ``(tool, query, timestamp_range)``). The ``tool`` values must COVER every ``expected_evidence``
    ``adapter_method`` — i.e. the agent's OWN tool selection, through the compiled graph, called the tools
    the fault's evidence requires. Honest baseline: (c)=0 — the degenerate HYP↔VAL loop never reaches EXR
    (the rule-based plans lack VAL's trio → VAL replans → EXR/ENV never run → ``tool_calls=[]``).
    """
    tool_calls = _list_of_dicts(state.get("tool_calls"))
    called = {tc.get("tool") for tc in tool_calls}
    return all(expected.adapter_method in called for expected in scenario.expected_evidence)


def condition_d(state: Mapping[str, object], scenario: Scenario) -> bool:
    """**(d)** the agent's gathered ``evidence`` (via ENV) COVERS the expected source_types.

    The normalized Evidence the agent gathered (through ENV, the evidence_normalizer). Its ``source_type``
    set must COVER every ``expected_evidence`` ``source_type`` — i.e. the agent's gathered evidence matches
    the ground-truth sources for the fault. Honest baseline: (d)=0 — ENV never runs (EXR unreachable in the
    degenerate loop) → ``evidence=[]``.
    """
    evidence = _list_of_dicts(state.get("evidence"))
    produced = {ev.get("source_type") for ev in evidence}
    return all(expected.source_type in produced for expected in scenario.expected_evidence)


def condition_e(state: Mapping[str, object], scenario: Scenario) -> bool:
    """**(e)** the report points at the correct root cause (NON-WEAKENED — R2).

    ``report → faulty_service`` implemented honestly + AD-6-grounded:
      1. ``report`` is a dict (NOT ``None``) — a ``None`` report is honestly (e)=False (R2: no "report
         exists OR evidence sufficient" weakening).
      2. ``report.root_cause`` is NON-EMPTY (≥1 grounded candidate) — the agent committed to a CITED
         root-cause claim (a hypothesis backed by ≥1 evidence with a non-null ``raw_excerpt`` — AD-6).
      3. The report's cited-evidence union (``evidence_backing``) COVERS the scenario's expected
         ``source_types`` — the cited evidence points at the fault's sources (the report is grounded IN THE
         RIGHT evidence).

    The report carries NO direct ``faulty_service`` field (it ranks candidates by ``hypothesis_id``); the
    faulty service is proxied by expected-evidence-source coverage — honest for the POC, whose inject models
    the symptom evidence (not a multi-hop path to e.g. ``coredns`` for the DNS scenario; full multi-hop
    naming is beyond POC inject). FLAGGED for leader confirmation in REVIEW-READY. Honest baseline: (e)=0 —
    the report is ``None`` for all 11 pre-convergence (5-A1).
    """
    report = state.get("report")
    if not isinstance(report, Mapping):
        return False  # R2: no report → honestly (e)=False (NOT "report exists OR evidence sufficient").
    root_cause = report.get("root_cause")
    if not _list_of_dicts(root_cause):
        return False  # no grounded candidate → the report made NO cited claim → (e)=False.
    backing = _list_of_dicts(report.get("evidence_backing"))
    cited_types = {entry.get("source_type") for entry in backing}
    return all(expected.source_type in cited_types for expected in scenario.expected_evidence)


def evaluate_conjunction(terminal: Mapping[str, object], scenario: Scenario) -> dict[str, bool]:
    """Score all 5 §3.7 conditions for one scenario's terminal state → ``{a, b, c, d, e}`` (booleans)."""
    state = _terminal_state(terminal)
    context = _as_mapping(state.get("context"))
    return {
        "a": condition_a(scenario),
        "b": condition_b(context.get("service"), scenario),
        "c": condition_c(state, scenario),
        "d": condition_d(state, scenario),
        "e": condition_e(state, scenario),
    }


# ---------------------------------------------------------------------------
# SM-1 — the % of scenarios where ALL 5 conditions hold (+ per-condition breakdown).
# ---------------------------------------------------------------------------


def evaluate_scenario(
    scenario: Scenario, *, max_iterations: int = _DEFAULT_MAX_ITERATIONS
) -> dict[str, object]:
    """Drive + score one scenario → ``{name, status, conditions, pass, ceiling_confidence, terminal_state}``.

    ``terminal_state`` (the FULL spine projection) is carried so :func:`conjunction_blob` proves the FULL
    graph is byte-stable across ``PYTHONHASHSEED`` (§2F make-or-break). ``ceiling_confidence`` (the agent's
    projected report confidence — the AD-7 authority SM-2 READS) is hoisted for the calibration pairs.
    """
    terminal = run_scenario(scenario, max_iterations)
    state = _terminal_state(terminal)
    conditions = evaluate_conjunction(terminal, scenario)
    report = _as_mapping(state.get("report"))
    confidence = _as_mapping(report.get("confidence"))
    return {
        "name": scenario.name,
        "status": terminal.get("status"),
        "prod_only": scenario.prod_only,
        "non_deterministic_extension": scenario.non_deterministic_extension,
        "conditions": conditions,
        "pass": all(conditions.values()),
        "ceiling_confidence": confidence.get("ceiling_confidence"),
        "terminal_state": dict(state),
    }


def _conditions_of(per_scenario: Mapping[str, object]) -> Mapping[str, object]:
    """Narrow a per-scenario row's ``conditions`` to a Mapping (``{}`` when absent/non-Mapping)."""
    conditions = per_scenario.get("conditions")
    return conditions if isinstance(conditions, Mapping) else {}


def sm1_overview(per_scenario: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """SM-1: the % of scenarios where ALL 5 conditions hold + the per-condition breakdown.

    The per-condition breakdown (a count of how many of the 11 each condition satisfies) quantifies WHERE
    the gap bites — the headline insight: (a)/(b) hold (pipeline + incident-routing are sound), (c)/(d)/(e)
    do NOT (the agent never executes the EXR→ENV→WRT path in the non-converging POC graph → 5-A1). All 11
    scenarios are scored (the A8 ``prod_only`` flag MARKS disk/memory; it does NOT exclude them from SM-1).
    Partial-credit + tolerance defer to 6.3 (SM-1 here is the strict binary ``a ∧ b ∧ c ∧ d ∧ e``).
    """
    n = len(per_scenario)
    n_pass = sum(1 for ps in per_scenario if ps.get("pass") is True)
    per_condition: dict[str, int] = {
        key: sum(1 for ps in per_scenario if _conditions_of(ps).get(key) is True)
        for key in _CONDITIONS
    }
    return {
        "n": n,
        "n_pass": n_pass,
        "sm1": (n_pass / n) if n else None,
        "per_condition": per_condition,
    }


# ---------------------------------------------------------------------------
# SM-2 — calibration mechanism (AD-7 single-authority; D4 no-cutoff; pure function of pairs).
# ---------------------------------------------------------------------------


def calibration_summary(pairs: list[tuple[float, bool]]) -> dict[str, object]:
    """SM-2 calibration — PURE function of ``[(assigned_confidence, actual_correctness)]`` pairs.

    No threshold / cutoff is hardcoded (D4 — pass/fail confidence cutoff defer). Reports the means + the
    calibration ``gap`` (``mean_assigned - mean_actual``; +ve = over-confident, -ve = under-confident,
    ≈0 = well-calibrated). AD-7: ``assigned_confidence`` is the authority READ from the report — this
    function NEVER recomputes it. An empty pair list → ``"blocked-no-report-level-confidence"`` (honest —
    no report-level confidence exists to calibrate against in the current non-converging graph; no
    fabrication of a synthetic verdict).
    """
    n = len(pairs)
    if n == 0:
        return {
            "n_pairs": 0,
            "mean_assigned": None,
            "mean_actual": None,
            "gap": None,
            "status": "blocked-no-report-level-confidence",
        }
    mean_assigned = sum(assigned for assigned, _actual in pairs) / n
    mean_actual = sum(1 for _assigned, actual in pairs if actual) / n
    return {
        "n_pairs": n,
        "mean_assigned": mean_assigned,
        "mean_actual": mean_actual,
        "gap": mean_assigned - mean_actual,
        "status": "ok",
    }


def sm2_calibration(per_scenario: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Extract ``(assigned report confidence, actual report correctness)`` pairs → :func:`calibration_summary`.

    AD-7: ``assigned`` = ``report.confidence.ceiling_confidence`` (the agent's projected authority — READ,
    never recomputed). ``actual`` = condition **(e)** (did the report point at the correct root cause — the
    report-level correctness the confidence calibrates against). A pair is recorded ONLY when the report
    carries a NUMERIC ``ceiling_confidence`` (a ``None`` report has no confidence to calibrate). Pre-
    convergence (no reports) → 0 pairs → :func:`calibration_summary` returns ``"blocked"`` (honest).
    """
    pairs: list[tuple[float, bool]] = []
    for ps in per_scenario:
        ceiling = ps.get("ceiling_confidence")
        # A numeric confidence only (a bool is an int subclass → rejected; AD-7 0.0–1.0 numeric authority).
        if not (isinstance(ceiling, int | float) and not isinstance(ceiling, bool)):
            continue
        actual = _conditions_of(ps).get("e") is True
        pairs.append((float(ceiling), actual))
    return calibration_summary(pairs)


# ---------------------------------------------------------------------------
# The canonical conjunction blob (gate#6 §2F determinism unit + the REVIEW-READY payload).
# ---------------------------------------------------------------------------


def conjunction_blob(*, max_iterations: int = _DEFAULT_MAX_ITERATIONS) -> str:
    """Canonical-JSON conjunction report for ALL 11 scenarios (the gate#6 subprocess output + §2F payload).

    The blob carries ``sm1`` (+ per-condition breakdown), ``sm2`` (calibration), and ``per_scenario`` (each
    row with its ``conditions``, ``pass``, ``ceiling_confidence``, and the FULL ``terminal_state`` spine
    projection). The terminal-state inclusion is the §2F make-or-break payload: the blob is byte-stable
    across ``PYTHONHASHSEED`` ONLY IF the FULL compiled graph is deterministic (no hash-ordered structure
    leaks into the spine). Deterministic + PYTHONHASHSEED-safe: canonical JSON (``sort_keys=True``). Same
    scenarios → byte-identical blob (AD-12 / NFR-Determinism; PROVEN by gate#6).
    """
    per_scenario = [
        evaluate_scenario(scenario, max_iterations=max_iterations)
        for scenario in BENCHMARK_SCENARIOS
    ]
    blob: dict[str, object] = {
        "max_iterations": max_iterations,
        "sm1": sm1_overview(per_scenario),
        "sm2": sm2_calibration(per_scenario),
        "per_scenario": per_scenario,
    }
    if os.environ.get("EVAL_GATE6_NEGATIVE"):
        # DELIBERATELY non-deterministic: set-iteration order varies by PYTHONHASHSEED → the blob differs
        # across seeds. The gate#6 negative test asserts this DIFFERS (proving the determinism assertion
        # has teeth — it is not a tautological always-pass). Mirrors :mod:`tests.eval_harness`.
        blob["__set_order__"] = ",".join(set(scenario.name for scenario in BENCHMARK_SCENARIOS))
    return json.dumps(blob, sort_keys=True, separators=(",", ":"), default=str)


def _main() -> int:
    """CLI entry (``python -m tests.conjunction_harness``): print the conjunction blob to stdout."""
    sys.stdout.write(conjunction_blob())
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
