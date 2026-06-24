"""CI gate #6 — benchmark DETERMINISM self-test (Story 6.1 — AD-13 #6 / FR-10 / NFR-Determinism).

Asserts the Story-6.1 DETERMINISM axis is REAL: driving each of the 11 §3.7 scenarios' canned inject
through the REAL adapter + the REAL evidence_normalizer produces a byte-identical Evidence symptom
ACROSS ``PYTHONHASHSEED`` values. This is the decisive cross-process proof (within a single process
``PYTHONHASHSEED`` is fixed, so only spawning subprocesses under several seeds truly proves the
inject → symptom map is hash-seed-independent — §3.7 "inject → symptom ổn định" / NFR-Determinism).

**GATE #6 BOUNDARY (honest — NOT a silent green lie):** at Story 6.1 gate #6 asserts ONLY the
determinism axis. The SCORING axes are deliberately DEFERRED to later Epic-6 stories and are NOT
asserted here:

  - binary conjunction (inject→symptom ∧ trigger-right ∧ tools-right ∧ evidence-matches-ground-truth
    ∧ report-right-root-cause) → Story 6.2,
  - partial-credit + tolerance window (ON the conjunction, non-deterministic metrics) → Story 6.3,
  - anti-hallucination raw-vs-summary (SM-3) → Story 6.3,
  - playbook-retrieval independent axis (SM-4) → Story 6.4.

So a GREEN gate #6 at 6.1 means "the 11-scenario inject is deterministic" — it does NOT mean "the
agent passes the benchmark scoring". This mirrors the Story-6.1 gate#6 placeholder
(``.github/workflows/ci.yml``) being narrowed from a TODO echo to a REAL determinism assertion, with
the scoring TODOs carried explicitly into 6.2/6.3/6.4 (the 4-A3 pattern: keep the axis real here,
defer the rest with an honest narrowed scope).

Negative test (mirrors gate#5's FAIL-on-drift discipline): the harness ``EVAL_GATE6_NEGATIVE`` hook
deliberately makes the symptom blob hash-seed-DEPENDENT (set-iteration order) → the cross-seed blobs
DIFFER → proving the determinism assertion has teeth (it is not a tautological always-pass).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]  # tests/ci/<this> -> repo root
HARNESS_MODULE = "tests.eval_harness"

# PYTHONHASHSEED values spanning the determinism axis (0/1 fixed + a larger int). If any step of the
# inject → Evidence pipeline depended on string-hash ordering, these would diverge.
_HASH_SEEDS_POSITIVE: tuple[str, ...] = ("0", "1", "42")
_HASH_SEEDS_NEGATIVE: tuple[str, ...] = ("0", "1")


def _run_harness(*, hash_seed: str, negative: bool = False) -> str:
    """Run ``python -m tests.eval_harness`` under ``PYTHONHASHSEED=hash_seed``; return its stdout blob.

    ``negative=True`` sets ``EVAL_GATE6_NEGATIVE=1`` so the harness emits a deliberately
    hash-seed-dependent blob (set-iteration order) for the negative test.
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
# Positive — gate #6 determinism axis: 11-scenario inject → byte-stable symptom cross-PYTHONHASHSEED.
# ---------------------------------------------------------------------------


def test_gate6_symptom_blob_is_valid_json_with_eleven_scenarios() -> None:
    """The harness emits a canonical-JSON blob carrying one symptom per §3.7 scenario."""
    blob = _run_harness(hash_seed="0")
    parsed = json.loads(blob)
    assert isinstance(parsed, dict)
    expected_names = {
        "dependency_timeout",
        "payment_failure",
        "latency_spike",
        "disk_pressure",
        "memory_leak",
        "inventory_reserve_failure",
        "dns_failure",
        "certificate_expired",
        "crashloop",
        "oom",
        "bad_deployment_config",
    }
    assert set(parsed.keys()) == expected_names
    for name, symptom in parsed.items():
        assert isinstance(symptom, str) and symptom, f"scenario {name!r} has an empty symptom"
        json.loads(symptom)  # each symptom is itself canonical JSON (Evidence list)


def test_gate6_inject_to_symptom_is_byte_stable_across_pythonhashseed() -> None:
    """DECISIVE: same 11-scenario inject → byte-IDENTICAL symptom blob across PYTHONHASHSEED values.

    Gate #6 determinism axis (AD-13 #6 / NFR-Determinism / §3.7 "inject → symptom ổn định"). If any
    step of the inject → REAL adapter → REAL evidence_normalizer pipeline depended on string-hash
    ordering, the blobs would diverge here.
    """
    blobs = [_run_harness(hash_seed=seed) for seed in _HASH_SEEDS_POSITIVE]
    assert len(set(blobs)) == 1, (
        "gate #6 DETERMINISM VIOLATION: the 11-scenario inject → symptom blob is NOT byte-stable "
        f"across PYTHONHASHSEED={_HASH_SEEDS_POSITIVE} (AD-12 / NFR-Determinism)."
    )


# ---------------------------------------------------------------------------
# Negative — the determinism assertion has teeth (mirrors gate#5 FAIL-on-drift discipline).
# ---------------------------------------------------------------------------


def test_gate6_assertion_catches_non_determinism() -> None:
    """A deliberately hash-seed-DEPENDENT blob DIFFERS across seeds → the gate is not tautological.

    With ``EVAL_GATE6_NEGATIVE=1`` the harness weaves set-iteration order (PYTHONHASHSEED-dependent)
    into the blob. The positive assertion (``len(set(blobs)) == 1``) would FAIL on these — proving
    the gate genuinely catches non-determinism rather than always passing.
    """
    blobs = [_run_harness(hash_seed=seed, negative=True) for seed in _HASH_SEEDS_NEGATIVE]
    assert len(set(blobs)) > 1, (
        "gate #6 negative control failed: the deliberately non-deterministic blob did NOT vary "
        "across PYTHONHASHSEED — the determinism assertion would be tautological."
    )
