"""CI gate #6 — Story 6.4 playbook-retrieval (SM-4) + train/eval-split (Q8) DETERMINISM self-test
(AD-13 #6 / FR-10 / NFR-Determinism).

Extends gate #6 to the Story-6.4 axis: the **PLAYBOOK-RETRIEVAL INDEPENDENT AXIS (SM-4 / FR-10e / A6) +
the TRAIN/EVAL SPLIT (Q8 / FR-10)** — TWO new independent columns ABOVE the 6.1/6.2/6.3 baselines — computed
over each of the 11 §3.7 scenarios produces a byte-identical **retrieval blob** ACROSS ``PYTHONHASHSEED``
values. This is the §2C make-or-break: a single process fixes ``PYTHONHASHSEED``, so only spawning
subprocesses under several seeds truly proves the SM-4 + Q8 computation is hash-seed-independent.

**§2C VERDICT (the make-or-break risk — PROVEN EARLY in DS):** the retrieval blob IS byte-stable across
seeds. The 6.4 axes are hash-seed-independent by construction: SM-4 = set-membership counts (``in`` checks —
order-independent) + an ``int`` hit count + a ``float`` recall (``None`` on the empty baseline); Q8 = an
index-based partition over the FROZEN scenario tuple (the partition sets are SORTED before serialization →
no hash-order leak; the leak-free ``isdisjoint`` / union checks are order-independent). The blob is
canonical JSON (``sort_keys=True``). No hash-order leak reaches the blob → byte-identical across
``PYTHONHASHSEED={0,1,42}``.

**GATE #6 BOUNDARY (6.4 extends the axis — honest, NOT a silent green lie):** gate #6 at 6.4 asserts the
SM-4 + Q8 axes are REAL + DETERMINISTIC — it asserts the blob is byte-stable across seeds AND the Q8
partition is leak-free. It does NOT assert ``SM-4 recall ≥ threshold`` NOR a specific split ratio NOR a
retrieval PASS (D4 — retrieval cutoffs + the ratio defer). A GREEN gate #6 at 6.4 means "the SM-4
retrieval axis + the Q8 partition RUN + are deterministic" — NOT "the agent retrieves playbooks" or "the
split is tuned". The honest baseline is SM-4 ``status="blocked-empty-retrieval"`` (``playbook_hits=[]``
11/11 — the retriever is wired but the Qdrant corpus is absent, 5-A1-family; R1: do NOT add retrieval
content), Q8 ``leak_free=True`` / ``calibration="moot-no-reports"`` (pre-convergence — no reports to
calibrate D3/D4 on — 5-A1). The retrieval PASS + cutoffs are NOT asserted here (R2 — SM-4 is a SEPARATE
independent column, never a back-door pass; the ratio is D4-deferred).

Negative test (mirrors the 6.1/6.2/6.3 gate#6 FAIL-on-drift discipline): the harness ``EVAL_GATE6_NEGATIVE``
hook deliberately makes the retrieval blob hash-seed-DEPENDENT (set-iteration order) → the cross-seed blobs
DIFFER → proving the determinism assertion has teeth (not tautological).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]  # tests/ci/<this> -> repo root
HARNESS_MODULE = "tests.retrieval_harness"

# PYTHONHASHSEED values spanning the determinism axis (0/1 fixed + a larger int). If any step of the SM-4
# + Q8 computation depended on string-hash ordering, these would diverge.
_HASH_SEEDS_POSITIVE: tuple[str, ...] = ("0", "1", "42")
_HASH_SEEDS_NEGATIVE: tuple[str, ...] = ("0", "1")


def _run_harness(*, hash_seed: str, negative: bool = False) -> str:
    """Run ``python -m tests.retrieval_harness`` under ``PYTHONHASHSEED``; return its stdout blob.

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
# Positive — gate #6 retrieval determinism: SM-4 + Q8 → byte-stable blob cross-PYTHONHASHSEED.
# ---------------------------------------------------------------------------


def test_gate6_retrieval_blob_is_valid_json_with_axes_and_eleven_rows() -> None:
    """The harness emits a canonical-JSON retrieval blob carrying the SM-4 overview + Q8 partition + 11 rows."""
    blob = json.loads(_run_harness(hash_seed="0"))
    assert isinstance(blob, dict)
    assert set(blob.keys()) >= {"max_iterations", "sm4", "q8", "per_scenario"}
    assert len(blob["per_scenario"]) == 11
    assert (
        blob["q8"]["leak_free"] is True
    )  # the Q8 leak-free invariant holds on the blob payload too


def test_gate6_retrieval_blob_is_byte_stable_across_pythonhashseed() -> None:
    """DECISIVE (§2C): same 11 scenarios → byte-IDENTICAL retrieval blob across PYTHONHASHSEED values.

    Gate #6 retrieval-determinism axis (AD-13 #6 / NFR-Determinism / §2C). If any step of the SM-4 + Q8
    computation (SM-4 membership counts / recall, Q8 index partition / sorted partition lists / leak-free
    checks) depended on string-hash ordering, the blobs would diverge here. Each per-scenario row carries the
    SM-4 reading of the REAL ``playbook_hits`` (the actual PBR output — R3), and the blob carries the Q8
    partition — the FULL 6.4 payload — so byte-stability proves the WHOLE SM-4 + Q8 computation is
    hash-seed-stable.
    """
    blobs = [_run_harness(hash_seed=seed) for seed in _HASH_SEEDS_POSITIVE]
    assert len(set(blobs)) == 1, (
        "gate #6 §2C DETERMINISM VIOLATION: the retrieval (SM-4 + Q8) blob is NOT byte-stable across "
        f"PYTHONHASHSEED={_HASH_SEEDS_POSITIVE} (AD-12 / NFR-Determinism) — a hash-order leak reaches the "
        "blob (SM-4 membership counts, SM-4 recall, or the Q8 partition is non-deterministic)."
    )


# ---------------------------------------------------------------------------
# Negative — the determinism assertion has teeth (mirrors gate#5/gate#6 FAIL-on-drift discipline).
# ---------------------------------------------------------------------------


def test_gate6_retrieval_assertion_catches_non_determinism() -> None:
    """A deliberately hash-seed-DEPENDENT blob DIFFERS across seeds → the gate is not tautological.

    With ``EVAL_GATE6_NEGATIVE=1`` the harness weaves set-iteration order (PYTHONHASHSEED-dependent) into the
    blob. The positive assertion (``len(set(blobs)) == 1``) would FAIL on these — proving the gate genuinely
    catches non-determinism rather than always passing.
    """
    blobs = [_run_harness(hash_seed=seed, negative=True) for seed in _HASH_SEEDS_NEGATIVE]
    assert len(set(blobs)) > 1, (
        "gate #6 retrieval negative control failed: the deliberately non-deterministic blob did NOT vary "
        "across PYTHONHASHSEED — the determinism assertion would be tautological."
    )
