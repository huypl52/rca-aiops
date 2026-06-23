"""preplanning_playbook_retriever — §3.5 PE-R node (Story 3.1 — FR-3 / AD-4 / AD-12).

The **second** §3.5 node (after `incident_context_builder`, 1.3). It runs ONCE at preplanning to
retrieve top-K playbooks and seed the `playbook_hits` state key with **hints** for the hypothesis
planner (Story 3.2). Playbooks are **context hints, NOT the source of truth** — hypotheses are still
decided by the planner + evidence (AC3).

LOCKED mechanism (do NOT redesign):
  1. **DI seam = a node FACTORY over the LOCKED `ReadOnlyAdapterPort`.** This is the FIRST node with
     an injected read-only source dependency. `build_preplanning_playbook_retriever(adapter, *,
     top_k)` returns a node `(state) -> {"playbook_hits": [...]}` closing over `adapter` + `top_k`.
     Tests inject the `StubReadOnlyAdapter` (2-1) / `CompositeReadOnlyAdapter` (2-2); real adapter
     wiring = 3-5/app composition root.
  2. **Call the adapter DIRECTLY — NOT through `executor_router`.** The node calls
     `adapter.search_playbook(query=..., top_k=top_k)`. The `executor_router` NODE-wiring is Story
     3.5 (the generic evidence-gathering tool loop); 3.1 is a dedicated preplanning step that runs
     ONCE before the loop and is NOT a dedupable evidence-loop tool dispatch.
  3. **Query is DETERMINISTIC** (AD-12): built purely from `state["trigger"]["canonical_trigger"]`
     (primary) + `state["context"]["service"]` (scope) — pure string construction, NO LLM, NO
     wall-clock, NO randomness.
  4. **Graceful degrade (AC2) — NEVER raises, NEVER blocks.** Missing/None `canonical_trigger`, empty
     hits, the adapter error envelope, OR an adapter exception → `{"playbook_hits": []}`. The planner
     then proceeds with evidence only.
  5. **Forward the adapter hit — do NOT invent fields, do NOT add a timestamp (AD-12).** Each
     `playbook_hits` item is `{"id", "score", "title"}` (the QdrantAdapter hit shape, 2-2). No
     `retrieved_at`/wall-clock (benchmark determinism).
  6. **REUSE the existing reducer — do NOT reimplement dedupe.** `playbook_hits` already has its
     `append_dedupe_playbook_hits` reducer from Story 0-3 (whole-item JSON identity). The node just
     RETURNS the hits list; the reducer dedupes.

Scope (Story 3.1): node + factory + helpers ONLY. Does NOT compile the graph (3.5), plan
hypotheses (3.2), validate plans (3.3), promote hits to evidence (4.x), or wire the composition
root (3.5/app).

ONE-WAY (AD-1 / gate #2): imports `graph.state` (same layer) + `tools.port` (FORWARD edge: graph
idx2 → tools idx4, ALLOWED — this is the FIRST graph node to import `tools.port`; verified green by
`uv run lint-imports`) + stdlib only. NEVER imports `routers`/`services`/`adapters`/`models`
(back-edge forbidden). It does NOT construct `Evidence` (4.2 boundary held).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from graph.state import InvestigationState, JsonValue
from tools.port import ReadOnlyAdapterPort

# ONE-WAY (AD-1 / gate #2): graph.state (same layer) + tools.port (FORWARD: graph idx2 → tools
# idx4, allowed) + stdlib only. NEVER routers/services/adapters/models (back-edge forbidden).

_DEFAULT_TOP_K: int = 5
"""POC default for the top-K retrieval count.

The MECHANISM (top-K retrieval) is locked; the NUMBER is **deferred to the retrieval-quality
benchmark (D3 / SM-4, Epic 6 eval axis)** — retrieval is an independent eval axis (A6). `top_k` is
an injected factory parameter; this is only the offline-test POC default, NOT a tuned final value.
"""


def _build_query(state: InvestigationState) -> str | None:
    """Build a DETERMINISTIC retrieval query from the trigger + context (AD-12).

    Primary signal: ``state["trigger"]["canonical_trigger"]`` (PascalCase domain trigger, §3.4
    field #4). Scope signal: ``state["context"]["service"]`` (from incident_context_builder, 1.3)
    when present. Pure string construction — no LLM / wall-clock / random (AD-12).

    Returns ``None`` when ``canonical_trigger`` is missing/None/empty/non-str → the caller degrades
    gracefully (AC2: no retrieval, empty ``playbook_hits``, planner proceeds with evidence only).

    Reads defensive ``.get`` + ``isinstance`` everywhere — nodes receive PARTIAL state and MUST NOT
    crash on a malformed trigger/context (Constraint 5).
    """
    trigger = state.get("trigger")
    if not isinstance(trigger, Mapping):
        return None
    canonical = trigger.get("canonical_trigger")
    if not isinstance(canonical, str) or not canonical:
        return None

    context = state.get("context")
    service: str | None = None
    if isinstance(context, Mapping):
        svc = context.get("service")
        if isinstance(svc, str) and svc:
            service = svc

    # Deterministic query template: "<canonical_trigger>" [+ " service:<service>"].
    # Traceable + stable; the adapter (QdrantAdapter) treats it as an opaque search string.
    if service is not None:
        return f"{canonical} service:{service}"
    return canonical


def _extract_hits(raw: Mapping[str, object]) -> list[JsonValue]:
    """Forward the adapter's hit list as ``playbook_hits`` items — NO invented fields, NO timestamp.

    Adapter success shape (QdrantAdapter, 2-2):
        ``{"source_type": "playbook", "query": ..., "top_k": ..., "hits": [{"id","score","title"}]}``
    Adapter error envelope (transport/backend failure, 2-2): contains an ``"error"`` key → degrade.

    Each forwarded item is exactly ``{"id", "score", "title"}`` (the hit's own fields). We do NOT
    invent fields and do NOT add a timestamp (AD-12 — benchmark determinism). Missing/non-list
    ``hits`` OR an error envelope → ``[]`` (graceful degrade, AC2).

    Returns ``list[JsonValue]`` (each item is a ``dict[str, JsonValue]``) so the value is a valid
    ``JsonValue`` for the node's ``dict[str, JsonValue]`` return (lists are invariant in mypy).
    """
    if "error" in raw:  # adapter error envelope (transport_error / backend_error) → degrade
        return []
    hits_val = raw.get("hits")
    if not isinstance(hits_val, list):
        return []
    forwarded: list[JsonValue] = []
    for hit in hits_val:
        if isinstance(hit, Mapping):
            item: dict[str, JsonValue] = {
                "id": hit.get("id"),
                "score": hit.get("score"),
                "title": hit.get("title"),
            }
            forwarded.append(item)
    return forwarded


def build_preplanning_playbook_retriever(
    adapter: ReadOnlyAdapterPort,
    *,
    top_k: int = _DEFAULT_TOP_K,
) -> Callable[[InvestigationState], dict[str, JsonValue]]:
    """Factory: build the §3.5 preplanning_playbook_retriever node over an injected adapter.

    Returns a node ``(state) -> {"playbook_hits": [...]}`` that closes over ``adapter`` + ``top_k``.
    This is the dependency-injection seam: tests inject the deterministic stub/composite adapter
    (offline, AD-12); Story 3.5 / app composition injects the real adapter (live stack = Epic 7).

    The node:
      - builds a deterministic query from ``trigger.canonical_trigger`` (+ context.service);
      - calls ``adapter.search_playbook`` DIRECTLY (NOT through ``executor_router`` — 3.1 is a
        dedicated preplanning step, not a dedupable evidence-loop dispatch);
      - forwards the hits to ``playbook_hits`` (the 0-3 ``append_dedupe_playbook_hits`` reducer
        dedupes — NO node-local dedupe);
      - degrades gracefully (missing trigger / error envelope / empty hits / adapter raise →
        ``{"playbook_hits": []}``) and NEVER raises into the graph (Constraint 5 / AC2).

    Args:
        adapter: a ``ReadOnlyAdapterPort`` (the LOCKED read-only source seam, 2-1). The node can
            only READ through it — the port exposes NO write method (AD-3).
        top_k: top-K retrieval count (POC default 5; the tuned number is DEFERRED to D3/SM-4).

    Returns:
        a §3.5 node returning PARTIAL state ``{"playbook_hits": [...]}`` (AD-4 — exactly one key).
    """

    def preplanning_playbook_retriever(state: InvestigationState) -> dict[str, JsonValue]:
        query = _build_query(state)
        if query is None:
            # Missing/None/empty canonical_trigger → graceful degrade (AC2): no retrieval, planner
            # proceeds with evidence only. Never raises.
            return {"playbook_hits": []}

        # Constraint 5 — never raise into the graph: the adapter (2-2) folds transport/backend
        # failures into an error envelope (never raises), but we wrap defensively so an unexpected
        # adapter exception still degrades to empty hits instead of crashing the graph.
        try:
            raw = adapter.search_playbook(query=query, top_k=top_k)
        except Exception:  # noqa: BLE001 — ANY adapter failure → graceful degrade (never raises)
            return {"playbook_hits": []}

        return {"playbook_hits": _extract_hits(raw)}

    return preplanning_playbook_retriever


__all__ = ["build_preplanning_playbook_retriever"]
