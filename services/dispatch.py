"""Async/background dispatch MECHANISM + in-process resume (AD-10 #2/#4/#5).

Story 1.4 — AD-10 Option C (LangGraph ``.ainvoke``/``.astream`` in a background
asyncio task + in-process dispatcher) / FR-7 (lifetime cap).

1-2 was the async **CONTRACT** (return ``202 + investigation_id`` immediately,
non-blocking as a promise). 1-4 is the **MECHANISM** that actually runs the
investigation in a non-blocking background task and keeps the 202 immediate:

  ingest → normalize_* (1-1) → group() (1-2, idempotent trigger_id) →
  dispatch(investigation_id, trigger) → enqueue background GraphRunner task →
  return 202 + investigation_id IMMEDIATELY (HTTP does NOT block, AD-10 #2).

The dispatcher:
  1. registers the investigation as ``running`` in the store,
  2. enqueues a background asyncio task (via ``_BackgroundExecutor``) that runs
     the ``GraphRunner`` PORT to terminal and updates the store,
  3. returns immediately (non-blocking).

GraphRunner PORT (AD-2 / AC2): the dispatcher depends on the ``GraphRunner``
Protocol (entry contract), NOT on compiled-graph internals. Story 1.4 ships a
minimal runner (``ContextBuilderRunner``, graph/runner.py — runs the 1-3 node);
Story 3-5 plugs the real compiled graph (same Protocol, dispatcher unchanged).

In-process resume (AD-10 #4 / AC5): ``startup_scan()`` re-dispatches every
non-terminal investigation WITHOUT a live task (e.g. left running after
task-death) — at-least-once, idempotent on ``investigation_id`` (no duplicate
concurrent task). Survives TASK-DEATH (proven by test); does NOT survive process
restart — cross-restart SqliteSaver durability (AD-11) = Story 7-4 (AC6).

Read-only boundary (AD-3 / AC9): at-least-once resume is SAFE because the
investigation is read-only (no write side-effect to double-apply). The read-only
tool registry / CI#1 = Story 2-1 (NOT implemented here).

ONE-WAY (AD-1 / gate #2): imports ``graph.runner`` (the entry-contract PORT,
downstream — AD-2-clean) + ``services.investigations`` (same layer) + stdlib.
NEVER imports compiled-graph internals / node functions / routers / adapters /
tools. Constrain D8: WAL/concurrent throughput deferred (single in-flight task
per investigation_id; the executor is single-loop single-thread).
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Coroutine
from typing import Any, TypeVar

from graph.runner import ContextBuilderRunner, GraphRunner, GraphRunnerResult, InvestigationResumer
from services.investigations import (
    STATUS_FAILED,
    STATUS_PARTIAL,
    STATUS_SUCCESS,
    InvestigationStore,
    default_store,
)

# Dispatcher-level lifetime cap (FR-7). The dispatcher owns the cap VALUE and
# passes it to the runner, which honors it (exceed → status="partial" — Story
# 4-3 / AD-10 #5: max-iter exhaustion is an HONEST partial, NOT a binary fail).
# Graph-internal reflector-loop max-iter = Story 4-3 (deferred — not enforced here).
# Small + configurable for deterministic tests; bumped for prod-like runs.
MAX_ITERATIONS_DEFAULT: int = 100

# Return-type variable for _BackgroundExecutor.run_sync (bridges a coroutine result to a sync caller
# — the dispatcher's resume_incomplete runs the async resumer scan synchronously on its bg loop).
_T = TypeVar("_T")


class _BackgroundExecutor:
    """In-process background asyncio executor (AD-10 Option C).

    Runs ONE dedicated event loop on a daemon thread. ``submit()`` schedules a
    coroutine as an asyncio Task on that loop and returns IMMEDIATELY (non-
    blocking — AD-10 #2). Tasks are tracked + cancellable, so the dispatcher can
    simulate task-death (AC5) and re-dispatch at-least-once.

    IN-PROCESS ONLY (AD-10 #4): survives task-death within one process; does NOT
    survive process restart (cross-restart SqliteSaver durability = Story 7-4).
    Concurrency (D8): single in-flight task per investigation_id (idempotent
    guard in the dispatcher); full concurrent throughput / WAL = deferred.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        # ``loop`` (Story 7-4): an EXTERNALLY-owned, ALREADY-RUNNING loop the executor reuses
        # instead of creating its own. Used by the durable-dispatcher wiring so the durable
        # checkpoint ``conn`` is built AND driven on ONE loop (same-loop → no cross-loop
        # aiosqlite fragility). When None (the in-process default) the loop is created lazily on
        # first use (existing behavior — unchanged for the 25 dispatch tests).
        self._loop: asyncio.AbstractEventLoop | None = loop
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._tasks: dict[str, asyncio.Task[Any]] = {}

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is not None:
            return self._loop  # injected (already running on a caller-managed daemon thread)
        with self._lock:
            if self._loop is None:
                self._loop = asyncio.new_event_loop()
                self._thread = threading.Thread(
                    target=self._run_loop, name="dispatcher-bg", daemon=True
                )
                self._thread.start()
            assert self._loop is not None
            return self._loop

    def _run_loop(self) -> None:
        assert self._loop is not None
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def submit(self, investigation_id: str, coro: Coroutine[Any, Any, None]) -> None:
        """Schedule ``coro`` as a tracked, cancellable task on the background loop.

        Returns immediately (non-blocking). The coroutine is tracked under
        ``investigation_id`` so it can be cancelled (task-death) and so the
        dispatcher's idempotent guard can detect a live in-flight task.
        """
        loop = self._ensure_loop()
        asyncio.run_coroutine_threadsafe(self._track(investigation_id, coro), loop)

    def run_sync(self, coro: Coroutine[Any, Any, _T]) -> _T:
        """Run ``coro`` on the background loop + BLOCK the caller until it returns (Story 7-4).

        Used by the dispatcher's cross-restart ``resume_incomplete`` to run the ASYNC durable-store
        resumer scan (``InvestigationResumer.incomplete_investigations``) synchronously from its sync
        startup caller. MUST be called from OUTSIDE the background loop (the caller blocks until the
        coro completes on the loop thread) — the resume scan never re-enters the loop, so no deadlock.
        """
        loop = self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result()  # blocks the caller until the coro completes on the loop thread

    async def _track(self, investigation_id: str, coro: Coroutine[Any, Any, None]) -> None:
        # Runs ON the background loop — the running loop IS this executor's loop.
        task = asyncio.ensure_future(coro)
        self._tasks[investigation_id] = task

        def _cleanup(done: asyncio.Task[Any]) -> None:
            # Pop only if it is still us — do not clobber a re-dispatch's new task.
            if self._tasks.get(investigation_id) is done:
                self._tasks.pop(investigation_id, None)

        task.add_done_callback(_cleanup)

    def cancel(self, investigation_id: str) -> bool:
        """Cancel a live in-flight task (task-death simulation, AC5 test)."""
        loop = self._loop
        task = self._tasks.get(investigation_id)
        if loop is None or task is None:
            return False
        loop.call_soon_threadsafe(task.cancel)
        return True

    def has_inflight(self, investigation_id: str) -> bool:
        task = self._tasks.get(investigation_id)
        return task is not None and not task.done()

    def inflight_ids(self) -> list[str]:
        # Snapshot under iteration — a concurrent _track/_cleanup mutation of
        # ``_tasks`` must not raise "dict changed size during iteration".
        return [tid for tid, task in list(self._tasks.items()) if not task.done()]

    def clear(self) -> None:
        """Cancel all in-flight tasks (test isolation)."""
        for investigation_id in list(self._tasks):
            self.cancel(investigation_id)
        self._tasks.clear()


class Dispatcher:
    """Async dispatcher + in-process resume (AD-10 #2/#4/#5).

    Depends on the ``GraphRunner`` PORT (DI) — never compiled-graph internals.
    Story 3-5 swaps the runner; this class is unchanged (the seam, AC2).
    """

    def __init__(
        self,
        runner: GraphRunner | None = None,
        store: InvestigationStore | None = None,
        max_iterations: int = MAX_ITERATIONS_DEFAULT,
        resume_source: InvestigationResumer | None = None,
        executor_loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self._runner: GraphRunner = runner if runner is not None else ContextBuilderRunner()
        self._store: InvestigationStore = store if store is not None else default_store()
        self._max_iterations: int = max_iterations
        # Story 7-4: optional durable-store resume PORT (DI). None (default) → cross-restart resume is
        # a no-op (the in-process default — no durable store). When injected, resume_incomplete scans
        # the durable store + resumes incomplete investigations on restart (AD-11 / AD-10 #4).
        self._resume_source: InvestigationResumer | None = resume_source
        # ``executor_loop`` (Story 7-4): inject the SAME loop the durable ``conn`` is bound to so the
        # checkpoint drives + the resume scan share ONE loop (same-loop → robust). None (default) →
        # the executor creates + owns its own loop (existing in-process behavior).
        self._executor: _BackgroundExecutor = _BackgroundExecutor(loop=executor_loop)

    @property
    def store(self) -> InvestigationStore:
        return self._store

    @property
    def runner(self) -> GraphRunner:
        return self._runner

    @property
    def max_iterations(self) -> int:
        return self._max_iterations

    def dispatch(self, investigation_id: str, trigger: dict[str, Any]) -> str:
        """Idempotently dispatch an investigation as a non-blocking background task.

        Registers the investigation as ``running`` (if new) and enqueues a
        background task that runs the runner to terminal, updating the store.
        Returns ``investigation_id`` IMMEDIATELY (AD-10 #2 — HTTP does not block).

        Idempotent (AD-10 #4): if the investigation is already non-terminal AND
        has a live in-flight task, this is a no-op (NO duplicate concurrent task
        per investigation_id). If non-terminal WITHOUT a live task (e.g. after
        task-death), it re-dispatches (at-least-once).
        """
        existing = self._store.get(investigation_id)
        if (
            existing is not None
            and not existing.is_terminal
            and self._executor.has_inflight(investigation_id)
        ):
            # already running with a live task → idempotent no-op (no duplicate spawn)
            return investigation_id
        # On a FIRST dispatch (no record) register + use the inbound trigger. On a
        # re-dispatch (record exists, non-terminal, no live task — e.g. after task-death)
        # resume from the STORED trigger so the re-run is consistent with the record
        # regardless of the (caller-supplied) trigger argument.
        if existing is None:
            self._store.register_running(investigation_id, trigger)
            resume_trigger = trigger
        else:
            resume_trigger = existing.trigger
        # enqueue non-blocking background run
        self._executor.submit(investigation_id, self._run(investigation_id, resume_trigger))
        return investigation_id

    async def _run(self, investigation_id: str, trigger: dict[str, Any]) -> None:
        """Background task body: run the runner → update store to terminal.

        CancelledError (task-death, AC5) leaves the store NON-terminal (running)
        so ``startup_scan`` re-dispatches. Any other exception → status ``failed``
        (NOT silent, AD-10 #5). The runner honors ``max_iterations`` (FR-7).
        """
        try:
            result: GraphRunnerResult = await self._runner.run(
                trigger, investigation_id, self._max_iterations
            )
        except asyncio.CancelledError:
            # task killed mid-run (simulated crash, AC5) → leave the record
            # NON-terminal (running) so startup_scan re-dispatches at-least-once.
            # Do NOT mark failed (that would hide the crash as a clean failure).
            raise
        except Exception:
            # runner failure → status failed (NOT silent, AD-10 #5). The failure
            # is observable via the read-store (status=failed) — that is the
            # non-silent contract; we do not re-raise into the background task.
            self._store.set_failed(investigation_id)
            return
        self._apply_result(investigation_id, result)

    def _apply_result(self, investigation_id: str, result: GraphRunnerResult) -> None:
        """Map a terminal ``GraphRunnerResult`` onto the registry lifecycle status (shared run + resume).

        ``success`` / ``failed`` / ``partial`` are valid terminal lifecycle states (5-2 / 4-A2): the
        runner's honest ``partial`` (max-iter exhausted) is passed through as ``STATUS_PARTIAL`` — NOT
        masked as ``failed`` (AD-10 #5). Any OTHER status is a runner contract violation → FAILED.
        Shared by the fresh-run task (:meth:`_run`) + the resume task (:meth:`_run_resume`) so the
        terminal mapping is SINGULAR (the dispatcher contract is identical for a fresh + a resumed run).
        """
        status = result.get("status", STATUS_SUCCESS)
        if status not in (STATUS_SUCCESS, STATUS_FAILED, STATUS_PARTIAL):
            status = STATUS_FAILED
        self._store.set_terminal(
            investigation_id,
            status,
            result.get("state_snapshot"),
            result.get("report"),
        )

    async def _run_resume(self, investigation_id: str) -> None:
        """Background RESUME task body (Story 7-4): drive the resumer → update store to terminal.

        The resumer holds the checkpointed runner + resumes WITHOUT a trigger (the checkpoint holds
        the state). Same terminal mapping as :meth:`_run` (shared via :meth:`_apply_result`).
        CancelledError leaves the store NON-terminal (re-resumable at-least-once); any other exception
        → status ``failed`` (NOT silent, AD-10 #5).
        """
        assert self._resume_source is not None  # only submitted when a resumer is injected
        try:
            result: GraphRunnerResult = await self._resume_source.resume(
                investigation_id, self._max_iterations
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            self._store.set_failed(investigation_id)
            return
        self._apply_result(investigation_id, result)

    def startup_scan(self) -> int:
        """Resume-trigger (AD-10 #4): re-dispatch non-terminal investigations.

        Scans the in-process store for non-terminal records WITHOUT a live task
        (e.g. left running after task-death) and re-dispatches them at-least-once.
        Idempotent on ``investigation_id`` (no duplicate concurrent task).

        IN-PROCESS (1-4): explicit call within one process. Cross-restart scan of
        a durable checkpoint store (SqliteSaver, AD-11) = Story 7-4 (AC6).
        Returns the number of investigations re-dispatched.
        """
        count = 0
        for record in self._store.non_terminal():
            if self._executor.has_inflight(record.investigation_id):
                continue  # already live → no duplicate spawn (idempotent)
            self._executor.submit(
                record.investigation_id,
                self._run(record.investigation_id, record.trigger),
            )
            count += 1
        return count

    def resume_incomplete(self) -> int:
        """Cross-restart resume (Story 7-4 — AD-10 #4 / AD-11): resume durable-incomplete investigations.

        The DURABLE analog of :meth:`startup_scan`. Scans the durable checkpoint store (via the injected
        ``InvestigationResumer`` PORT) for INCOMPLETE investigations (those NOT yet at graph END) and
        resumes each at-least-once — recovering the trigger from the checkpoint + re-registering the
        in-process read-store record so the terminal update (``set_terminal``) has a record to write.

        No-op (returns 0) when NO resumer is injected — the in-process default (no durable store). The
        scan runs the async resumer SYNCHRONOUSLY on the background loop (``run_sync`` — bridges the
        async durable-store scan to this sync startup caller); the resumes are then scheduled as
        non-blocking background tasks.

        Idempotent (AD-10 #4): skips any investigation with a live in-flight task (no duplicate spawn)
        OR a read-store record ALREADY terminal in THIS process (no re-drive). Safe because the
        investigation is read-only (at-least-once resume has no double-apply side effect — AD-3).
        """
        if self._resume_source is None:
            return 0  # in-process default (no durable store) → cross-restart resume is a no-op
        pairs = self._executor.run_sync(self._resume_source.incomplete_investigations())
        count = 0
        for investigation_id, trigger in pairs:
            if self._executor.has_inflight(investigation_id):
                continue  # already resuming → no duplicate spawn (idempotent)
            existing = self._store.get(investigation_id)
            if existing is not None and existing.is_terminal:
                continue  # already resolved in THIS process → no re-drive (idempotent)
            if existing is None:
                # restart: the in-process read-store is EMPTY → re-register from the recovered
                # trigger so ``set_terminal`` (the terminal update) has a record to write. The resume
                # itself needs NO trigger (the checkpoint holds the state) — the trigger is for the
                # read-store record's consistency with the original dispatch.
                self._store.register_running(investigation_id, trigger)
            self._executor.submit(investigation_id, self._run_resume(investigation_id))
            count += 1
        return count

    def kill(self, investigation_id: str) -> bool:
        """Simulate task-death (AC5 test): cancel a live in-flight task.

        Leaves the store record NON-terminal (running) so ``startup_scan``
        re-dispatches. Returns True iff a live task was cancelled.
        """
        return self._executor.cancel(investigation_id)

    def has_inflight(self, investigation_id: str) -> bool:
        return self._executor.has_inflight(investigation_id)


# ---------------------------------------------------------------------------
# Module-level default dispatcher — the in-process singleton used by the ingest
# router. The default runner is the minimal ContextBuilderRunner; the composition
# root (routers/app) / Story 3-5 may swap it (set_default_dispatcher / DI).
# ---------------------------------------------------------------------------
_default_dispatcher: Dispatcher | None = None


def default_dispatcher() -> Dispatcher:
    global _default_dispatcher
    if _default_dispatcher is None:
        _default_dispatcher = Dispatcher()
    return _default_dispatcher


def set_default_dispatcher(dispatcher: Dispatcher) -> None:
    """Composition-root override (3-5 plugs the compiled-graph runner here, AC2)."""
    global _default_dispatcher
    _default_dispatcher = dispatcher


def dispatch(investigation_id: str, trigger: dict[str, Any]) -> str:
    """Convenience: dispatch via the default in-process dispatcher."""
    return default_dispatcher().dispatch(investigation_id, trigger)


def startup_scan() -> int:
    """Convenience: run the default dispatcher's in-process resume scan."""
    return default_dispatcher().startup_scan()


def resume_incomplete() -> int:
    """Convenience: run the default dispatcher's cross-restart resume scan (Story 7-4).

    No-op (returns 0) unless the composition root injected a durable-store
    ``InvestigationResumer`` into the default dispatcher (``set_default_dispatcher`` /
    routers wiring). Called at process startup to resume durable-incomplete
    investigations at-least-once (AD-10 #4 / AD-11).
    """
    return default_dispatcher().resume_incomplete()


def reset_dispatcher() -> None:
    """Test isolation: cancel in-flight tasks + clear the default store."""
    dispatcher = default_dispatcher()
    dispatcher._executor.clear()
    dispatcher.store.clear()


__all__ = [
    "MAX_ITERATIONS_DEFAULT",
    "Dispatcher",
    "default_dispatcher",
    "dispatch",
    "reset_dispatcher",
    "resume_incomplete",
    "set_default_dispatcher",
    "startup_scan",
]
