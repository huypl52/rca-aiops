"""incident_context_builder — §3.5 PE-R entry node (Story 1.3 — AD-4 / AD-9 / AD-12).

The **first** node of the Plan-Execute-Reflect workflow (spec §3.5). It reads the
plain-dict `state["trigger"]` (AD-9: state layer holds plain JSON-safe dicts,
Pydantic lives only at the port) and builds the initial investigation context:

    context = {
        "service":        trigger["service"],
        "namespace":      "demo" if namespace in (None, "") else namespace,  # Constrain #4: NO falsy/0 coercion
        "time_window":    {"start": started_at, "end": ends_at},   # end=None when firing (deterministic, AD-12)
        "labels":         labels if isinstance(labels, dict) else {},
        "topology_seed":  {"services": [s for s in affected_services if isinstance(s, str)]},  # non-inventing seed
    }

Contract locks (leader DEEP, first node writing the state spine — sets the
pattern for all 8 nodes):
  - **AD-4 (partial return):** the node returns **only** `{"context": {...}}`.
    LangGraph's `upsert_context` reducer (graph.state, Story 0.3 — REUSED, NOT
    redefined) shallow-merges `{**left, **right}` into `state.context`. The node
    NEVER returns the full 13-key state and NEVER overwrites whole state.
  - **AD-9 (plain JSON-safe state):** input is a plain dict (`state["trigger"]`),
    NOT a Pydantic model. Pydantic is only at the port boundary (api-gateway /
    evidence_normalizer). Every emitted value is JSON-safe (str/dict/list/scalar/
    None); `time_window` values are ISO-8601 **strings**, never `datetime` objs.
  - **AD-12 (pure / deterministic):** no wall-clock (`datetime.now`/`time`), no
    random, no side-effect, no I/O. Same input → same output. Crucially, a
    **firing** trigger (missing `ends_at`) yields `time_window.end = None` — the
    DETERMINISTIC choice. We do NOT use a now-marker (that would break benchmark
    determinism, AD-10 #6). Downstream (executor_router/reflector) owns open-window
    handling.

Scope (Story 1.3): node function + helper ONLY. Does NOT compile the graph
(`StateGraph(...).compile()` = Story 3-5), implement/wire any other node, or
perform real topology exploration (Story 3-4 + tools) — it only **seeds** the
`affected_services` list (non-inventing).

ONE-WAY (AD-1 / gate #2 HARD-FAIL): this module imports `graph.state` (same
layer) + stdlib only. It NEVER imports `routers` / `services` (back-edge
forbidden) and does NOT import `models` — Pydantic lives at the port boundary.
"""

from __future__ import annotations

from collections.abc import Mapping

from graph.state import InvestigationState, JsonValue

# ONE-WAY (AD-1 / gate #2): this module imports `graph.state` (same layer) +
# stdlib only. It does NOT import `routers` / `services` (back-edge forbidden),
# and does NOT wrap the trigger into a Pydantic model — the trigger dict shape is
# ⊆ IncidentTrigger.model_dump() (§3.4, 18 fields + incident_id), kept as a plain
# dict per AD-9 (Pydantic only at the port boundary).

_DEFAULT_NAMESPACE: str = "demo"
"""POC single-tenant namespace default (spec §3.4 "namespace default hiện là demo")."""


def build_incident_context(trigger: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    """Build the investigation context dict from a plain trigger dict (AD-9).

    Pure + deterministic (AD-12): no wall-clock/random/side-effect; same input →
    same output. Reads defensive ``.get`` for optional/defensive keys (graceful,
    never crashes on a firing trigger missing ``ends_at`` / ``namespace``).

    Args:
        trigger: plain dict, shape ⊆ ``IncidentTrigger.model_dump()`` (§3.4,
            18 fields + incident_id). NOT a Pydantic model (AD-9).

    Returns:
        context dict with keys ``service`` / ``namespace`` / ``time_window`` /
        ``labels`` / ``topology_seed`` — all JSON-safe (AD-9).
    """
    service = trigger.get("service")
    namespace = trigger.get("namespace")
    # §3.4 default: namespace defaults to "demo" ONLY when absent (None) OR an
    # empty-string. We deliberately do NOT coerce falsy non-strings (0 / False /
    # []) into "demo" — that would mask upstream bugs (leader Constrain #4:
    # "chỉ default khi absent/empty-string"). At a well-formed port the namespace
    # is always a str, so this branch only fires on the absent/"" edge.
    if namespace is None or namespace == "":
        namespace = _DEFAULT_NAMESPACE

    started_at = trigger.get("started_at")
    # §3.4 row 14: ends_at is None while still firing. We LOCK None (deterministic,
    # AD-12) — NEVER a now-marker (datetime.now would break benchmark determinism).
    ends_at = trigger.get("ends_at")

    labels = trigger.get("labels")
    if not isinstance(labels, dict):
        labels = {}

    affected_services = trigger.get("affected_services")
    # Non-inventing topology seed: copy the affected_services list only. Real
    # topology/edge exploration is Story 3-4 (+ tools) — we do NOT fabricate
    # edges/nodes/dependencies here.
    if not isinstance(affected_services, list):
        affected_services_list: list[JsonValue] = []
    else:
        affected_services_list = [s for s in affected_services if isinstance(s, str)]

    return {
        "service": service,
        "namespace": namespace,
        "time_window": {
            "start": started_at,
            "end": ends_at,
        },
        "labels": dict(labels),
        "topology_seed": {
            "services": affected_services_list,
        },
    }


def incident_context_builder(state: InvestigationState) -> dict[str, JsonValue]:
    """§3.5 entry node — build ``state.context`` from ``state["trigger"]``.

    Reads the plain-dict trigger (AD-9), builds the context via
    :func:`build_incident_context`, and returns **PARTIAL** state
    ``{"context": {...}}`` (AD-4). The ``upsert_context`` reducer (graph.state,
    Story 0.3 — REUSED) merges it into ``state.context``.

    Pure + deterministic (AD-12): same input → same output; no wall-clock/random/
    side-effect/I/O; does NOT mutate the input ``state``.

    Args:
        state: partial ``InvestigationState`` — must carry a ``trigger`` dict
            (AD-9 plain dict, shape ⊆ ``IncidentTrigger.model_dump()``).

    Returns:
        partial state ``{"context": {...}}`` (exactly one key — AD-4).
    """
    trigger = state["trigger"]
    return {"context": build_incident_context(trigger)}
