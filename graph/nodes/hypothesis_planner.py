"""hypothesis_planner — §3.5 PE-R node (Story 3.2 — FR-4 / AD-4 / AD-12).

The **third** §3.5 node (after `incident_context_builder` 1.3 + `preplanning_playbook_retriever` 3.1).
It is a **PURE PLANNING** node: it consumes state (`context` + `playbook_hits` + `evidence` gathered
so far) and EMITS a candidate hypothesis list. Each hypothesis is a **PLAN** (a description of
evidence to gather), NOT an action — it makes NO `ReadOnlyAdapterPort` call (unlike 3-1) and does NOT
touch `executor_router`. The read-only EXECUTION gate is downstream (`plan_validator` 3.3 +
`executor_router` 3.5).

LOCKED mechanism (do NOT redesign):
  1. **DI seam = a node FACTORY over an injected hypothesis-content SOURCE (graph-internal).**
     `build_hypothesis_planner(source, *, max_hypotheses)` returns a node
     `(state) -> {"hypotheses": [...]}` closing over `source` + `max_hypotheses`. Mirrors the 1-3 /
     3-1 factory convention. The `source` is a pure-Python **graph-internal** `Protocol`
     (`HypothesisSource`, defined here — NO external dep): signature
     `(context, playbook_hits, evidence) -> list[descriptor WITHOUT id]`. POC default = a
     DETERMINISTIC rule-based source. Per AD-10 an LLM source is the *designated swappable*
     non-determinism point, wired at the composition root (3-5/app) or Epic 7 (**DEFERRED**). Tests
     inject deterministic sources (offline, AD-12).
  2. **AC2 — deterministic IDs stamped BY THE NODE (not the source).** IDs are sequential `H01,
     H02, …` (2-digit zero-padded, format `"H%02d"`). The node assigns `id` by **enumerating the
     source output**; the source emits descriptors WITHOUT `id`. This guarantees deterministic IDs
     regardless of source impl (rule-based OR LLM). NOT random, NOT hash, NOT wall-clock.
     (AST-proven: no `random`, no `time`/`datetime`, no `uuid` in this module.)
  3. **Shape discipline — each item is EXACTLY `{id, priority, plan, status}`** (state key #6 /
     spec AC1). The node normalizes each source descriptor to these **4 keys** — no invented fields,
     no timestamp (same discipline as 3-1's `{id,score,title}`). The hypothesis claim/statement rides
     **inside `plan`** (a JSON-safe `dict[str, JsonValue]`); the `plan` internal fields, the
     `priority` scale, and the `status` enum values are **DEFERRED** (lock the keys EXIST + are
     JSON-safe; defer the values).
  4. **AC1 — REUSE `upsert_hypotheses` (0-3); do NOT reimplement merge/dedupe.** The node returns
     `{"hypotheses": [...]}` (a list); the reducer upserts by `id` (matching → replace-in-place,
     position stable; new → append; `left` always preserved). "replan KHÔNG mất hypothesis cũ" is
     **GUARANTEED by the reducer**, NOT by the node — the node does NOT read prior
     `state.hypotheses` to preserve them. (With a deterministic source, replan reproduces stable
     hypotheses; genuinely new ones append via the reducer.)
  5. **Graceful degrade (Constraint 5) — NEVER raises into the graph.** Missing/empty `context` /
     `playbook_hits` / `evidence`, a source raise, OR malformed state → `{"hypotheses": []}`. The
     planner proceeds; it never blocks the investigation. The source call is wrapped defensively
     (`except Exception → {"hypotheses": []}`), exactly like 3-1 wraps `adapter.search_playbook`.
  6. **AD-4 partial state — return EXACTLY one key `{"hypotheses": [...]}`.** No invented keys.

Scope (Story 3.2): node + factory + graph-internal seam + default deterministic source ONLY. Does
NOT compile the graph (3.5), validate plans (3.3 — that is the read-only gate), wire
`executor_router` (3.5), normalize `Evidence` (4.x), or decide sufficiency (4.x `reflector`).

ONE-WAY (AD-1 / gate #2 HARD-FAIL): imports `graph.state` (same layer) + stdlib ONLY. The
`HypothesisSource` seam is **graph-internal**. **CRITICAL DIFFERENCE from 3-1: hypothesis_planner
imports NO `tools.port`** — it has no adapter call. So `lint-imports` shows this node importing ONLY
`graph.state` + stdlib (NO forward edge to `tools/`). NEVER `routers`/`services`/`adapters`/
`models`/`tools` (back-edge forbidden). It does NOT construct `Evidence` (4.x boundary held).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Protocol

from graph.state import InvestigationState, JsonValue

# ONE-WAY (AD-1 / gate #2): graph.state (same layer) + stdlib ONLY. NO tools.port (unlike 3-1 —
# this node has no adapter call). NEVER routers/services/adapters/models/tools (back-edge forbidden).

_DEFAULT_MAX_HYPOTHESES: int = 5
"""POC cap on emitted hypotheses. The MECHANISM (cap) is locked; the NUMBER is **deferred** to the
hypothesis-quality benchmark (SM-4, Epic 6 eval axis). ``max_hypotheses`` is an injected factory
parameter; this is only the offline-test POC default, NOT a tuned final value."""

_DEFAULT_PRIORITY: int = 1
"""POC deterministic priority for a freshly-planned hypothesis. The priority SCALE (1..N ordering
semantics + tie-break) is **DEFERRED** (a 3.3/4.x concern). This is a stable placeholder, not a
tuned value."""

_DEFAULT_STATUS: str = "proposed"
"""POC deterministic status for a freshly-planned hypothesis (awaiting `plan_validator` 3.3). The
status ENUM vocabulary is **DEFERRED**; ``"proposed"`` is a stable, self-describing placeholder."""


class HypothesisSource(Protocol):
    """Graph-internal seam for hypothesis-content generation (pure-Python, NO external dep).

    This is the **designated swappable non-determinism point** (AD-10): the POC default
    (:func:`_rule_based_source`, this module) is a deterministic pure function; the real LLM source
    is wired at the composition root (3-5/app) or Epic 7 (**DEFERRED**). Tests inject deterministic
    sources (offline, AD-12).

    Signature: ``(context, playbook_hits, evidence) -> list[descriptor]``. Each descriptor is a
    JSON-safe dict carrying the hypothesis CONTENT (``priority``/``plan``/``status``) but WITHOUT an
    ``id`` — the NODE stamps the deterministic sequential id (AC2). This keeps id assignment
    deterministic regardless of source impl (rule-based OR LLM).
    """

    def __call__(
        self,
        context: Mapping[str, JsonValue],
        playbook_hits: Sequence[Mapping[str, JsonValue]],
        evidence: Sequence[Mapping[str, JsonValue]],
    ) -> list[dict[str, JsonValue]]: ...


def _rule_based_source(
    context: Mapping[str, JsonValue],  # noqa: ARG001 — deterministic; consumed by the real source
    playbook_hits: Sequence[Mapping[str, JsonValue]],
    evidence: Sequence[Mapping[str, JsonValue]],  # noqa: ARG001 — deterministic; consumed at 4.x/LLM
) -> list[dict[str, JsonValue]]:
    """DETERMINISTIC POC default source (AD-12): emit one hypothesis per playbook hint.

    Pure function of its inputs — no wall-clock/random/LLM. The playbooks retrieved at preplanning
    (3-1) are CONTEXT HINTS for the planner (FR-3); each playbook hint becomes one candidate
    hypothesis whose ``plan`` references the playbook. This is the **minimal** rule set — the FULL
    generator rule content (which `canonical_trigger`/service → which hypotheses) is **DEFERRED**
    (lock the seam EXISTS as a deterministic pure function; do NOT over-build the rule set).

    ``context`` + ``evidence`` are accepted for forward-compatibility (the real LLM source consumes
    the service + evidence gathered so far) but are intentionally unused here, keeping this default
    deterministic + minimal. Each descriptor carries ``priority``/``plan``/``status`` and NO ``id``
    (the node stamps it).
    """
    # Defensive: only Mapping hits with content contribute (non-inventing — we never fabricate a
    # playbook id/title; we only forward what the retriever handed us).
    out: list[dict[str, JsonValue]] = []
    for pb in playbook_hits:
        if not isinstance(pb, Mapping):
            continue
        out.append(
            {
                "priority": _DEFAULT_PRIORITY,
                "plan": {
                    "playbook_id": pb.get("id"),
                    "playbook_title": pb.get("title"),
                },
                "status": _DEFAULT_STATUS,
            }
        )
    return out


def _stamp_ids(
    descriptors: Sequence[Mapping[str, JsonValue]], *, max_hypotheses: int
) -> list[JsonValue]:
    """Stamp deterministic sequential ids ``H01..`` + normalize to exactly the 4 hypothesis keys.

    The NODE (not the source) owns the id — **enumeration guarantees determinism regardless of
    source impl** (rule-based OR LLM). Each item is normalized to EXACTLY ``{id, priority, plan,
    status}`` (state key #6 / spec AC1): no invented fields, no timestamp. ``plan`` is coerced to a
    JSON-safe dict when the descriptor omits/garbles it; missing ``priority``/``status`` fall back
    to the deterministic POC defaults. Capped at ``max_hypotheses`` (POC; number DEFERRED).

    Returns ``list[JsonValue]`` (each item a ``dict[str, JsonValue]``) so the value is a valid
    ``JsonValue`` for the node's ``dict[str, JsonValue]`` return (lists are invariant in mypy).
    """
    hypotheses: list[JsonValue] = []
    for idx, desc in enumerate(descriptors, start=1):
        if idx > max_hypotheses:
            break
        priority: JsonValue = _DEFAULT_PRIORITY
        plan: dict[str, JsonValue] = {}
        status: JsonValue = _DEFAULT_STATUS
        if isinstance(desc, Mapping):
            p = desc.get("priority")
            if p is not None:
                priority = p
            pl = desc.get("plan")
            if isinstance(pl, Mapping):
                plan = dict(pl)
            s = desc.get("status")
            if isinstance(s, str) and s:
                status = s
        item: dict[str, JsonValue] = {
            "id": f"H{idx:02d}",
            "priority": priority,
            "plan": plan,
            "status": status,
        }
        hypotheses.append(item)
    return hypotheses


def build_hypothesis_planner(
    source: HypothesisSource = _rule_based_source,
    *,
    max_hypotheses: int = _DEFAULT_MAX_HYPOTHESES,
) -> Callable[[InvestigationState], dict[str, JsonValue]]:
    """Factory: build the §3.5 hypothesis_planner node over an injected hypothesis-content source.

    Returns a node ``(state) -> {"hypotheses": [...]}`` closing over ``source`` + ``max_hypotheses``.
    This is the dependency-injection seam: tests inject a deterministic source (offline, AD-12);
    Story 3.5 / app composition injects the real (LLM) source (live stack = Epic 7, DEFERRED).

    The node:
      - reads ``state["context"]`` / ``state["playbook_hits"]`` / ``state["evidence"]`` defensively;
      - calls the injected ``source(context, playbook_hits, evidence)`` DIRECTLY (NOT
        ``executor_router`` — 3.2 is a pure planning node; execution is 3.3/3.5);
      - stamps deterministic sequential ids ``H01..`` by enumeration (AC2) and normalizes each item
        to EXACTLY ``{id, priority, plan, status}`` (shape discipline);
      - returns ``{"hypotheses": [...]}``; the 0-3 ``upsert_hypotheses`` reducer merges (NO node
        merge/dedupe — replan preserves prior hypotheses, GUARANTEED by the reducer);
      - degrades gracefully (missing/empty inputs / source raise / malformed state →
        ``{"hypotheses": []}``) and NEVER raises into the graph (Constraint 5).

    Args:
        source: a ``HypothesisSource`` (graph-internal seam). Defaults to the deterministic
            rule-based POC source (:func:`_rule_based_source`). The real LLM source is DEFERRED
            (3-5/app, Epic 7).
        max_hypotheses: cap on emitted hypotheses (POC default 5; the number is DEFERRED to SM-4).

    Returns:
        a §3.5 node returning PARTIAL state ``{"hypotheses": [...]}`` (AD-4 — exactly one key).
    """

    def hypothesis_planner(state: InvestigationState) -> dict[str, JsonValue]:
        # Defensive reads — nodes receive PARTIAL state and MUST NOT crash on missing/wrong-typed
        # keys (Constraint 5). Each input is narrowed to a well-typed value before the source call.
        context = state.get("context")
        if not isinstance(context, Mapping):
            context = {}

        raw_playbook_hits = state.get("playbook_hits")
        if isinstance(raw_playbook_hits, list):
            pb_hits: list[Mapping[str, JsonValue]] = [
                h for h in raw_playbook_hits if isinstance(h, Mapping)
            ]
        else:
            pb_hits = []

        raw_evidence = state.get("evidence")
        if isinstance(raw_evidence, list):
            ev: list[Mapping[str, JsonValue]] = [e for e in raw_evidence if isinstance(e, Mapping)]
        else:
            ev = []

        # Constraint 5 — never raise into the graph: the default source is pure/deterministic and
        # never raises, but an injected source might; we wrap defensively and degrade. (Mirrors
        # 3-1's defensive wrap of adapter.search_playbook.)
        try:
            descriptors = source(context, pb_hits, ev)
        except Exception:  # noqa: BLE001 — ANY source failure → graceful degrade (never raises)
            return {"hypotheses": []}

        if not isinstance(descriptors, list):
            return {"hypotheses": []}

        return {"hypotheses": _stamp_ids(descriptors, max_hypotheses=max_hypotheses)}

    return hypothesis_planner


__all__ = ["HypothesisSource", "build_hypothesis_planner"]
