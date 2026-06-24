"""Story 6.4 — the PLAYBOOK-RETRIEVAL INDEPENDENT AXIS (SM-4 / FR-10e / A6) + TRAIN/EVAL SPLIT (Q8).

Covers the Story-6.4 DEEP spotlights:

  - **the HONEST BASELINE is REPORTED (R1)** — driving the FULL compiled §3.5 graph (reused from 6.2) over
    all 11 yields the EMPTY/DEGRADED retrieval baseline: ``playbook_hits=[]`` 11/11 → SM-4
    ``status="empty-degraded"``, ``n_hits=0``, ``recall=None`` (blocked). The 6.1/6.2/6.3 baselines are
    UNCHANGED (R1: ``retrieval_harness`` is ADDITIVE — it touches no existing harness/artifact). SM-4 does
    NOT add retrieval content (no Qdrant wiring, no playbook corpus) — the EMPTY baseline is the deliverable.
  - **the WHY the baseline is empty is INVESTIGATED + ENCODED (spotlight #4)** — the retriever IS wired
    (``START → N_ICB → N_PBR → N_HYP``) and RAN with a VALID trigger (``trigger.canonical_trigger`` is
    populated), yet ``playbook_hits=[]`` because the adapter has NO Qdrant corpus (no scenario injects
    ``search_playbook`` → ``ScenarioTransport._qdrant=None`` → ``QdrantAdapter.search_playbook`` raises
    ``TypeError`` → PBR's never-raise ``except`` degrades). This is the 5-A1-family/D3 content gap — NOT a
    missing-trigger bug. ``context.canonical_trigger`` IS ``None`` (CTX does not classify it into context)
    but this is BENIGN: PBR + floor_check read ``trigger.canonical_trigger`` (never context). The leader's
    "context.canonical_trigger=None explains the degradation" hypothesis is DISPROVEN — encoded as a
    regression test + a new carry-forward.
  - **the INSTRUMENT reads the REAL pipeline (R3)** — SM-4 reads the REAL ``playbook_hits`` from the 6.2
    terminal-state spine (``sm4.n_hits == len(terminal_state.playbook_hits)``), NEVER a synthesized input.
  - **the INSTRUMENT has TEETH (R3)** — SM-4 recall fires on CONTROLLED synthetic hits + a clearly-labeled
    SYNTHETIC ``canonical_trigger → playbook`` ground-truth map: full / partial / zero recall. A SM-4 that
    stayed zero on populated hits would be tautological. The synthetic map is NEVER substituted for the real
    baseline (``retrieval_blob`` always calls ``sm4_retrieval`` with ``expected_ids=None``).
  - **SM-4 is a SEPARATE column (R2)** — it is NEVER folded into SM-1 (the retrieval blob carries ``sm4``,
    NOT the conjunction ``conditions`` / ``pass`` surface), NEVER reported as a pass, NEVER averaged with
    correctness. The Q8 split ratio is D4-deferred (lock mechanism, defer numbers).
  - **Q8 is leak-free + deterministic + calibration-moot** — the partition covers all 11, train ∩ eval = ∅,
    is index-based over the FROZEN tuple (byte-stable), and calibration is ``"moot-no-reports"``
    pre-convergence (5-A1).
  - **the determinism prerequisite** — the retrieval blob is byte-stable across repeated in-process runs
    (the decisive cross-``PYTHONHASHSEED`` proof is gate #6, ``tests/ci/test_gate6_retrieval_determinism.py``).

The retrieval evaluator itself lives in :mod:`tests.retrieval_harness` (NOT collected by pytest — the
``test_`` prefix is HERE). This test imports it + asserts its honest output + its mechanism soundness.
"""

from __future__ import annotations

import json

import pytest

from eval import BENCHMARK_SCENARIOS
from eval.scenarios import DEPENDENCY_TIMEOUT
from eval.schema import Scenario
from tests.conjunction_harness import _as_mapping, evaluate_scenario
from tests.retrieval_harness import (
    evaluate_retrieval,
    q8_split,
    retrieval_blob,
    sm4_overview,
    sm4_retrieval,
)

# A clearly-labeled SYNTHETIC ground-truth map (canonical_trigger → expected playbook ids) for the SM-4
# recall TEETH ONLY (R3). NEVER substituted into the real baseline (retrieval_blob always calls
# sm4_retrieval with expected_ids=None). These ids are NOT real Qdrant playbooks — the corpus is DEFERRED
# content (5-A1-family / D3); they exist only to prove the instrument FIRES on populated hits.
_SYNTHETIC_PLAYBOOK_MAP: dict[str, frozenset[str]] = {
    "DependencyTimeout": frozenset({"pb-dep-timeout-restart", "pb-dep-timeout-circuit-breaker"}),
    "OOMKilled": frozenset({"pb-oom-resource-limit", "pb-oom-leak-investigation"}),
    "CrashLoopBackOff": frozenset({"pb-crashloop-image-pull", "pb-crashloop-readiness"}),
}


def _synthetic_hits(*ids: str) -> list[dict[str, object]]:
    """Controlled synthetic ``playbook_hits`` (R3 teeth) — each ``{id, score, title}`` (the hit shape PBR
    forwards). Used ONLY to prove the SM-4 instrument computes a measurable recall on populated hits."""
    return [{"id": pid, "score": 0.9, "title": f"playbook {pid}"} for pid in ids]


# ---------------------------------------------------------------------------
# The HONEST BASELINE — SM-4 EMPTY/DEGRADED over all 11 (5-A1-family retrieval gap, R1).
#
# The 6.1/6.2/6.3 baselines are UNCHANGED (R1): retrieval_harness is ADDITIVE. SM-4 reports the SAME empty
# retrieval as the spine's playbook_hits ([]) — it does NOT populate the corpus (no Qdrant wiring — R1).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("scenario", BENCHMARK_SCENARIOS, ids=lambda s: s.name)
def test_baseline_sm4_is_empty_degraded(scenario: Scenario) -> None:
    """SM-4 ``status="empty-degraded"``, ``n_hits=0``, ``recall=None`` for every scenario (R1 — NOT fixed).

    The retriever RAN but produced 0 hits (no Qdrant corpus — 5-A1-family) → SM-4 honestly reports the
    EMPTY/DEGRADED baseline. ``recall`` is ``None`` (blocked — no ground-truth in the real baseline AND 0
    hits — R3/R1). Not a defect; not fixed in 6.4.
    """
    sm4 = evaluate_retrieval(scenario)["sm4"]
    assert isinstance(sm4, dict)
    assert sm4["status"] == "empty-degraded", (
        f"{scenario.name}: SM-4 must be empty-degraded (playbook_hits=[] — retriever degraded, R1)"
    )
    assert sm4["n_hits"] == 0, f"{scenario.name}: SM-4 n_hits must be 0 (playbook_hits=[] 11/11)"
    assert sm4["recall"] is None, f"{scenario.name}: SM-4 recall must be None (blocked — R3/R1)"
    assert sm4["n_expected"] is None  # no synthetic ground-truth substituted into the baseline (R3)
    assert sm4["n_relevant"] is None


def test_baseline_sm4_overview_is_blocked_empty() -> None:
    """The SM-4 overview: ``n_empty=11``, ``n_populated=0``, ``recall_mean=None``, status blocked (R1).

    Carries-forward the empty-retrieval baseline at the aggregate level. ``recall_mean`` is ``None``
    (blocked — no ground-truth + 0 hits). SM-4 is a SEPARATE column (R2): the 6.2 SM-1 headline is NOT
    recomputed here.
    """
    per_scenario = [evaluate_retrieval(s) for s in BENCHMARK_SCENARIOS]
    overview = sm4_overview(per_scenario)
    assert overview["n"] == 11
    assert overview["n_empty"] == 11
    assert overview["n_populated"] == 0
    assert overview["recall_mean"] is None
    assert overview["status"] == "blocked-empty-retrieval"


# ---------------------------------------------------------------------------
# Spotlight #4 — WHY the baseline is empty (investigated + encoded; NOT fixed — R1).
#
# The retriever IS wired + RAN with a VALID trigger, yet degraded. The empty baseline is the ADAPTER CORPUS
# GAP (no Qdrant backend — 5-A1-family/D3), NOT a missing-trigger bug. context.canonical_trigger IS None but
# is BENIGN (no node reads it — PBR/floor_check read trigger.canonical_trigger, which IS populated).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("scenario", BENCHMARK_SCENARIOS, ids=lambda s: s.name)
def test_baseline_retrieval_degrades_despite_a_valid_trigger(scenario: Scenario) -> None:
    """Spotlight #4 (WHY ``playbook_hits=[]``): the retriever RAN with a VALID trigger but DEGRADED.

    ``trigger.canonical_trigger`` IS populated (PBR built the query + called ``search_playbook``), yet
    ``playbook_hits==[]`` → the empty baseline is the ADAPTER CORPUS GAP (no scenario injects
    ``search_playbook`` → ``ScenarioTransport._qdrant=None`` → ``QdrantAdapter.search_playbook`` raises
    ``TypeError`` on ``"error" in None`` → PBR's never-raise ``except Exception`` degrades), NOT a
    missing-trigger bug. This is the honest 5-A1-family/D3 baseline (R1) — NOT a defect to fix in 6.4.
    """
    state = _as_mapping(evaluate_scenario(scenario)["terminal_state"])
    trigger = _as_mapping(state.get("trigger"))
    canonical = trigger.get("canonical_trigger")
    assert isinstance(canonical, str) and canonical, (  # the trigger IS populated → retriever ran
        f"{scenario.name}: the empty retrieval is NOT a missing-trigger bug (canonical_trigger={canonical!r})"
    )
    assert state.get("playbook_hits") == [], (  # ...yet degraded (adapter corpus gap — 5-A1-family)
        f"{scenario.name}: playbook_hits must be [] (retriever degraded — no Qdrant corpus); got "
        f"{state.get('playbook_hits')!r}"
    )


def test_context_canonical_trigger_absent_but_non_functional() -> None:
    """Spotlight #4 (the ``context.canonical_trigger=None`` observation): CTX does NOT classify
    ``canonical_trigger`` into ``context`` — but this is BENIGN.

    CTX builds ``context = {service, namespace, time_window, labels, topology_seed}`` (no canonical_trigger);
    PBR + floor_check read ``trigger.canonical_trigger`` (populated), NEVER ``context.canonical_trigger``.
    So ``context.canonical_trigger=None`` does NOT explain the empty retrieval nor block floor_check — the
    leader's hypothesis is DISPROVEN. It is a cosmetic schema-omission, lowest priority (nothing reads it);
    NOT a functional gap; NOT fixed in 6.4 (would be a 5-A1-family CTX-mirror — a SEPARATE story).
    """
    state = _as_mapping(evaluate_scenario(DEPENDENCY_TIMEOUT)["terminal_state"])
    context = _as_mapping(state.get("context"))
    trigger = _as_mapping(state.get("trigger"))
    assert context.get("canonical_trigger") is None  # absent in context (CTX does not classify it)
    assert (
        trigger.get("canonical_trigger") == "DependencyTimeout"
    )  # but present in trigger (PBR/floor read)


# ---------------------------------------------------------------------------
# The SM-4 MECHANISM reads the REAL pipeline (R3) — never a synthesized input.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("scenario", BENCHMARK_SCENARIOS, ids=lambda s: s.name)
def test_sm4_reads_the_real_terminal_state_playbook_hits(scenario: Scenario) -> None:
    """R3: SM-4 reads the REAL ``playbook_hits`` from the 6.2 terminal-state spine (NOT synthesized).

    ``sm4.n_hits`` equals ``len(terminal_state.playbook_hits)`` → SM-4 reads the SAME real PBR output the
    spine carries (via 6.2's ``evaluate_scenario``). A SM-4 on synthesized input would be a bypass (R3).
    """
    base = evaluate_scenario(scenario)
    spine_hits = _as_mapping(base["terminal_state"]).get("playbook_hits")
    sm4 = evaluate_retrieval(scenario)["sm4"]
    assert isinstance(sm4, dict)
    assert sm4["n_hits"] == len(spine_hits if isinstance(spine_hits, list) else []), (
        f"{scenario.name}: SM-4 n_hits must equal the REAL spine playbook_hits count (R3)"
    )


# ---------------------------------------------------------------------------
# The SM-4 MECHANISM — recall TEETH on CONTROLLED synthetic hits + the synthetic ground-truth map (R3).
#
# The baseline (above) is empty because the corpus is absent. These prove the instrument has TEETH: on
# CONTROLLED synthetic hits it computes a measurable recall (full / partial / zero). The synthetic map is a
# clearly-labeled TEST FIXTURE (R3) — never substituted into the real baseline.
# ---------------------------------------------------------------------------


def test_sm4_recall_teeth_full_recall() -> None:
    """R3 teeth: all expected playbooks retrieved → recall 1.0 (the instrument FIRES, not always-zero)."""
    expected = _SYNTHETIC_PLAYBOOK_MAP["DependencyTimeout"]
    sm4 = sm4_retrieval(_synthetic_hits(*expected), expected_ids=expected)
    assert sm4["status"] == "ok"
    assert sm4["recall"] == pytest.approx(1.0)
    assert sm4["n_relevant"] == sm4["n_expected"] == len(expected)


def test_sm4_recall_teeth_partial_recall() -> None:
    """R3 teeth: HALF the expected retrieved → recall 0.5 (graded, NOT all-or-nothing)."""
    expected = _SYNTHETIC_PLAYBOOK_MAP["OOMKilled"]  # 2 expected
    sm4 = sm4_retrieval(_synthetic_hits("pb-oom-resource-limit"), expected_ids=expected)  # 1 of 2
    assert sm4["recall"] == pytest.approx(0.5)
    assert sm4["n_relevant"] == 1
    assert sm4["n_expected"] == 2


def test_sm4_recall_teeth_zero_recall() -> None:
    """R3 teeth: NONE relevant retrieved → recall 0.0 (the empty-recall case fires on populated hits too)."""
    expected = _SYNTHETIC_PLAYBOOK_MAP["CrashLoopBackOff"]
    sm4 = sm4_retrieval(_synthetic_hits("pb-totally-unrelated"), expected_ids=expected)
    assert sm4["recall"] == pytest.approx(0.0)
    assert sm4["n_relevant"] == 0
    assert sm4["n_expected"] == len(expected)


def test_sm4_recall_vacuous_when_no_expected() -> None:
    """``expected_ids`` empty → recall 1.0 (vacuous truth — mirrors ``coverage_fraction`` / ``all([])``)."""
    sm4 = sm4_retrieval(_synthetic_hits("pb-x"), expected_ids=frozenset())
    assert sm4["recall"] == pytest.approx(1.0)
    assert sm4["n_expected"] == 0


def test_sm4_baseline_mode_never_substitutes_a_ground_truth_map() -> None:
    """R3: the real baseline (``expected_ids=None``) NEVER substitutes a synthetic map → recall blocked.

    The synthetic ground-truth map is a TEETH fixture (above) — the baseline reports the honest EMPTY/
    DEGRADED state (recall ``None``), never a fabricated recall against a synthesized map.
    """
    sm4 = sm4_retrieval([], expected_ids=None)
    assert sm4["recall"] is None
    assert sm4["n_expected"] is None
    assert sm4["status"] == "empty-degraded"


# ---------------------------------------------------------------------------
# SM-4 is a SEPARATE column (R2) — never folded into SM-1, never reported as a pass.
# ---------------------------------------------------------------------------


def test_sm4_is_a_separate_column_not_folded_into_sm1() -> None:
    """R2: the retrieval blob carries the ``sm4`` column but NOT the SM-1 conjunction surface.

    Each per-scenario row has ``sm4`` but NOT ``conditions`` / ``pass`` / ``binary_conditions`` (the SM-1
    surface lives in the 6.2 conjunction blob, a SEPARATE axis). SM-4 is never folded into correctness,
    never averaged with the conjunction, never reported as a pass (R2 — AC6 "KHÔNG trộn vào correctness").
    """
    row = json.loads(retrieval_blob())["per_scenario"][0]
    assert "sm4" in row  # the SM-4 column is present
    for sm1_key in ("conditions", "pass", "binary_conditions", "binary_pass"):
        assert sm1_key not in row, (
            f"R2: the SM-1 surface {sm1_key!r} must NOT be in the SM-4 column (separate axis — not folded)"
        )


def test_sm4_additive_does_not_touch_the_sm1_baseline() -> None:
    """R1: 6.4 is ADDITIVE — the 6.2 SM-1 correctness baseline is UNCHANGED (still 0% — 5-A1).

    ``retrieval_harness`` does not edit ``conjunction_harness`` / ``scoring_harness``; the SM-1 headline
    (``evaluate_scenario(s)['pass']``) is still ``False`` (the graph does not converge — 5-A1), independent
    of the new SM-4 column. The columns coexist; neither contaminates the other.
    """
    assert evaluate_scenario(DEPENDENCY_TIMEOUT)["pass"] is False  # SM-1 still 0% (unchanged — R1)


# ---------------------------------------------------------------------------
# Q8 (FR-10) — DETERMINISTIC train/eval partition: leak-free + complete + calibration-moot.
# ---------------------------------------------------------------------------


def test_q8_partition_is_leak_free_and_complete() -> None:
    """Q8 MECHANISM: train ∩ eval = ∅ AND train ∪ eval = all 11 (leak-free — no feedback-loop bias).

    The leak-free invariant (the Q8 gate assertion): no scenario is in both sets, and every scenario is in
    one. This is the anti-feedback-loop-bias guarantee (calibrate-on-train, eval-on-eval — no overlap).
    """
    split = q8_split()
    assert split["leak_free"] is True
    train_names = split["train_names"]
    eval_names = split["eval_names"]
    assert isinstance(train_names, list) and isinstance(eval_names, list)
    train = set(train_names)
    eval_ = set(eval_names)
    assert train.isdisjoint(eval_)  # no scenario in both sets
    all_names = {s.name for s in BENCHMARK_SCENARIOS}
    assert train | eval_ == all_names  # every scenario in exactly one set
    assert split["n_total"] == len(BENCHMARK_SCENARIOS) == 11
    n_train = split["n_train"]
    n_eval = split["n_eval"]
    assert isinstance(n_train, int) and isinstance(n_eval, int)
    assert n_train + n_eval == 11


def test_q8_partition_is_deterministic_index_based() -> None:
    """Q8 is DETERMINISTIC: index-based over the FROZEN tuple → identical partition across calls (AD-12).

    No LLM, no clock/random/IO, no ``hash()`` on strings. The frozen ``BENCHMARK_SCENARIOS`` tuple order →
    the index partition is byte-stable. (The decisive cross-``PYTHONHASHSEED`` proof is gate #6.)
    """
    first = q8_split()
    second = q8_split()
    assert first == second  # pure function of the frozen tuple (deterministic)
    # The frozen-index default partition (8 train = indices 0-7 / 3 eval = indices 8-10). This is the
    # DOCUMENTED POC default; the specific RATIO is D4-deferred (NOT tuned, NOT a gate threshold — R2).
    assert first["train_names"] == [
        "certificate_expired",
        "dependency_timeout",
        "disk_pressure",
        "dns_failure",
        "inventory_reserve_failure",
        "latency_spike",
        "memory_leak",
        "payment_failure",
    ]
    assert first["eval_names"] == ["bad_deployment_config", "crashloop", "oom"]


def test_q8_calibration_is_moot_and_ratio_deferred() -> None:
    """Q8 discipline: calibration is MOOT pre-convergence (no reports) + the ratio is D4-DEFERRED.

    The partition MECHANISM is locked (leak-free + deterministic); the calibration is ``"moot-no-reports"``
    (no report to calibrate D3 floor / D4 cutoff on train — 5-A1) + ``split_ratio_status="d4-deferred"`` (the
    gate asserts leak-free + deterministic, NOT a specific ratio NOR a retrieval PASS — R2).
    """
    split = q8_split()
    assert (
        split["calibration"] == "moot-no-reports"
    )  # no reports pre-convergence → calibration moot
    assert split["split_ratio_status"] == "d4-deferred"  # the ratio is NOT locked/asserted (D4)


def test_q8_partition_custom_indices_remain_leak_free() -> None:
    """Q8 mechanism is GENERAL: a custom ``train_indices`` still produces a leak-free partition.

    The mechanism (a frozenset of indices over the frozen tuple → complement = eval) holds for any valid
    index set. This proves the mechanism is the LOCKED part; the 8/3 default is just one application (D4).
    """
    split = q8_split(train_indices=(2, 4, 6, 8, 10))  # a different (odd-indexed) partition
    assert split["leak_free"] is True
    assert split["n_train"] == 5
    assert split["n_eval"] == 6
    train_names = split["train_names"]
    eval_names = split["eval_names"]
    assert isinstance(train_names, list) and isinstance(eval_names, list)
    assert set(train_names).isdisjoint(set(eval_names))


# ---------------------------------------------------------------------------
# Determinism prerequisite + blob shape (the decisive cross-PYTHONHASHSEED proof is gate #6).
# ---------------------------------------------------------------------------


def test_retrieval_blob_is_valid_json_with_axes_and_eleven_rows() -> None:
    """The blob is canonical JSON: ``sm4`` overview + ``q8`` partition + 11 per-scenario SM-4 rows."""
    blob = json.loads(retrieval_blob())
    assert set(blob.keys()) >= {"max_iterations", "sm4", "q8", "per_scenario"}
    assert len(blob["per_scenario"]) == 11
    for row in blob["per_scenario"]:
        assert set(row.keys()) == {"name", "canonical_trigger", "sm4"}, (
            f"each SM-4 row must carry exactly {{name, canonical_trigger, sm4}} (separate column — R2); "
            f"got {set(row.keys())}"
        )
        sm4 = row["sm4"]
        assert sm4["status"] == "empty-degraded"
        assert sm4["n_hits"] == 0
        assert sm4["recall"] is None
    assert blob["sm4"]["n_empty"] == 11
    assert blob["q8"]["leak_free"] is True


def test_retrieval_blob_is_within_process_deterministic() -> None:
    """Determinism prerequisite: same scenarios → byte-identical retrieval blob across runs (AD-12).

    The decisive cross-``PYTHONHASHSEED`` proof is gate #6; this asserts the in-process prerequisite (the
    blob is a pure function of the scenarios — SM-4 = membership counts, Q8 = sorted partition lists; no
    hash-ordered structure leaks into the canonical-JSON blob).
    """
    blobs = [retrieval_blob() for _ in range(3)]
    assert len(set(blobs)) == 1, (
        "the retrieval blob is non-deterministic in-process (AD-12 violation)"
    )
