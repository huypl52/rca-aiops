"""Durable checkpointer — LangGraph ``AsyncSqliteSaver`` factory + cross-restart resumer (Story 7-4 — AD-11 / AD-10 #4).

AD-3 vs AD-11 BOUNDARY (read this — it is the subtlest line in the project):
  - **AD-3 (read-only investigator):** the agent MUST NOT mutate the SYSTEM-UNDER-INVESTIGATION
    (the demo cluster / K8s / Prometheus / Loki — §3.8). Enforced by gate #1 scanning
    ``tools``/``adapters`` for write operations. This module is in ``graph`` — OUTSIDE that scan
    set — and it writes a LOCAL sqlite FILE (the agent's OWN state), NOT a SUT/cluster resource.
    The checkpoint is the agent persisting ITS OWN investigation state; it is NOT the agent
    mutating the system it investigates. **AD-3 and AD-11 are INDEPENDENT concerns.**
  - **AD-11 (durable checkpoint):** the agent's OWN investigation state survives process restart,
    so an interrupted investigation resumes from where it stopped. At-least-once resume is SAFE
    because the investigation is READ-ONLY (re-running a read has no double-apply side effect —
    the read-only-investigator contract is what makes idempotent resume correct).

WHAT THIS MODULE DOES:
  - :func:`build_durable_store` — async factory returning ``(AsyncSqliteSaver, aiosqlite.Connection)``.
    The SYNC ``SqliteSaver`` raises ``NotImplementedError`` on the async ``astream``/``aget_state``
    the compiled graph uses, so the ASYNC saver (aiosqlite-backed) is REQUIRED. Portable serializer
    = LangGraph's BUILT-IN ``JsonPlusSerializer`` (the saver default — AD-9: NO custom serializer;
    the 13-key spine is already JSON-safe, validated by gate #3).
  - :class:`SqliteCheckpointResumer` — the cross-restart resume PORT implementation
    (:class:`graph.runner.InvestigationResumer`): scans the durable store for INCOMPLETE
    investigations + drives each to terminal WITHOUT a trigger (the checkpoint holds the state).

SWAP (AC1 — SqliteSaver ↔ PostgresSaver ≠ change contract): swapping the backend = swapping the
store FACTORY (:func:`build_durable_store` → a postgres factory returning a ``BaseCheckpointSaver`` +
a connection). The resumer + the runner + the dispatcher are UNCHANGED — they depend on the PORT
(``InvestigationResumer`` / the runner's ``resume``/``checkpoint_*`` methods), NOT on this concrete
sqlite type. The dispatcher imports ``graph.runner`` (the PORT); it NEVER imports this module.

ONE-WAY (AD-1 / gate #2): imports ``graph.runner`` (the PORT, same layer) + ``graph.compiled`` (the
concrete checkpointed runner — same layer) + langgraph + aiosqlite (3rd-party) + stdlib ONLY. NEVER
``routers``/``services``/``adapters``/``tools``. The dispatcher imports the PORT, not this module —
so adding a concrete durable-store dependency here does NOT widen the services→graph edge.

Determinism (AD-12): this module opens a FILE at call time (an IO side effect) — but that IO is
CONFINED to the durable-store lifecycle (the agent's OWN state file), NOT the agent's INVESTIGATION
logic. The investigation graph + its nodes stay byte-deterministic; the checkpointer is
infrastructure wired at compile-time, exactly like the EXR adapter seam (graph→tools FORWARD). The
determinism harness (gate #6) compiles the graph with NO checkpointer (byte-identical to pre-7-4);
this module is exercised only by the resume path + its tests.
"""

from __future__ import annotations

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from graph.compiled import CompiledGraphRunner
from graph.runner import GraphRunnerResult, InvestigationResumer
from graph.state import JsonValue


async def build_durable_store(
    db_path: str,
) -> tuple[AsyncSqliteSaver, aiosqlite.Connection]:
    """Open + set up the durable sqlite checkpoint store (Story 7-4 AC1 — AD-11).

    Opens an aiosqlite connection over ``db_path``, wraps it in ``AsyncSqliteSaver`` (the ASYNC
    saver — the sync ``SqliteSaver`` raises ``NotImplementedError`` on the compiled graph's async
    ``astream``/``aget_state``), runs ``setup()`` to create the checkpoint tables, and returns
    ``(saver, conn)``. Wire the ``saver`` at ``build_compiled_graph(checkpointer=saver)`` (compile
    time — AD-2 immutable-once); pass the SAME ``conn`` to :class:`SqliteCheckpointResumer` (for
    cross-thread enumeration). The caller owns the connection lifecycle (the process lifetime for
    the deployed backend; a temp file for the in-process test).

    Serializer (AD-9): the saver's DEFAULT ``JsonPlusSerializer`` (NO custom serializer). The 13-key
    spine is already JSON-safe (gate #3 round-trips it), so the built-in serializer is sufficient +
    PORTABLE (the sqlite ↔ postgres swap needs no custom serde — AC1). WAL / concurrent-throughput
    tuning (Constrain D8) is deferred; a single aiosqlite connection is the POC-durable choice.
    """
    conn = await aiosqlite.connect(db_path)
    saver = AsyncSqliteSaver(conn)
    await saver.setup()
    return saver, conn


class SqliteCheckpointResumer(InvestigationResumer):
    """Cross-restart resume over the durable sqlite store (Story 7-4 AC2 — AD-10 #4 / AD-11).

    Implements :class:`graph.runner.InvestigationResumer`. The dispatcher injects this PORT (DI) —
    it depends on the PORT, NOT on this concrete type. ``resume_incomplete()`` scans the durable
    store for incomplete investigations + drives each to terminal at-least-once.

    Source of truth for "incomplete" (CS Q2): the DURABLE checkpoint store — an investigation is
    incomplete when its last checkpoint is NOT at graph END (``StateSnapshot.next`` non-empty). The
    in-process read-store (``services.investigations``) is an in-process API cache, NOT durable; on
    restart it is EMPTY, so the durable store is the ONLY source of "what was running". The
    ``trigger`` is RECOVERED from the checkpointed state (spine key #3) so the dispatcher can
    re-register the read-store record (``set_terminal`` is a no-op without a record — Story 1-4).
    """

    def __init__(self, runner: CompiledGraphRunner, conn: aiosqlite.Connection) -> None:
        # ``runner`` is the CHECKPOINTED CompiledGraphRunner (compiled with the saver built from the
        # SAME connection). ``conn`` is used ONLY to enumerate thread_ids: LangGraph's
        # ``saver.alist()`` filters a SINGLE thread_id, so cross-thread enumeration needs a raw
        # ``DISTINCT thread_id`` over the connection (the checkpoints table is a LangGraph detail,
        # read but never written here — the WRITE is the saver's, at drive time).
        self._runner = runner
        self._conn = conn

    async def incomplete_investigations(self) -> list[tuple[str, dict[str, JsonValue]]]:
        """Durable scan: incomplete ``(investigation_id, trigger)`` pairs to resume.

        Enumerates every checkpointed thread (``DISTINCT thread_id`` where ``checkpoint_ns=''`` —
        the root namespace, one per investigation), and for each recovers the trigger from the
        checkpointed state (spine key #3) + keeps only the INCOMPLETE ones (``StateSnapshot.next``
        non-empty — NOT yet at graph END). Terminal investigations are NOT resumed (idempotent).
        """
        thread_ids = await self._distinct_thread_ids()
        incomplete: list[tuple[str, dict[str, JsonValue]]] = []
        for thread_id in thread_ids:
            state = await self._runner.checkpoint_state(thread_id)
            if state is None:
                continue  # no recoverable state (a checkpoint row with an empty channel value)
            if await self._runner.checkpoint_is_complete(thread_id):
                continue  # already at END → terminal, do not resume (idempotent)
            trigger = state.get("trigger")
            recovered = dict(trigger) if isinstance(trigger, dict) else {}
            incomplete.append((thread_id, recovered))
        return incomplete

    async def resume(self, investigation_id: str, max_iterations: int) -> GraphRunnerResult:
        """Continue a checkpointed investigation to terminal WITHOUT a trigger (checkpoint holds it).

        Delegates to the runner's ``resume`` (same compiled graph + saver). Reaching END →
        ``success`` (+ report if the graph converged); re-exhausting the cap → an honest ``partial``
        (AD-10 #5). Raising propagates to the dispatcher's ``status="failed"`` (NOT silent).
        """
        return await self._runner.resume(investigation_id, max_iterations)

    async def _distinct_thread_ids(self) -> list[str]:
        """Every investigation thread that has a checkpoint (root namespace, one per investigation).

        LangGraph's ``saver.alist()`` accepts a single ``thread_id`` filter — it CANNOT enumerate
        across threads — so a raw ``DISTINCT thread_id`` over the connection is required. The
        ``checkpoints`` table + ``checkpoint_ns=''`` (root namespace) are LangGraph storage details;
        this READS them (the WRITE is the saver's, at drive time — the agent's own state).
        """
        async with self._conn.execute(
            "SELECT DISTINCT thread_id FROM checkpoints WHERE checkpoint_ns = ''"
        ) as cursor:
            rows = await cursor.fetchall()
        return [row[0] for row in rows if isinstance(row[0], str)]


__all__ = [
    "SqliteCheckpointResumer",
    "build_durable_store",
]
