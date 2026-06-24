"""Story 7-4 — durable checkpoint (AD-11) + cross-restart resume (AD-10 #4).

Proves the MECHANISM that Story 1-4 honestly deferred (its AC6: "in-process only; no
LangGraph checkpointer"). Three ACs:

  - AC1 — ``AsyncSqliteSaver`` FILE checkpoint persists across process restart. The
    investigation state (full 13-key spine) survives a conn close (process death) + a
    FRESH store reopen over the SAME file: the trigger is recoverable + the investigation
    is still INCOMPLETE (not at graph END).
  - AC2 — startup dispatcher resume. On restart, ``resume_incomplete`` scans the durable
    store for incomplete investigations + resumes each at-least-once (idempotent on
    ``investigation_id``; safe because the investigation is read-only — no double-apply).
  - boundary — the checkpoint WRITE is a LOCAL sqlite file (the agent's OWN state, AD-11),
    NOT a read-only-investigator violation (AD-3 forbids writing to the SUT via
    tools/adapters; this is wired at graph/compile-time, OUTSIDE gate #1's scan set).

HONEST OUTPUT (read this — it is the headline caveat): the checkpoint proves DURABILITY +
RESUME, NOT convergence. The full graph is non-convergent at POC (SM-1 = 0%): a resumed
investigation re-exhausts the lifetime cap + reaches an HONEST ``partial`` with
``report=None``. The deliverable is the RESUME MECHANISM (state survives + the dispatcher
re-drives it), NOT working RCA. Every resume test asserts ``report is None`` honestly.

WIRING (CS Q1/Q3): the durable ``conn`` is built AND driven on ONE long-lived loop owned
by the dispatcher's background executor (``executor_loop=``) — same-loop, so no cross-loop
aiosqlite fragility. The deployed default (``ContextBuilderRunner``, no durable store) is
UNCHANGED unless ``RCA_CHECKPOINT_DB`` is set (gate #6 determinism harness runs with no env
→ byte-stable compiled graph, no checkpointer).
"""

from __future__ import annotations

import asyncio
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from graph.checkpoint import SqliteCheckpointResumer, build_durable_store
from graph.compiled import build_default_compiled_runner
from graph.runner import GraphRunnerResult
from graph.state import InvestigationState
from services.dispatch import Dispatcher
from services.investigations import (
    STATUS_FAILED,
    STATUS_PARTIAL,
    STATUS_SUCCESS,
    InvestigationStore,
)

# A §3.4-shaped trigger (the chaos CrashLoopBackOff scenario). ``canonical_trigger`` is the
# key the resumer must RECOVER from the checkpointed spine (spine key #3 ``trigger``).
TRIG: dict[str, Any] = {
    "trigger_id": "chaos:crashloop:payment",
    "source": "kubernetes_event",
    "signal_type": "kubernetes_event",
    "service": "payment",
    "namespace": "demo",
    "canonical_trigger": "CrashLoopBackOff",
    "raw_payload": {},
}

# Small lifetime cap so each drive is FAST (the non-convergent graph re-exhausts it → partial
# in well under the poll timeout). Mirrors the integration-probe value.
_MAX_ITER = 3


# ---------------------------------------------------------------------------
# phase helpers — process A (run + die) / process B (restart + resume)
# ---------------------------------------------------------------------------


async def _phase_a_run_async(db_path: str, inv_id: str) -> GraphRunnerResult:
    """Process A: checkpointed runner drives an investigation partway, then 'dies' (conn close).

    The non-convergent graph re-exhausts the cap → ``partial`` (``report=None``). The conn is
    then CLOSED (simulated process death); the checkpoint PERSISTS on the local sqlite file.
    """
    saver, conn = await build_durable_store(db_path)
    runner = build_default_compiled_runner(checkpointer=saver)
    result = await runner.run(TRIG, inv_id, _MAX_ITER)
    await conn.close()  # process A dies — the file on disk is what survives
    return result


async def _inspect_async(db_path: str, inv_id: str) -> tuple[InvestigationState | None, bool]:
    """Reopen a FRESH store over ``db_path`` + inspect the checkpointed investigation.

    Returns ``(loaded_state, is_complete)``. ``loaded_state`` is None if no recoverable
    checkpoint; ``is_complete`` is True iff the checkpoint is at graph END (``.next == ()``).
    """
    saver, conn = await build_durable_store(db_path)
    runner = build_default_compiled_runner(checkpointer=saver)
    loaded = await runner.checkpoint_state(inv_id)
    complete = await runner.checkpoint_is_complete(inv_id)
    await conn.close()
    return loaded, complete


def _build_durable_dispatcher(db_path: Path, store: InvestigationStore) -> Dispatcher:
    """Process B (restart): a Dispatcher whose executor owns the loop the durable conn binds to.

    Mirrors ``routers/app.wire_durable_dispatcher_if_configured``: ONE long-lived daemon-thread
    loop owns the conn + drives the resume scan + the resumed investigations (same-loop → no
    cross-loop aiosqlite fragility). The durable store is built ON that loop; the dispatcher is
    wired to it via ``executor_loop=``.
    """
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, name="test-durable-loop", daemon=True).start()
    future = asyncio.run_coroutine_threadsafe(build_durable_store(str(db_path)), loop)
    saver, conn = future.result()
    runner = build_default_compiled_runner(checkpointer=saver)
    resumer = SqliteCheckpointResumer(runner, conn)
    return Dispatcher(
        runner=runner,
        store=store,
        resume_source=resumer,
        max_iterations=_MAX_ITER,
        executor_loop=loop,
    )


def _wait_until(predicate: Any, timeout: float = 15.0, interval: float = 0.02) -> bool:
    """Poll ``predicate`` until True or timeout (sync test helper)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def _is_terminal(store: InvestigationStore, investigation_id: str) -> bool:
    record = store.get(investigation_id)
    return record is not None and record.is_terminal


# ===========================================================================
# AC1 — durable checkpoint persists across process restart (AD-11)
# ===========================================================================


def test_ac1_checkpoint_survives_process_death(tmp_path: Path) -> None:
    """Process A runs partway + dies; a FRESH store over the same file recovers the checkpoint.

    The full 13-key spine survives the conn close: the trigger is recoverable from the
    checkpointed state + the investigation is still INCOMPLETE (partial → not at graph END).
    This is DURABILITY (AD-11) — the agent's own state outlives the process.
    """
    db = tmp_path / "ac1-durability.db"
    result = asyncio.run(_phase_a_run_async(str(db), "inv-ac1"))
    assert result["status"] == "partial"  # non-convergent → honest partial (NOT success)
    assert result["report"] is None  # HONEST: no convergence → no report

    # process A died (conn closed) → reopen a FRESH store over the SAME file
    loaded, complete = asyncio.run(_inspect_async(str(db), "inv-ac1"))
    assert loaded is not None, "checkpoint did not survive process-A death"
    trigger = loaded.get("trigger")
    assert isinstance(trigger, dict)
    assert trigger.get("canonical_trigger") == "CrashLoopBackOff"  # trigger RECOVERED
    assert complete is False  # still incomplete — partial never reached graph END


def test_ac1_checkpoint_is_local_file_not_sut_write(tmp_path: Path) -> None:
    """AD-3 vs AD-11 boundary: the checkpoint writes a LOCAL sqlite file, NOT a SUT mutation.

    The durable store creates a local file holding LangGraph's own ``checkpoints`` table — the
    agent persisting ITS OWN investigation state (AD-11), wired at graph/compile-time OUTSIDE
    gate #1's tools/adapters scan set. It is NOT a read-only-investigator violation (AD-3
    forbids writing to the SYSTEM-UNDER-INVESTIGATION; this writes the agent's own state).
    """
    db = tmp_path / "ac1-boundary.db"
    asyncio.run(_phase_a_run_async(str(db), "inv-boundary"))
    assert db.exists()  # a LOCAL file was created (the agent's own state)
    conn = sqlite3.connect(str(db))
    try:
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        conn.close()
    assert "checkpoints" in tables  # LangGraph own-state table, NOT a SUT/cluster resource


# ===========================================================================
# AC2 — startup dispatcher resume (AD-10 #4 / AD-11)
# ===========================================================================


def test_ac2_resume_incomplete_scans_and_resumes(tmp_path: Path) -> None:
    """Process A dies mid-investigation; process B's ``resume_incomplete`` resumes it at-least-once.

    The durable scan finds the ONE incomplete investigation, re-registers a read-store record
    from the recovered trigger, + drives the resume on the dispatcher's loop. The investigation
    reaches an HONEST terminal status (success/partial) with ``report=None`` (non-convergent).
    """
    db = tmp_path / "ac2-resume.db"
    asyncio.run(_phase_a_run_async(str(db), "inv-ac2"))  # process A: run + die

    store = InvestigationStore()  # restart: the in-process read-store is EMPTY
    dispatcher = _build_durable_dispatcher(db, store)
    assert store.get("inv-ac2") is None  # nothing registered yet (restart → empty read-store)

    count = dispatcher.resume_incomplete()
    assert count == 1  # one incomplete investigation resumed (at-least-once)

    # the resume re-registered a record (from the recovered trigger) + is driving on the bg loop
    assert store.get("inv-ac2") is not None
    assert _wait_until(lambda: _is_terminal(store, "inv-ac2"))
    final = store.get("inv-ac2")
    assert final is not None
    assert final.status in (STATUS_SUCCESS, STATUS_PARTIAL, STATUS_FAILED)  # honest terminal
    assert final.report is None  # HONEST: non-convergent graph → no report (mechanism, not RCA)


def test_ac2_resume_is_idempotent_no_redrive(tmp_path: Path) -> None:
    """A second ``resume_incomplete`` after the resume reached terminal does NOT re-drive it.

    Idempotency (AD-10 #4): the read-store record is terminal in THIS process → the second scan
    skips it (no duplicate spawn, no re-drive). The non-convergent graph's checkpoint stays
    incomplete (partial → ``.next`` non-empty), so this guard is what prevents a re-drive loop.
    """
    db = tmp_path / "ac2-idem.db"
    asyncio.run(_phase_a_run_async(str(db), "inv-idem"))

    store = InvestigationStore()
    dispatcher = _build_durable_dispatcher(db, store)
    assert dispatcher.resume_incomplete() == 1
    assert _wait_until(lambda: _is_terminal(store, "inv-idem"))

    # second scan after terminal → no re-drive (read-store terminal guard)
    assert dispatcher.resume_incomplete() == 0


def test_ac2_resume_no_live_inflight_guard(tmp_path: Path) -> None:
    """A second ``resume_incomplete`` while a resume is still LIVE does not spawn a duplicate.

    Idempotency (AD-10 #4): a live in-flight resume task → the second scan skips it (the
    ``has_inflight`` guard), so there is never a duplicate concurrent resume per investigation.
    """
    db = tmp_path / "ac2-inflight.db"
    asyncio.run(_phase_a_run_async(str(db), "inv-inflight"))

    store = InvestigationStore()
    dispatcher = _build_durable_dispatcher(db, store)
    assert dispatcher.resume_incomplete() == 1
    # while the resume task is live, a second scan is a no-op (has_inflight guard)
    if dispatcher.has_inflight("inv-inflight"):
        assert dispatcher.resume_incomplete() == 0
    assert _wait_until(lambda: _is_terminal(store, "inv-inflight"))


def test_ac2_resume_noop_without_resumer() -> None:
    """The in-process default (no durable store) → ``resume_incomplete`` is a no-op (returns 0)."""
    dispatcher = Dispatcher()  # default — no resume_source
    assert dispatcher.resume_incomplete() == 0


def test_ac2_incomplete_investigations_recovers_trigger(tmp_path: Path) -> None:
    """The resumer scan returns the incomplete ``(investigation_id, trigger)`` pair.

    ``trigger`` is RECOVERED from the checkpointed spine (key #3) so the dispatcher can
    re-register the read-store record. Only INCOMPLETE investigations are returned (terminal
    ones are excluded via ``StateSnapshot.next == ()``); the non-convergent graph never reaches
    END, so this POC exercises the incomplete case (the realistic one).
    """
    db = tmp_path / "ac2-scan.db"
    asyncio.run(_phase_a_run_async(str(db), "inv-scan"))

    async def _scan() -> list[tuple[str, dict[str, Any]]]:
        saver, conn = await build_durable_store(str(db))
        runner = build_default_compiled_runner(checkpointer=saver)
        resumer = SqliteCheckpointResumer(runner, conn)
        pairs = await resumer.incomplete_investigations()
        await conn.close()
        return pairs

    pairs = asyncio.run(_scan())
    assert len(pairs) == 1
    inv_id, trigger = pairs[0]
    assert inv_id == "inv-scan"
    assert trigger.get("canonical_trigger") == "CrashLoopBackOff"  # recovered from the spine
