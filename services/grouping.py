"""Incident grouping service — H3 1-trigger-1-investigation + idempotent trigger_id (FR-2 / DEC-1 / AD-10 #1).

Lives in the services layer (AD-1 one-way: routers → services → models). WRAPS the
Story 1-1 normalizer output: ingest → `normalize_*` (IncidentTrigger, commit e183d86)
→ **group** → HTTP `202 + {investigation_id}` (the router upgrade over 1-1's
`200 + IncidentTrigger` echo). It does NOT reimplement normalization — it consumes
the validated `IncidentTrigger` and turns it into an idempotent Investigation handle.

What "grouping" means in H3 POC (FR-2 / DEC-1):
  - **1-trigger-1-investigation:** each `IncidentTrigger` opens exactly ONE
    Investigation. There is NO multi-trigger merge rule here — that is H2, prod-only
    (see Constrain D9 below). "Grouping" in POC = idempotency + 1:1, NOT a merge rule.
  - **Idempotent on `trigger_id` (AD-10 #1, KEY):** re-sending the same `trigger_id`
    (Alertmanager retry / dedupe) returns the SAME `investigation_id` and opens NO new
    Investigation. The dedupe key is `IncidentTrigger.trigger_id` (fingerprint/UID,
    already normalized by Story 1-1).
  - **`incident_id == investigation_id` (H3 POC contract lock):** the §3.4 H3 add-on
    `IncidentTrigger.incident_id` (optional since Story 0-2, commit 7592e4c) is set to
    the investigation_id at grouping time. POC is 1:1:1 trigger→incident→investigation,
    so a single grouping identifier is used — we do NOT invent two separate ids.

Constrain — D9 (real H2 grouping rule = prod-only, NOT implemented here):
  There is no rule that merges several triggers into one incident. Agent/graph logic
  is INDEPENDENT of the grouping rule: the compiled graph must run correctly whether
  the contract later moves to H2 (prod) or stays H3 (POC). This story only locks the
  H3 POC contract (idempotency + 1:1 + incident_id=investigation_id).

Scope boundary (locked 1-2 vs 1-4 vs 3-5 — do NOT cross):
  - This service RECORDS the `trigger_id → investigation_id` mapping in an in-memory
    registry and returns the investigation_id. That is all.
  - Async/background worker execution loop, read-store `GET /api/investigations/{id}`
    (poll/SSE), and checkpoint/resume (AD-10 #2-4, AD-11) = Story 1-4.
  - Compiled graph / node execution (AD-2) = Story 3-5.
  - Cross-restart persistence of the registry = checkpoint store (1-4 / 7-4); here the
    registry is in-memory and idempotency must hold within ONE process (proven by test).

Note on persistence: `group()` sets `incident_id` on the `IncidentTrigger` object (H3
contract statement), but the full trigger is NOT persisted in this registry — the
registry stores only the `trigger_id → investigation_id` mapping for idempotency.
Persisting `state.trigger` is graph state/checkpoint (Story 1-3 / 3-5 / 1-4).
"""

from __future__ import annotations

import uuid

from models import IncidentTrigger

# investigation_id format: UUID v4 string. `investigation_id` = run id per the spine
# Naming convention. Idempotency is achieved by registry LOOKUP on `trigger_id`, so a
# random (non-deterministic) id is fine — the dedupe key is the trigger_id, not the id.


class InvestigationRegistry:
    """In-memory idempotency store: `trigger_id → investigation_id` (1:1, H3 POC).

    The registry is the idempotency mechanism for AD-10 #1. It maps each distinct
    `trigger_id` to exactly one `investigation_id` (1:1), so a re-send of the same
    trigger_id returns the same investigation_id and does not mint a new one.

    POC = in-memory (single process). Cross-restart persistence = checkpoint store
    (Story 1-4 / 7-4) and is NOT implemented here.
    """

    def __init__(self) -> None:
        # trigger_id -> investigation_id. Insertion-ordered; 1:1 (no overwrite).
        self._by_trigger_id: dict[str, str] = {}

    def get_or_open(self, trigger_id: str) -> str:
        """Return the investigation_id for `trigger_id`, minting one on first sight.

        Idempotent (AD-10 #1): a trigger_id seen before returns its existing
        investigation_id and does NOT mint a new one. A brand-new trigger_id mints a
        fresh investigation_id (UUID v4) and records the mapping.

        Note: this lookup-then-mint is NOT atomic under concurrent sync-threadpool
        requests (the POC contract is serial/retry re-send dedupe within one process,
        proven by serial tests; true concurrency safety belongs to the async worker,
        Story 1-4).
        """
        existing = self._by_trigger_id.get(trigger_id)
        if existing is not None:
            return existing
        investigation_id = str(uuid.uuid4())
        self._by_trigger_id[trigger_id] = investigation_id
        return investigation_id

    def investigation_id_for(self, trigger_id: str) -> str | None:
        """Lookup-only (no mint). Returns None if the trigger_id has never been seen."""
        return self._by_trigger_id.get(trigger_id)

    def __len__(self) -> int:
        return len(self._by_trigger_id)

    def __contains__(self, trigger_id: object) -> bool:
        return trigger_id in self._by_trigger_id

    def clear(self) -> None:
        """Drop all mappings. Used for test isolation (in-process registry)."""
        self._by_trigger_id.clear()


# Module-level default registry — the in-process singleton used by the ingest router.
# Idempotency holds within ONE process: re-sending the same trigger_id (even across
# HTTP requests in the same process) returns the same investigation_id.
_default_registry = InvestigationRegistry()


def default_registry() -> InvestigationRegistry:
    """Accessor for the in-process default registry (used by tests for runtime proof)."""
    return _default_registry


def reset_registry() -> None:
    """Clear the in-process default registry. Tests call this to avoid cross-test leakage."""
    _default_registry.clear()


def group(trigger: IncidentTrigger) -> str:
    """Open (idempotently) the Investigation for `trigger` and return its investigation_id.

    H3 POC grouping (FR-2 / DEC-1 / AD-10 #1):
      - Idempotent on `trigger.trigger_id`: same trigger_id → same investigation_id,
        NO new Investigation (registry lookup, no mint on re-send).
      - 1:1: one trigger_id maps to exactly one investigation_id.
      - Sets `trigger.incident_id = investigation_id` (H3 POC contract: incident_id and
        investigation_id are the same grouping identifier; do NOT invent a second id).

    Does NOT merge multiple triggers (H2 = prod D9). Does NOT run the graph, dispatch
    a worker, write a read-store, or persist a checkpoint (those are Stories 1-4 / 3-5).
    """
    investigation_id = _default_registry.get_or_open(trigger.trigger_id)
    # H3 POC contract lock: incident_id == investigation_id (single grouping identifier).
    trigger.incident_id = investigation_id
    return investigation_id


__all__ = [
    "InvestigationRegistry",
    "default_registry",
    "group",
    "reset_registry",
]
