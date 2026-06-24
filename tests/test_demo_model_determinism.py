"""Story 7.1 — the demo healthy baseline is BYTE-STABLE across PYTHONHASHSEED.

This is the demo-system analog of CI gate #6 §2C: the make-or-break pipeline ::

    render_prometheus(replay_trace(generate_trace(seed, n)))

must be byte-identical across ``PYTHONHASHSEED={0,1,42}``. AD-12 (determinism) is
extended to the demo system: the same healthy baseline must be reproducible
run-to-run so Story 7.3's chaos inject produces reproducible symptoms.

We prove it cross-PROCESS: spawn ``python -m demo.model`` under several hash seeds and
assert every subprocess output equals the in-process reference (and each other). A leak
(any unsorted dict/set iteration, any ``hash()``-on-strings) would show up as a divergence.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from demo.model import DEFAULT_SEED, generate_trace, healthy_blob, render_prometheus, replay_trace

REPO_ROOT = Path(__file__).resolve().parents[1]

#: The hash seeds the baseline must be stable across (PYTHONHASHSEED randomizes str/int
#: hashing; the model must not depend on it).
HASH_SEEDS: tuple[str, ...] = ("0", "1", "42")


def _run_model_cli(seed: int, hash_seed: str) -> str:
    """Spawn ``python -m demo.model <seed>`` under ``PYTHONHASHSEED=hash_seed``."""
    env = {**os.environ, "PYTHONHASHSEED": hash_seed, "PYTHONPATH": str(REPO_ROOT)}
    result = subprocess.run(
        [sys.executable, "-m", "demo.model", str(seed)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
        check=False,
    )
    assert result.returncode == 0, (
        f"`demo.model` failed under PYTHONHASHSEED={hash_seed}:\n{result.stderr}"
    )
    return result.stdout


def test_generate_trace_is_pure_and_reproducible() -> None:
    first = generate_trace(seed=DEFAULT_SEED, n=200)
    second = generate_trace(seed=DEFAULT_SEED, n=200)
    assert first == second  # PURE: same (seed, n) → identical trace
    assert len(first) == 200
    assert all(step.seq == i for i, step in enumerate(first))


def test_replay_render_is_in_process_stable() -> None:
    blob_a = render_prometheus(replay_trace(generate_trace(seed=DEFAULT_SEED, n=200)))
    blob_b = render_prometheus(replay_trace(generate_trace(seed=DEFAULT_SEED, n=200)))
    assert blob_a == blob_b
    # the healthy baseline carries all 5 services.
    for svc in ("api-gateway", "user", "order", "inventory", "payment"):
        assert f'service="{svc}"' in blob_a


def test_healthy_baseline_byte_stable_across_hash_seeds() -> None:
    # The in-process reference runs under whatever PYTHONHASHSEED pytest has; the claim
    # is it is hash-seed-INDEPENDENT, so it must equal every cross-process output.
    reference = healthy_blob(seed=DEFAULT_SEED)
    outputs = {hs: _run_model_cli(DEFAULT_SEED, hs) for hs in HASH_SEEDS}
    for hs, output in outputs.items():
        assert output == reference, f"PYTHONHASHSEED={hs} diverged from the reference baseline"
    assert len(set(outputs.values())) == 1  # all three subprocess outputs agree
