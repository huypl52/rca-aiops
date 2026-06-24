"""CI gate #6 — Story 6.3 graded-scoring DETERMINISM self-test (AD-13 #6 / FR-10 / NFR-Determinism).

Extends gate #6 to the Story-6.3 axis: the **GRADED SCORING LAYER ABOVE the 6.2 binary conjunction**
(partial-credit ``coverage_{a..e}`` floats + tolerance window + anti-hallucination SM-3) computed over each of
the 11 §3.7 scenarios produces a byte-identical **scoring blob** ACROSS ``PYTHONHASHSEED`` values. This is the
§2D make-or-break: a single process fixes ``PYTHONHASHSEED``, so only spawning subprocesses under several seeds
truly proves the graded + SM-3 + tolerance computation is hash-seed-independent.

**§2D VERDICT (the make-or-break risk — PROVEN EARLY in DS):** the scoring blob IS byte-stable across seeds.
The graded axes are hash-seed-independent by construction: ``coverage`` = set-membership fractions (``in``
checks — order-independent), SM-3 = token-membership containment (sets used for membership only, NEVER
serialized into the blob), tolerance = ``abs()`` arithmetic. The blob is canonical JSON (``sort_keys=True``).
No hash-order leak reaches the blob → byte-identical across ``PYTHONHASHSEED={0,1,42}``.

**GATE #6 BOUNDARY (6.3 extends the axis — honest, NOT a silent green lie):** gate #6 at 6.3 asserts the
graded scoring axis is REAL + DETERMINISTIC — it asserts the blob is byte-stable across seeds. It does NOT
assert ``coverage ≥ threshold`` NOR ``SM-3 ≥ threshold`` NOR a tolerance PASS (D4 — confidence/SM/tolerance
cutoffs defer). A GREEN gate #6 at 6.3 means "the graded coverage + tolerance + SM-3 axes RUN + are
deterministic" — NOT "the agent achieves a grade". The honest baseline is ``coverage = {a≈1.0, b=1.0, c=0.0,
d=0.0, e=0.0}`` (the graph does not converge, 5-A1; the binary SM-1 = 0% headline is PRESERVED — R1), SM-3
evidence-layer 100% (the pipeline), SM-3 report-layer ``blocked`` (no report). The graded PASS + cutoffs are
NOT asserted here (R2 — partial-credit is a SEPARATE supplementary axis, never a back-door pass).

Negative test (mirrors the 6.1/6.2 gate#6 FAIL-on-drift discipline): the harness ``EVAL_GATE6_NEGATIVE`` hook
deliberately makes the scoring blob hash-seed-DEPENDENT (set-iteration order) → the cross-seed blobs DIFFER →
proving the determinism assertion has teeth (not tautological).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]  # tests/ci/<this> -> repo root
HARNESS_MODULE = "tests.scoring_harness"

# PYTHONHASHSEED values spanning the determinism axis (0/1 fixed + a larger int). If any step of the graded +
# SM-3 + tolerance computation depended on string-hash ordering, these would diverge.
_HASH_SEEDS_POSITIVE: tuple[str, ...] = ("0", "1", "42")
_HASH_SEEDS_NEGATIVE: tuple[str, ...] = ("0", "1")


def _run_harness(*, hash_seed: str, negative: bool = False) -> str:
    """Run ``python -m tests.scoring_harness`` under ``PYTHONHASHSEED``; return its stdout blob.

    ``negative=True`` sets ``EVAL_GATE6_NEGATIVE=1`` so the harness emits a deliberately hash-seed-dependent
    blob (set-iteration order) for the negative test.
    """
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = hash_seed
    env["PYTHONPATH"] = str(REPO_ROOT)
    if negative:
        env["EVAL_GATE6_NEGATIVE"] = "1"
    else:
        env.pop("EVAL_GATE6_NEGATIVE", None)
    result = subprocess.run(
        [sys.executable, "-m", HARNESS_MODULE],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=env,
        check=True,
    )
    assert result.stderr == "", f"harness emitted stderr under seed={hash_seed}: {result.stderr}"
    return result.stdout


# ---------------------------------------------------------------------------
# Positive — gate #6 scoring determinism: graded+SM-3+tolerance → byte-stable blob cross-PYTHONHASHSEED.
# ---------------------------------------------------------------------------


def test_gate6_scoring_blob_is_valid_json_with_eleven_rows_and_overview() -> None:
    """The harness emits a canonical-JSON scoring blob carrying the overview + 11 per-scenario graded rows."""
    blob = json.loads(_run_harness(hash_seed="0"))
    assert isinstance(blob, dict)
    assert set(blob.keys()) >= {"max_iterations", "overview", "per_scenario"}
    assert len(blob["per_scenario"]) == 11


def test_gate6_scoring_blob_is_byte_stable_across_pythonhashseed() -> None:
    """DECISIVE (§2D): same 11 scenarios → byte-IDENTICAL scoring blob across PYTHONHASHSEED values.

    Gate #6 scoring-determinism axis (AD-13 #6 / NFR-Determinism / §2D). If any step of the graded + SM-3 +
    tolerance computation (coverage membership-fractions, SM-3 token-containment, tolerance ``abs()``) depended
    on string-hash ordering, the blobs would diverge here. Each per-scenario row carries the binary conditions
    (preserved SM-1 headline), graded ``coverage``, ``sm3_evidence``/``sm3_report``, and ``tolerance`` — the
    FULL graded payload — so byte-stability proves the WHOLE graded computation is hash-seed-stable.
    """
    blobs = [_run_harness(hash_seed=seed) for seed in _HASH_SEEDS_POSITIVE]
    assert len(set(blobs)) == 1, (
        "gate #6 §2D DETERMINISM VIOLATION: the graded scoring blob is NOT byte-stable across "
        f"PYTHONHASHSEED={_HASH_SEEDS_POSITIVE} (AD-12 / NFR-Determinism) — a hash-order leak reaches the "
        "blob (coverage fractions, SM-3 token containment, or tolerance arithmetic is non-deterministic)."
    )


# ---------------------------------------------------------------------------
# Negative — the determinism assertion has teeth (mirrors gate#5/gate#6 FAIL-on-drift discipline).
# ---------------------------------------------------------------------------


def test_gate6_scoring_assertion_catches_non_determinism() -> None:
    """A deliberately hash-seed-DEPENDENT blob DIFFERS across seeds → the gate is not tautological.

    With ``EVAL_GATE6_NEGATIVE=1`` the harness weaves set-iteration order (PYTHONHASHSEED-dependent) into the
    blob. The positive assertion (``len(set(blobs)) == 1``) would FAIL on these — proving the gate genuinely
    catches non-determinism rather than always passing.
    """
    blobs = [_run_harness(hash_seed=seed, negative=True) for seed in _HASH_SEEDS_NEGATIVE]
    assert len(set(blobs)) > 1, (
        "gate #6 scoring negative control failed: the deliberately non-deterministic blob did NOT vary "
        "across PYTHONHASHSEED — the determinism assertion would be tautological."
    )
