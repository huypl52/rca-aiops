"""tests.retrieval_harness — the Story-6.4 PLAYBOOK-RETRIEVAL INDEPENDENT AXIS (SM-4 / FR-10e / A6)
+ TRAIN/EVAL SPLIT (Q8 / FR-10) — TWO new INDEPENDENT columns ABOVE (NOT over) the 6.1/6.2/6.3 baselines.

This module has NO ``test_`` prefix → pytest does NOT collect it. It is the Story-6.4 **measurement
instrument** that adds TWO independent columns to the eval layer, kept STRICTLY SEPARATE from the
6.1/6.2/6.3 correctness/scoring baselines (which it does NOT touch — R1: ``scoring_harness`` /
``conjunction_harness`` / ``eval_harness`` are byte-for-byte unchanged):

  1. **SM-4 (FR-10e / A6) — playbook-retrieval independent axis.** A retrieval-CONTRIBUTION metric
     (``% investigation retrieval đóng góp``) measuring the fraction of the ground-truth playbook
     set the preplanning retriever returned (recall). It is a SEPARATE column — it is NEVER folded
     into SM-1 correctness, NEVER averaged with the §3.7 conjunction, NEVER reported as a pass
     (R2 — AC6 verbatim: "% investigation retrieval đóng góp — KHÔNG trộn vào correctness").
     SM-4 reads the REAL ``playbook_hits`` from the terminal-state spine (the actual
     :func:`~graph.nodes.preplanning_playbook_retriever` output — R3: never synthesized).
  2. **Q8 (FR-10) — train/eval split.** A DETERMINISTIC partition of the 11 ``BENCHMARK_SCENARIOS``
     into train + eval (calibrate-on-train / eval-on-eval discipline, leak-free — no feedback-loop
     bias). Index-based over the FROZEN scenario tuple → byte-stable + PYTHONHASHSEED-safe (AD-12).

This is the MEASUREMENT INSTRUMENT + the HONEST BASELINE ONLY (Story 6.4 scope). It does NOT add
retrieval content (R1): the POC retriever is WIRED (``compiled.py``: ``START → N_ICB → N_PBR → N_HYP``)
but the scenario transport has NO Qdrant corpus (no scenario injects ``search_playbook`` →
``ScenarioTransport._qdrant=None`` → ``read_qdrant()=None`` → ``QdrantAdapter.search_playbook`` raises
``TypeError`` on ``"error" in None`` → PBR's never-raise ``except Exception`` degrades to
``playbook_hits=[]`` 11/11). So SM-4's honest baseline is **EMPTY/DEGRADED** (``playbook_hits=[]``
11/11; recall blocked — no ground-truth in the real baseline AND 0 hits). The Q8 partition IS defined
+ leak-free + deterministic, but the calibration is MOOT (pre-convergence → no reports → no D3 floor /
D4 cutoff to calibrate — 5-A1). These are the DELIVERABLE honest baselines, NOT defects (R1).

The 3 FORBIDDEN MOVES (anti-gaming) apply to the MEASUREMENT:

  - **R1** — do NOT add retrieval/convergence content. Do NOT wire a Qdrant backend, classify
    ``canonical_trigger`` into ``context``, populate ``playbook_hits``, or build a floor/playbook
    registry to make SM-4 non-zero. That is the 5-A1 family (a SEPARATE story). The honest EMPTY
    baseline is the deliverable.
  - **R2** — do NOT mix SM-4 into correctness. SM-4 is a SEPARATE INDEPENDENT column — never folded
    into SM-1, never averaged with the conjunction, never reported as a pass. The Q8 split ratio is
    D4-deferred (lock the MECHANISM, defer the NUMBERS — gate #6 asserts leak-free + deterministic,
    NOT a specific ratio NOR a retrieval PASS).
  - **R3** — do NOT bypass the agent / do NOT synthesize. SM-4 reads the REAL ``playbook_hits`` (the
    actual PBR output via 6.2's :func:`evaluate_scenario` terminal state). The ground-truth
    ``canonical_trigger → playbook`` map for teeth is a clearly-labeled SYNTHETIC test fixture applied
    to CONTROLLED synthetic hits in the test file ONLY — NEVER substituted for the real baseline. Q8
    partitions over the REAL scenario identities (the frozen ``BENCHMARK_SCENARIOS`` tuple).

NO new production seam (the dispatch scope boundary): this module reads 6.2's
:func:`~tests.conjunction_harness.evaluate_scenario` (the full compiled-graph terminal state, carrying
the spine's ``playbook_hits`` — the REAL PBR output) + 6.1's ``BENCHMARK_SCENARIOS``. It touches NO
``graph/`` / ``services/`` / ``routers/`` / ``models/`` code. (6.2 paid the opt1-seam cost; 6.4
reuses it. ``eval/`` stays import-pure; the agent-driving orchestration this layer builds ON lives in
``tests/`` — the SAME discipline as :mod:`tests.conjunction_harness` / :mod:`tests.scoring_harness`.)

Why this lives in ``tests/``: it imports ``tests.conjunction_harness`` (which imports ``graph`` +
``adapters`` + ``models``) + ``eval.scenarios`` — the same reason 6.2/6.3 live here, not in ``eval/``.

Used by:
  - ``tests/test_retrieval_evaluator.py`` (in-process: the SM-4 EMPTY baseline 11/11 + the SM-4
    recall TEETH on CONTROLLED synthetic hits + the synthetic ground-truth map; the Q8 partition
    leak-free + deterministic; the determinism prerequisite).
  - ``tests/ci/test_gate6_retrieval_determinism.py`` (the decisive cross-``PYTHONHASHSEED`` proof that
    the SM-4 + Q8 blob is byte-stable across seeds — §2C; the ``EVAL_GATE6_NEGATIVE`` hook deliberately
    makes the blob hash-seed-dependent so the negative test proves the assertion has teeth, mirroring
    6.1/6.2/6.3).

Deterministic (AD-12 / NFR-Determinism): no wall-clock, no ``random``, no network, no filesystem
mutation, no ``hash()`` on strings. SM-4 = set-membership counts (``in`` checks, order-independent)
+ ``int`` counts + a ``float`` recall; the synthetic ground-truth map is exercised in the TEST FILE
only (never in the baseline blob). Q8 = index-based partition over the FROZEN tuple (the partition
sets are SORTED before serialization → no hash-order leak; the leak-free ``isdisjoint`` / union checks
are order-independent). The blob is canonical JSON (``sort_keys=True``) → same scenarios → byte-
identical blob regardless of ``PYTHONHASHSEED`` (PROVEN by gate #6 §2C).
"""

from __future__ import annotations

import json
import os
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

# This module intentionally builds ON 6.2's agent-driving orchestration (tests.conjunction_harness —
# which already imports graph + adapters + models) + 6.1's benchmark data (eval.scenarios). eval/
# stays import-pure. It does NOT touch scoring_harness / conjunction_harness / eval_harness (R1 — the
# 6.1/6.2/6.3 baselines are byte-for-byte unchanged; SM-4 + Q8 are NEW columns, additive only).


# ---------------------------------------------------------------------------
# Q8 (FR-10) — DETERMINISTIC train/eval partition over the FROZEN scenario tuple.
# ---------------------------------------------------------------------------

# The MECHANISM (locked): a partition is expressed as a frozenset of TRAIN INDICES over the FROZEN
# BENCHMARK_SCENARIOS tuple (the eval set = the complement). Index-based over a frozen tuple is
# byte-stable + PYTHONHASHSEED-safe (AD-12: no hash-on-strings). The specific RATIO (8 train / 3
# eval) is a DOCUMENTED POC default; it is D4-DEFERRED — NOT tuned, NOT asserted by gate #6 (the gate
# asserts the MECHANISM: leak-free + byte-stable, NOT the ratio NOR a retrieval PASS — R2). The frozen
# tuple order (eval.scenarios): dependency_timeout(0) · payment_failure(1) · latency_spike(2) ·
# disk_pressure(3) · memory_leak(4) · inventory_reserve_failure(5) · dns_failure(6) ·
# certificate_expired(7) · crashloop(8) · oom(9) · bad_deployment_config(10).
_TRAIN_INDICES: tuple[int, ...] = (0, 1, 2, 3, 4, 5, 6, 7)
"""The Q8 train partition — the FIRST 8 of the FROZEN ``BENCHMARK_SCENARIOS`` tuple (eval = the last 3)."""


def q8_split(
    scenarios: Sequence[Scenario] = BENCHMARK_SCENARIOS,
    *,
    train_indices: Sequence[int] = _TRAIN_INDICES,
) -> dict[str, object]:
    """Q8 (FR-10): DETERMINISTIC train/eval partition of the benchmark scenarios (the MECHANISM).

    A partition is expressed as a frozenset of TRAIN indices over the FROZEN ``scenarios`` tuple (the
    eval set = the complement). Index-based over a frozen tuple → byte-stable + PYTHONHASHSEED-safe
    (AD-12: no ``hash()`` on strings; the partition sets are SORTED before serialization → no
    hash-order leak reaches the blob; the leak-free ``isdisjoint`` / union checks are order-independent).
    calibrate-on-train / eval-on-eval discipline is EXPRESSED; the calibration itself is MOOT
    pre-convergence (no reports → no D3 floor / D4 cutoff to calibrate — 5-A1). The SPECIFIC ratio is
    D4-deferred (R2 — gate #6 asserts leak-free + deterministic, NOT the ratio NOR a retrieval PASS).

    **Leak-free invariant (the Q8 gate assertion):** ``train ∩ eval == ∅`` AND ``train ∪ eval == all``
    (no scenario in both sets — no feedback-loop bias). The returned ``leak_free`` flag carries this.

    Deterministic + pure (AD-12): no wall-clock / random / IO / hash-on-strings; never raises.
    """
    names = tuple(s.name for s in scenarios)
    n_total = len(names)
    all_indices = frozenset(range(n_total))
    train_idx = frozenset(i for i in train_indices if isinstance(i, int) and i in all_indices)
    eval_idx = all_indices - train_idx
    train_names = frozenset(names[i] for i in range(n_total) if i in train_idx)
    eval_names = frozenset(names[i] for i in range(n_total) if i in eval_idx)
    all_names = frozenset(names)
    leak_free = bool(train_names.isdisjoint(eval_names) and (train_names | eval_names) == all_names)
    return {
        "n_total": n_total,
        "n_train": len(train_names),
        "n_eval": len(eval_names),
        "train_names": sorted(train_names),  # sorted → byte-stable (AD-12; no hash-order leak)
        "eval_names": sorted(eval_names),
        "leak_free": leak_free,
        "ratio_train_eval": [len(train_names), len(eval_names)],
        "calibration": "moot-no-reports",  # pre-convergence (5-A1) — no reports to calibrate D3/D4 on
        "split_ratio_status": "d4-deferred",  # the specific ratio is NOT tuned/asserted (D4)
    }


# ---------------------------------------------------------------------------
# SM-4 (FR-10e / A6) — the playbook-RETRIEVAL independent axis (SEPARATE from SM-1 — R2).
# ---------------------------------------------------------------------------


def sm4_retrieval(
    playbook_hits: object,
    *,
    expected_ids: frozenset[str] | None = None,
) -> dict[str, object]:
    """SM-4 (FR-10e / A6): the playbook-RETRIEVAL independent axis — a SEPARATE column (R2).

    A retrieval-CONTRIBUTION metric (``% investigation retrieval đóng góp``): the recall of the
    retriever's ``playbook_hits`` against a ground-truth ``expected_ids`` set (the
    ``canonical_trigger → playbook`` map). Reads the REAL ``playbook_hits`` (the actual PBR output —
    R3: never synthesized; the caller passes the terminal-state spine's ``playbook_hits``).

    Two modes (the R3 discipline):
      - **REAL baseline** (``expected_ids is None``): no ground-truth is substituted into the baseline
        (the synthetic map is a TEST-FIXTURE applied to controlled synthetic hits in the test file
        ONLY — R3) → SM-4 reports the honest EMPTY/DEGRADED baseline. On the 11 scenarios
        ``playbook_hits=[]`` (the retriever ran but the Qdrant corpus is absent — 5-A1-family; R1) →
        ``n_hits=0``, ``recall=None`` (blocked — no denominator AND 0 hits), ``status="empty-degraded"``.
        Do NOT inflate (R1).
      - **TEETH** (``expected_ids`` provided — TEST FILE only): recall = ``|relevant| / |expected|``
        computed over controlled synthetic hits → the instrument FIRES a measurable value (proving it
        is not a tautological always-zero). NEVER substituted for the real baseline (R3).

    Deterministic (AD-12): set-membership only (``in`` checks), ``int`` counts, a ``float`` recall —
    no hash-ordered structure is serialized → PYTHONHASHSEED-safe. Never raises.
    """
    hits = _list_of_dicts(playbook_hits)
    hit_ids = {h.get("id") for h in hits}  # membership-only (order-independent); never serialized
    n_hits = len(hits)
    if expected_ids is None:
        # REAL baseline — no synthetic ground-truth substituted (R3). recall is blocked (no
        # denominator) AND 0 hits anyway → the honest EMPTY/DEGRADED baseline (R1: do NOT inflate).
        return {
            "n_hits": n_hits,
            "n_expected": None,
            "n_relevant": None,
            "recall": None,
            "status": "empty-degraded" if n_hits == 0 else "populated-no-ground-truth",
        }
    expected = set(expected_ids)
    n_relevant = sum(1 for pid in expected if pid in hit_ids)  # membership-only (order-independent)
    n_expected = len(expected)
    # Vacuous truth when expected is empty (mirrors coverage_{a..e} in scoring_harness: all([])==True).
    recall = (n_relevant / n_expected) if n_expected else 1.0
    return {
        "n_hits": n_hits,
        "n_expected": n_expected,
        "n_relevant": n_relevant,
        "recall": recall,
        "status": "ok",
    }


def _sm4_of(row: Mapping[str, object]) -> Mapping[str, object]:
    """Narrow a per-scenario row's ``sm4`` to a Mapping (``{}`` when absent/non-Mapping)."""
    sm4 = row.get("sm4")
    return sm4 if isinstance(sm4, Mapping) else {}


def _mean_floats(values: Sequence[object]) -> float | None:
    """Mean of the float-typed values in ``values`` (``None`` when none are numeric; never raises).

    Mirrors :func:`tests.scoring_harness._mean_floats` (the proven mypy-clean pattern: the ``isinstance``
    filter narrows the LOOP variable in a local list-comp, so ``float(v)`` type-checks). Returns ``None``
    (NOT ``0.0``) when no value is numeric — the SM-4 honest baseline (recall blocked, R3/R1).
    """
    numeric = [v for v in values if isinstance(v, int | float) and not isinstance(v, bool)]
    return (sum(float(v) for v in numeric) / len(numeric)) if numeric else None


def sm4_overview(per_scenario: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Aggregate the SM-4 axis across scenarios (the SEPARATE retrieval column — R2: never SM-1).

    Reports the count of EMPTY vs POPULATED retrieval + the mean recall. On the real baseline the mean
    recall is ``None`` (blocked — no ground-truth in the baseline AND 0 hits — R3/R1). The binary SM-1
    headline (6.2) is NOT recomputed here (R2: SM-4 is a SEPARATE supplementary axis, never conflated).
    Honest baseline: ``n_empty=11``, ``n_populated=0``, ``recall_mean=None``, ``status="blocked-empty-retrieval"``.
    """
    n = len(per_scenario)
    n_empty = sum(1 for row in per_scenario if _sm4_of(row).get("status") == "empty-degraded")
    n_populated = n - n_empty
    recall_mean = _mean_floats([_sm4_of(row).get("recall") for row in per_scenario])
    status = "blocked-empty-retrieval" if (n and n_empty == n) else ("partial" if n else "empty")
    return {
        "n": n,
        "n_empty": n_empty,
        "n_populated": n_populated,
        "recall_mean": recall_mean,
        "status": status,
    }


# ---------------------------------------------------------------------------
# The per-scenario retrieval evaluator (REUSES 6.2's terminal state — NO new seam).
# ---------------------------------------------------------------------------


def evaluate_retrieval(
    scenario: Scenario, *, max_iterations: int = _DEFAULT_MAX_ITERATIONS
) -> dict[str, object]:
    """Score one scenario's SM-4 axis → ``{name, canonical_trigger, sm4}`` (REUSES 6.2's terminal state).

    Drives 6.2's :func:`evaluate_scenario` ONCE (the full compiled graph → terminal-state spine carrying
    the REAL ``playbook_hits``), then computes SM-4 ON TOP. The SM-4 column is SEPARATE from SM-1 / the
    graded coverage (6.2/6.3 baselines untouched — R1); it reads ``playbook_hits`` only. No production
    code is touched; this reads 6.2's surface only.

    The REAL ``playbook_hits`` is passed to :func:`sm4_retrieval` with ``expected_ids=None`` → the honest
    EMPTY/DEGRADED baseline (no synthetic ground-truth substituted — R3; the synthetic map is a
    test-file fixture for TEETH only).
    """
    base = evaluate_scenario(scenario, max_iterations=max_iterations)
    state = _as_mapping(base.get("terminal_state"))
    playbook_hits = state.get("playbook_hits")  # the REAL PBR output (R3) — empty as it is
    return {
        "name": scenario.name,
        "canonical_trigger": scenario.canonical_trigger,
        "sm4": sm4_retrieval(
            playbook_hits
        ),  # expected_ids=None → honest baseline (R3 — no map substituted)
    }


# ---------------------------------------------------------------------------
# The canonical retrieval blob (gate#6 §2C determinism unit + the REVIEW-READY payload).
# ---------------------------------------------------------------------------


def retrieval_blob(*, max_iterations: int = _DEFAULT_MAX_ITERATIONS) -> str:
    """Canonical-JSON SM-4 + Q8 report for ALL 11 scenarios (the gate#6 subprocess output + §2C payload).

    The blob carries the ``sm4`` overview (the SEPARATE retrieval column — EMPTY/DEGRADED 11/11 honest
    baseline), the ``q8`` partition (leak-free + deterministic + calibration moot), and ``per_scenario``
    (each row's SM-4 reading of the REAL ``playbook_hits``). Byte-stability across ``PYTHONHASHSEED``
    (§2C) holds ONLY IF the SM-4 + Q8 computation is deterministic (no hash-ordered structure leaks into
    the blob): SM-4 = set-membership counts + a float recall, Q8 = sorted partition lists + order-
    independent leak checks — all PYTHONHASHSEED-safe. Canonical JSON (``sort_keys=True``); same
    scenarios → byte-identical blob (PROVEN by gate #6 §2C).
    """
    per_scenario = [
        evaluate_retrieval(scenario, max_iterations=max_iterations)
        for scenario in BENCHMARK_SCENARIOS
    ]
    blob: dict[str, object] = {
        "max_iterations": max_iterations,
        "sm4": sm4_overview(per_scenario),
        "q8": q8_split(),
        "per_scenario": per_scenario,
    }
    if os.environ.get("EVAL_GATE6_NEGATIVE"):
        # DELIBERATELY non-deterministic: set-iteration order varies by PYTHONHASHSEED → the blob differs
        # across seeds. The gate#6 negative test asserts this DIFFERS (proving the determinism assertion
        # has teeth — it is not a tautological always-pass). Mirrors the 6.1/6.2/6.3 harnesses.
        blob["__set_order__"] = ",".join(set(scenario.name for scenario in BENCHMARK_SCENARIOS))
    return json.dumps(blob, sort_keys=True, separators=(",", ":"), default=str)


def _main() -> int:
    """CLI entry (``python -m tests.retrieval_harness``): print the retrieval blob to stdout."""
    sys.stdout.write(retrieval_blob())
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
