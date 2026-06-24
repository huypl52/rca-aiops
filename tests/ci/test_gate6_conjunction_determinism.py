"""CI gate #6 — Story 6.2 conjunction DETERMINISM self-test (AD-13 #6 / FR-10 / NFR-Determinism).

Extends gate #6 to the Story-6.2 axis: driving the **FULL compiled §3.5 graph** over each of the 11 §3.7
scenarios (via :func:`build_default_compiled_runner`'s ``adapter`` seam wired to a
``ScenarioTransport``-backed adapter) produces a byte-identical **conjunction blob** (SM-1 + SM-2 +
per-scenario terminal state) ACROSS ``PYTHONHASHSEED`` values. This is the §2F make-or-break: a single
process fixes ``PYTHONHASHSEED``, so only spawning subprocesses under several seeds truly proves the FULL
graph run (inject → terminal-state → SM-1) is hash-seed-independent.

**§2F VERDICT (the make-or-break risk — PROVEN EARLY in DS):** the conjunction blob IS byte-stable across
seeds. The compiled graph's spine is built from insertion-ordered dicts + list-ordered collections (the
HYP↔VAL loop is deterministic: insertion-ordered hypothesis dicts, deterministic ``min`` promotion, the
VAL ``seen`` set is dedupe-only — never iterated into output). No hash-order leak reaches the spine → the
blob is byte-identical across ``PYTHONHASHSEED={0,1,42}``.

**GATE #6 BOUNDARY (6.2 extends the axis — honest, NOT a silent green lie):** gate #6 at 6.2 asserts the
conjunction axis is REAL + DETERMINISTIC — it asserts the blob is byte-stable across seeds. It does NOT
assert ``SM-1 ≥ threshold`` (D4 — confidence/SM cutoffs defer) NOR that the agent PASSES the conjunction
(the honest baseline is SM-1 = 0% — the graph does not converge, 5-A1; fixing that is a SEPARATE story,
R1). A GREEN gate #6 at 6.2 means "the full-agent conjunction runs + is deterministic" — NOT "the agent
passes". The scoring PASS is a future-convergence matter, gated honestly here as determinism-only.

Negative test (mirrors the 6.1 gate#5/gate#6 FAIL-on-drift discipline): the harness
``EVAL_GATE6_NEGATIVE`` hook deliberately makes the conjunction blob hash-seed-DEPENDENT (set-iteration
order) → the cross-seed blobs DIFFER → proving the determinism assertion has teeth (not tautological).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]  # tests/ci/<this> -> repo root
HARNESS_MODULE = "tests.conjunction_harness"

# PYTHONHASHSEED values spanning the determinism axis (0/1 fixed + a larger int). If any step of the FULL
# graph run depended on string-hash ordering, these would diverge.
_HASH_SEEDS_POSITIVE: tuple[str, ...] = ("0", "1", "42")
_HASH_SEEDS_NEGATIVE: tuple[str, ...] = ("0", "1")


def _run_harness(*, hash_seed: str, negative: bool = False) -> str:
    """Run ``python -m tests.conjunction_harness`` under ``PYTHONHASHSEED``; return its stdout blob.

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
# Positive — gate #6 conjunction determinism: full-graph run → byte-stable blob cross-PYTHONHASHSEED.
# ---------------------------------------------------------------------------


def test_gate6_conjunction_blob_is_valid_json_with_eleven_scenarios() -> None:
    """The harness emits a canonical-JSON conjunction blob carrying SM-1 + SM-2 + 11 per-scenario rows."""
    blob = json.loads(_run_harness(hash_seed="0"))
    assert isinstance(blob, dict)
    assert set(blob.keys()) >= {"max_iterations", "sm1", "sm2", "per_scenario"}
    assert len(blob["per_scenario"]) == 11


def test_gate6_full_graph_conjunction_is_byte_stable_across_pythonhashseed() -> None:
    """DECISIVE (§2F): same 11 scenarios → byte-IDENTICAL conjunction blob across PYTHONHASHSEED values.

    Gate #6 conjunction-determinism axis (AD-13 #6 / NFR-Determinism / §2F). If any step of the FULL
    compiled-graph run (inject → ICB → PBR → HYP↔VAL → ... → terminal-state → SM-1/SM-2) depended on
    string-hash ordering, the blobs would diverge here. The terminal_state per scenario is the payload —
    byte-stability proves the WHOLE spine is hash-seed-stable.
    """
    blobs = [_run_harness(hash_seed=seed) for seed in _HASH_SEEDS_POSITIVE]
    assert len(set(blobs)) == 1, (
        "gate #6 §2F DETERMINISM VIOLATION: the full-graph conjunction blob is NOT byte-stable "
        f"across PYTHONHASHSEED={_HASH_SEEDS_POSITIVE} (AD-12 / NFR-Determinism) — a hash-order leak "
        "reaches the spine."
    )


# ---------------------------------------------------------------------------
# Negative — the determinism assertion has teeth (mirrors gate#5/gate#6 FAIL-on-drift discipline).
# ---------------------------------------------------------------------------


def test_gate6_conjunction_assertion_catches_non_determinism() -> None:
    """A deliberately hash-seed-DEPENDENT blob DIFFERS across seeds → the gate is not tautological.

    With ``EVAL_GATE6_NEGATIVE=1`` the harness weaves set-iteration order (PYTHONHASHSEED-dependent) into
    the blob. The positive assertion (``len(set(blobs)) == 1``) would FAIL on these — proving the gate
    genuinely catches non-determinism rather than always passing.
    """
    blobs = [_run_harness(hash_seed=seed, negative=True) for seed in _HASH_SEEDS_NEGATIVE]
    assert len(set(blobs)) > 1, (
        "gate #6 conjunction negative control failed: the deliberately non-deterministic blob did NOT "
        "vary across PYTHONHASHSEED — the determinism assertion would be tautological."
    )
