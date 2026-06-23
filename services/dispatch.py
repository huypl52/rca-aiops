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
from typing import Any

from graph.runner import ContextBuilderRunner, GraphRunner, GraphRunnerResult
from services.investigations import (
    STATUS_FAILED,
    STATUS_SUCCESS,
    InvestigationStore,
    default_store,
)

# Dispatcher-level lifetime cap (FR-7). The dispatcher owns the cap VALUE and
# passes it to the runner, which honors it (exceed → status="failed"). Graph-
# internal reflector-loop max-iter = Story 3-x (deferred — not enforced here).
# Small + configurable for deterministic tests; bumped for prod-like runs.
MAX_ITERATIONS_DEFAULT: int = 100


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

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._tasks: dict[str, asyncio.Task[Any]] = {}

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
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
    ) -> None:
        self._runner: GraphRunner = runner if runner is not None else ContextBuilderRunner()
        self._store: InvestigationStore = store if store is not None else default_store()
        self._max_iterations: int = max_iterations
        self._executor: _BackgroundExecutor = _BackgroundExecutor()

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

        status = result.get("status", STATUS_SUCCESS)
        # Defensive: only success/failed are valid terminal lifecycle states. An
        # unknown status is a runner contract violation → FAILED (not silent).
        if status not in (STATUS_SUCCESS, STATUS_FAILED):
            status = STATUS_FAILED
        self._store.set_terminal(
            investigation_id,
            status,
            result.get("state_snapshot"),
            result.get("report"),
        )

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
    "set_default_dispatcher",
    "startup_scan",
]
