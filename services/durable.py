"""Story 7-4 — durable-dispatcher composition root (AD-11 / AD-10 #4).

Env-gated wiring of a durable ``AsyncSqliteSaver`` checkpointer + a cross-restart
``SqliteCheckpointResumer`` into the default dispatcher. This module is the composition root
for the durable path: it imports the ``graph`` CONCRETE checkpoint/runner + instantiates them +
injects them into the dispatcher. The dispatcher itself still depends only on the PORTs
(``GraphRunner`` / ``InvestigationResumer``) — AD-2 seam preserved; THIS module owns the wiring.

WHY THIS LIVES IN ``services`` (NOT ``routers``): the layering contract allows services→graph
(forward), but ``routers`` is forbidden from importing ``graph``
(``test_routers_module_does_not_import_forbidden_layers`` mirrors gate #2: routers imports only
fastapi/pydantic/models/services). ``routers/app`` therefore calls this function; it never
imports ``graph`` itself.

AD-3 vs AD-11 BOUNDARY (the subtlest line in the project): the checkpoint WRITE is the agent
persisting its OWN investigation state to a LOCAL sqlite FILE — NOT a read-only-investigator
violation. AD-3 (gate #1) forbids writing to the SYSTEM-UNDER-INVESTIGATION via
``tools``/``adapters``; this is wired at graph/compile-time in the ``graph`` layer, OUTSIDE
that scan set. The two concerns (AD-3 read-only investigator vs AD-11 durable own-state) are
INDEPENDENT. At-least-once resume is SAFE precisely because the investigation is read-only
(re-running a read has no double-apply side effect).

ONE-WAY (AD-1 / gate #2): imports ``graph.checkpoint`` + ``graph.compiled`` (forward, same
project) + ``services.dispatch`` (same layer) + stdlib ONLY. NEVER ``routers``/``adapters``/
``tools``. Lazy imports inside the function so the no-env path (the POC default) never pulls
the sqlite checkpoint deps — the determinism harness (gate #6) compiles the graph with NO
checkpointer (byte-identical to pre-7-4).

Determinism (AD-12): this module opens a FILE + a daemon-thread loop — IO + threading confined
to the durable-store LIFECYCLE (the agent's OWN state), NOT to the investigation graph logic.
The graph + its nodes stay byte-deterministic; the checkpointer is infrastructure wired at
compile-time, exactly like the EXR adapter seam (graph→tools FORWARD).
"""

from __future__ import annotations

import os


def wire_durable_dispatcher_if_configured() -> None:
    """Env-gated (``RCA_CHECKPOINT_DB``): wire the durable checkpointer + resume on startup.

    When ``RCA_CHECKPOINT_DB`` is set, build a durable ``AsyncSqliteSaver`` store over that file,
    compile the graph WITH that checkpointer, inject a cross-restart ``SqliteCheckpointResumer``
    into a fresh dispatcher, set it as the default, + resume any durable-incomplete
    investigations at-least-once. When UNSET (the POC default) this is a no-op — the deployed
    app is UNCHANGED: the minimal ``ContextBuilderRunner`` + no durable store.

    The durable ``conn`` is built AND driven on ONE long-lived daemon-thread loop owned by the
    dispatcher's background executor (``executor_loop=``) — same-loop, so no cross-loop aiosqlite
    fragility (the conn, the resume scan, + the resumed investigations all share the one loop).
    """
    db_path = os.environ.get("RCA_CHECKPOINT_DB")
    if not db_path:
        return  # POC default — no durable store; deployed app unchanged (gate #6 byte-stable)

    # Lazy imports: pull the sqlite checkpoint deps ONLY on the durable path (the no-env path
    # returns above, so importing routers/app never touches them). Layers-clean: services(1)
    # → graph(2) is forward.
    import asyncio
    import threading

    from graph.checkpoint import SqliteCheckpointResumer, build_durable_store
    from graph.compiled import build_default_compiled_runner
    from services.dispatch import Dispatcher, set_default_dispatcher

    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, name="rca-durable-loop", daemon=True).start()
    # Build the durable store ON that loop (the conn binds to it); run_coroutine_threadsafe
    # blocks this caller until the store is ready. The saver + conn are then held by the
    # dispatcher (→ the module-level default) for the process lifetime.
    future = asyncio.run_coroutine_threadsafe(build_durable_store(db_path), loop)
    saver, conn = future.result()
    runner = build_default_compiled_runner(checkpointer=saver)
    resumer = SqliteCheckpointResumer(runner, conn)
    dispatcher = Dispatcher(runner=runner, resume_source=resumer, executor_loop=loop)
    set_default_dispatcher(dispatcher)
    # Cross-restart resume (AC2): at process start, scan the durable store + resume any
    # incomplete investigations at-least-once (safe — read-only, idempotent on trigger).
    dispatcher.resume_incomplete()


__all__ = ["wire_durable_dispatcher_if_configured"]
