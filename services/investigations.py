"""Investigation lifecycle registry — the in-process read-store backing (AD-10 #3).

Story 1.4 — AD-10 #3 (trace+report via store, no sync) / AD-9 (JSON-safe) /
AD-10 #4 (at-least-once resume from store) / AD-10 #5 (terminal not-silent).
Story 5-2 — ``STATUS_PARTIAL`` (4-A2 honest-partial wiring end-to-end: runner
``partial`` → registry ``partial`` → API ``partial``, NOT masked as ``failed``;
AD-10 #5) + the OUTPUT-SIDE remediation-off guard (AC2 / T9 / D12 defense-in-depth).

Maps ``investigation_id -> InvestigationRecord`` where a record carries:

  - the REGISTRY-LEVEL lifecycle ``status`` (``running`` / ``success`` / ``failed`` /
    ``partial`` [5-2 — max-iter exhausted, inconclusive; AD-10 #5]),
  - a JSON-safe ``state_snapshot`` (the read-store projection),
  - the optional ``report`` (RCA, FR-9 — ``None`` until Epic 5),
  - the original ``trigger`` dict (kept for at-least-once resume; NOT exposed in
    the read-store response).

CRITICAL (AD-9): lifecycle ``status`` is REGISTRY-LEVEL — it is NOT a key on the
13-key ``InvestigationState`` spine. Story 1.4 deliberately does NOT add a
``status`` key to the graph state (gate #5 contract 18/9 + gate #3 spine
unchanged — proven by ``assert len(InvestigationState.__annotations__) == 13``).
The registry is a separate in-process dict keyed by ``investigation_id``.

Scope (locked 1-4 vs 7-4): in-memory POC — survives across requests/tests WITHIN
ONE process and survives task-death (the dispatcher re-dispatches a record left
non-terminal by a killed background task, AC5). Cross-RESTART durability
(SqliteSaver file, AD-11) = Story 7-4 and is NOT implemented here. Rationale: no
compiled graph (Story 3-5) → no real LangGraph checkpointer → cross-restart
resume is not implementable yet (Constrain note, AC6).

Read-only boundary (AD-3): the store is read-only projection — there is no
write/remediation path. At-least-once resume is SAFE because re-running a
read-only investigation has no side-effect to double-apply (AD-3 trace). The
read-only tool registry / CI#1 HARD-FAIL = Story 2-1 (NOT implemented here).
The 5-2 OUTPUT-SIDE remediation-off guard (``_strip_remediation``) runs in
``view`` on the DEEP-COPIED projection — it STRIPS remediation action text (a
read-only strip, NEVER a write, NEVER a synthesis); the stored record is intact.

ONE-WAY (AD-1 / gate #2): stdlib only — does NOT import graph (no state-internals
coupling, AD-2) / routers / adapters / tools. The store is a pure services
data-structure; JSON-safety is enforced at the runner boundary (AD-9).
"""

from __future__ import annotations

import copy
import threading
from dataclasses import dataclass, field
from typing import Any

# Investigation lifecycle status — REGISTRY-LEVEL (NOT a graph-state key, AD-9).
STATUS_RUNNING = "running"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
# Story 5-2 (AD-10 #5): a max-iter-exhausted / inconclusive run ends ``partial`` —
# the run ENDED (honest), NOT a crash to resume. ``partial`` IS terminal, so it is a
# member of ``_TERMINAL`` (it is NOT re-dispatched by ``non_terminal``/resume). The
# dispatcher accepts the runner's honest ``"partial"`` (4-A2 wiring) — it is NOT
# masked as ``failed`` (AD-10 #5 — NOT a silent binary fail). Still REGISTRY-LEVEL:
# add ``status`` ONLY here, NEVER to ``InvestigationState`` (13-key spine, AD-9).
STATUS_PARTIAL = "partial"
# Add `status` ONLY here (registry), NEVER to InvestigationState (13-key spine).
_TERMINAL: frozenset[str] = frozenset({STATUS_SUCCESS, STATUS_FAILED, STATUS_PARTIAL})


@dataclass
class InvestigationRecord:
    """A single investigation's registry record (in-process, AD-10 #3).

    ``status`` is REGISTRY-LEVEL. ``trigger`` is retained for at-least-once resume
    but is NOT part of the read-store ``InvestigationReadView`` projection.
    """

    investigation_id: str
    status: str
    state_snapshot: dict[str, Any]
    report: dict[str, Any] | None = None
    trigger: dict[str, Any] = field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        return self.status in _TERMINAL


@dataclass
class InvestigationReadView:
    """Read-store response projection (AD-10 #3). JSON-safe. Excludes ``trigger``."""

    investigation_id: str
    status: str
    state_snapshot: dict[str, Any]
    report: dict[str, Any] | None = None


def _strip_remediation(report: dict[str, Any] | None) -> dict[str, Any] | None:
    """Force ``report.remediation`` to empty/off at the output projection (AC2 / T9 / D12).

    Story 5-2 — the OUTPUT-SIDE remediation-off guard (defense-in-depth). The POC emits
    NO remediation action text (T9 / D12 — remediation is a prod product decision, §3.8).
    This single read-path chokepoint forces ``report["remediation"]`` to ``[]`` in EVERY
    projected read-view, regardless of what is stored — so the POC output boundary NEVER
    leaks action text, even if a future/prod report carried it. The field stays PRESENT
    (the contract keeps a prod slot) but is emptied.

    READ-ONLY (§3.8 / AD-3): this operates ONLY on the projection (already deep-copied by
    ``InvestigationStore.view``); it NEVER mutates the stored record, NEVER adds a write
    path, and NEVER synthesizes remediation action text (the anti-invention discipline —
    the same muscle as AD-6 on the producer side). A non-dict report (``None`` until the
    rca_writer node runs, or a malformed value) is returned UNCHANGED — a field cannot be
    stripped from a non-dict, and we do not invent structure.
    """
    if not isinstance(report, dict):
        return report
    # T9 / D12: remediation OFF at the output boundary (slot kept, emptied — never invented).
    report["remediation"] = []
    return report


class InvestigationStore:
    """In-memory investigation lifecycle store keyed by ``investigation_id``.

    The dispatcher registers records (``running``), updates them on terminal
    (``success``/``failed``), and the read-store router projects them. The store
    is the resume source (``non_terminal()``) for at-least-once re-dispatch.
    """

    def __init__(self) -> None:
        self._records: dict[str, InvestigationRecord] = {}
        # Guards ``_records`` against torn reads / dict-changed-during-iteration:
        # the background loop thread writes terminals (``set_terminal``/``set_failed``,
        # multi-field updates) while FastAPI request threads read (``view``/``non_terminal``).
        # Individual dict ops are GIL-atomic, but a multi-field terminal update is NOT a
        # single atomic step — a concurrent ``view`` could observe a torn record (new
        # status, old snapshot) without this lock. NOT D8 WAL (that is multi-writer
        # throughput durability, deferred) — this is basic read/write isolation.
        self._lock = threading.RLock()

    def register_running(
        self,
        investigation_id: str,
        trigger: dict[str, Any],
        state_snapshot: dict[str, Any] | None = None,
    ) -> InvestigationRecord:
        """Register a FRESH investigation as ``running``.

        Precondition: no existing record for ``investigation_id`` (the dispatcher's
        idempotent guard calls this only when ``existing is None``). It is NOT a
        general idempotent upsert — re-registering would reset a terminal record.
        """
        record = InvestigationRecord(
            investigation_id=investigation_id,
            status=STATUS_RUNNING,
            state_snapshot=dict(state_snapshot) if state_snapshot is not None else {},
            report=None,
            trigger=dict(trigger),
        )
        with self._lock:
            self._records[investigation_id] = record
        return record

    def set_terminal(
        self,
        investigation_id: str,
        status: str,
        state_snapshot: dict[str, Any] | None,
        report: dict[str, Any] | None,
    ) -> None:
        """Mark an investigation terminal (``success``/``failed``) with its snapshot.

        The whole field update (status + snapshot + report) is one atomic step under
        ``_lock`` so a concurrent ``view`` never sees a half-updated record.
        """
        with self._lock:
            record = self._records.get(investigation_id)
            if record is None:
                return
            record.status = status if status in _TERMINAL else STATUS_FAILED
            if state_snapshot is not None:
                record.state_snapshot = dict(state_snapshot)
            record.report = report

    def set_failed(
        self,
        investigation_id: str,
        state_snapshot: dict[str, Any] | None = None,
    ) -> None:
        """Mark an investigation ``failed`` (NOT silent, AD-10 #5)."""
        with self._lock:
            record = self._records.get(investigation_id)
            if record is None:
                return
            record.status = STATUS_FAILED
            if state_snapshot is not None:
                record.state_snapshot = dict(state_snapshot)

    def get(self, investigation_id: str) -> InvestigationRecord | None:
        with self._lock:
            return self._records.get(investigation_id)

    def non_terminal(self) -> list[InvestigationRecord]:
        """Records still ``running`` — the resume scan source (at-least-once, AC5).

        Snapshots under ``_lock`` so concurrent mutation cannot raise
        ``dict changed size during iteration``.
        """
        with self._lock:
            return [r for r in self._records.values() if not r.is_terminal]

    def view(self, investigation_id: str) -> InvestigationReadView | None:
        """Read-store projection (``None`` → 404 lookup miss). Excludes ``trigger``.

        ``state_snapshot`` and ``report`` are DEEP-copied under ``_lock`` so the
        response never aliases a dict the background loop mutates concurrently. The
        5-2 OUTPUT-SIDE remediation-off guard (``_strip_remediation``) runs on the
        deep-copied ``report`` — every read-view forces ``remediation=[]`` (AC2 / T9),
        so the POC output boundary is NEVER bypassable (the single client-read chokepoint).
        """
        with self._lock:
            record = self._records.get(investigation_id)
            if record is None:
                return None
            return InvestigationReadView(
                investigation_id=record.investigation_id,
                status=record.status,
                state_snapshot=copy.deepcopy(record.state_snapshot),
                # The guard runs on the DEEP-COPIED projection: the stored record is NEVER
                # mutated (read-only strip, §3.8 / AD-3); the output boundary always off.
                report=_strip_remediation(
                    copy.deepcopy(record.report) if record.report is not None else None
                ),
            )

    def __len__(self) -> int:
        with self._lock:
            return len(self._records)

    def __contains__(self, investigation_id: object) -> bool:
        with self._lock:
            return investigation_id in self._records

    def clear(self) -> None:
        """Drop all records (test isolation — in-process store)."""
        with self._lock:
            self._records.clear()


# Module-level default store — the in-process singleton used by the dispatcher
# and the read-store router. Survives across requests/tests within ONE process.
# Cross-restart persistence = SqliteSaver (AD-11) = Story 7-4 (NOT here).
_default_store = InvestigationStore()


def default_store() -> InvestigationStore:
    """Accessor for the in-process default store (dispatcher + read-store router)."""
    return _default_store


def reset_store() -> None:
    """Clear the in-process default store. Tests call this to avoid cross-test leakage."""
    _default_store.clear()


__all__ = [
    "InvestigationReadView",
    "InvestigationRecord",
    "InvestigationStore",
    "STATUS_FAILED",
    "STATUS_PARTIAL",
    "STATUS_RUNNING",
    "STATUS_SUCCESS",
    "default_store",
    "reset_store",
]
