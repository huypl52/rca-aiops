"""InvestigationState — graph state spine (Story 0.3 — AD-9 / AD-4 / AD-10).

`InvestigationState` is a **plain JSON-safe `TypedDict`** carrying the 13
top-level keys of the AD-9 spine. Pydantic models live **only at the port**
(`models.IncidentTrigger` §3.4, `models.Evidence` §3.6 — Story 0.2); the state
never wraps itself in Pydantic (AD-9 rule 1). Nested state shape is a *subset*
of the port contract — enforced by CI gate #3 (AD-13 #3): shape ⊆ port
field-set + serialize→deserialize round-trip deep-equal.

Reducer semantics (AD-4) are wired via the LangGraph `Annotated[<type>,
<reducer>]` idiom:
  - `evidence` / `tool_calls` / `playbook_hits` → append + dedupe (idempotent)
  - `hypotheses`               → upsert by id
  - `context`                  → upsert (merge dict)
  - `safety_flags`             → append/merge (shallow merge; flag value-shape deferred)
  - scalar `plan` / `sufficiency` / `next_action` → replace (LangGraph default
    overwrite — these keys are NOT annotated)
  - set-once `schema_version` / `incident_id` / `trigger` / `report` → default
    overwrite, set once in the run lifecycle.

Dedupe keys:
  - `tool_calls` = `(tool, query, timestamp_range)` (AD-10)
  - `evidence`   = `(source_name, query, timestamp_range)` (project-context L93)
  - `playbook_hits` = whole-item JSON identity (no field locked → exact-dup drop)

Nodes return **partial** state (`TypedDict(total=False)`); the reducer merges,
nodes never overwrite whole state (AD-4). All reducers are **pure** and
**deterministic** (no side-effect, no wall-clock/random — AD-12 spirit).

Scope (Story 0.3): state definition + reducers + factory ONLY. This module does
NOT compile the graph (`StateGraph(...).compile()` = Story 3-5), implement any
of the 8 §3.5 nodes (Epic 1/3/4/5), or wire consumers (routers ingest = 1-1).
One-way (AD-1): imports `models` (port) + `ci.contract_schema` (non-layer) +
3rd-party/stdlib only — never `routers`/`services` (gate #2 KEPT).
"""

from __future__ import annotations

import json
from collections.abc import Hashable, Mapping
from typing import Annotated, Any, TypedDict

# --- JSON-safe value type (encodes the AD-9 "plain JSON-safe dicts" invariant) ---
# Recursive alias: every state value is a JSON primitive or a JSON container of
# JSON values — never a `datetime`/`set`/custom object (those break the JSON-safe
# invariant, caught by gate #3 via stdlib `json.dumps`).
type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]

# The state schema version. Bumped only on an intentional, breaking state-shape
# change. Resume reads it and fail-fasts on mismatch (AD-9 rule 4) — we do NOT
# silently migrate the POC schema.
SCHEMA_VERSION: int = 1


def assert_schema_version(state: Mapping[str, object], expected: int = SCHEMA_VERSION) -> None:
    """Fail-fast if ``state["schema_version"] != expected`` (AD-9 rule 4).

    Raises ``ValueError`` on mismatch — resume never silently migrates the POC
    state schema (mechanism lock; migration strategy is deferred).
    """
    actual = state.get("schema_version")
    if actual != expected:
        raise ValueError(
            f"InvestigationState schema_version mismatch: state has {actual!r}, "
            f"expected {expected!r} — fail-fast (AD-9), refusing silent POC migration."
        )


# ---------------------------------------------------------------------------
# Reducer helpers (pure, deterministic)
# ---------------------------------------------------------------------------

# A reduced collection item is always a JSON dict (Evidence/ToolCall/Hypothesis
# are stored as their `.model_dump()` dicts at the port boundary).
type _Item = dict[str, JsonValue]


def _json_key(value: object) -> Hashable:
    """Project any JSON-safe value onto a deterministic hashable key.

    Used to dedupe items whose identity is a composite/structured value (e.g. a
    nested ``timestamp_range`` dict). Deterministic (sorted keys) so the same
    logical value always keys identically.
    """
    if isinstance(value, Mapping):
        return ("__d__", json.dumps(dict(value), sort_keys=True, ensure_ascii=False))
    if isinstance(value, list):
        return ("__l__", tuple(_json_key(v) for v in value))
    if isinstance(value, bool | int | float | str) or value is None:
        return value
    # Unknown (non-JSON-safe) value — fall back to its string form so the reducer
    # stays total; the JSON-safe invariant is enforced separately by gate #3.
    return repr(value)


def _field(item: Mapping[str, object], key: str) -> object:
    """Read ``item[key]`` defensively (``None`` if absent)."""
    return item.get(key)


def _dedupe_key_evidence(item: Mapping[str, object]) -> tuple[Hashable, ...]:
    """Evidence identity = ``(source_name, query, timestamp_range)``.

    project-context.md L93 ground truth.
    """
    return (
        _json_key(_field(item, "source_name")),
        _json_key(_field(item, "query")),
        _json_key(_field(item, "timestamp_range")),
    )


def _dedupe_key_tool_calls(item: Mapping[str, object]) -> tuple[Hashable, ...]:
    """Tool-call identity = ``(tool, query, timestamp_range)`` (AD-10)."""
    return (
        _json_key(_field(item, "tool")),
        _json_key(_field(item, "query")),
        _json_key(_field(item, "timestamp_range")),
    )


def _dedupe_key_whole(item: Mapping[str, object]) -> Hashable:
    """Whole-item identity (exact-duplicate drop) — used when no field is locked.

    ``playbook_hits`` have no locked identity field (retriever output shape is
    deferred), so we dedupe by exact JSON identity (idempotent, deterministic).
    """
    return _json_key(dict(item))


def _append_dedupe(
    left: list[_Item],
    right: list[_Item] | _Item,
    key_of: Any,
) -> list[_Item]:
    """Append ``right`` items to ``left``, dropping items whose key already present.

    Pure: returns a NEW list, never mutates ``left``/``right``. ``right`` may be a
    single item or a list (LangGraph passes whatever the node returned).
    """
    new_items: list[_Item] = [*right] if isinstance(right, list) else [right]
    # Stable: keep existing order + first occurrence of each key.
    out: list[_Item] = list(left)
    seen: set[Hashable] = {key_of(it) for it in left}
    for it in new_items:
        k = key_of(it)
        if k not in seen:
            seen.add(k)
            out.append(it)
    return out


def append_dedupe_evidence(left: list[_Item], right: list[_Item] | _Item) -> list[_Item]:
    """Reducer for ``evidence`` — append + dedupe (source_name, query, timestamp_range)."""
    return _append_dedupe(left, right, _dedupe_key_evidence)


def append_dedupe_tool_calls(left: list[_Item], right: list[_Item] | _Item) -> list[_Item]:
    """Reducer for ``tool_calls`` — append + dedupe (tool, query, timestamp_range) (AD-10)."""
    return _append_dedupe(left, right, _dedupe_key_tool_calls)


def append_dedupe_playbook_hits(left: list[_Item], right: list[_Item] | _Item) -> list[_Item]:
    """Reducer for ``playbook_hits`` — append + dedupe by whole-item identity."""
    return _append_dedupe(left, right, _dedupe_key_whole)


def upsert_hypotheses(left: list[_Item], right: list[_Item] | _Item) -> list[_Item]:
    """Reducer for ``hypotheses`` — upsert by hypothesis ``id`` (AD-4).

    Matching ``id`` → replace in place (position preserved); new ``id`` → append.
    An item without ``id`` is treated as new (append). Deterministic + pure.
    """
    new_items: list[_Item] = [*right] if isinstance(right, list) else [right]
    by_id: dict[object, int] = {it.get("id"): i for i, it in enumerate(left) if "id" in it}
    out: list[_Item] = list(left)
    for it in new_items:
        hid = it.get("id")
        if hid is not None and hid in by_id:
            out[by_id[hid]] = it  # replace in place (position stable)
        else:
            if hid is not None:
                by_id[hid] = len(out)
            out.append(it)
    return out


def upsert_context(left: dict[str, JsonValue], right: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Reducer for ``context`` — shallow upsert/merge (new keys overwrite, keep the rest)."""
    return {**left, **right}


def append_safety_flags(
    left: dict[str, JsonValue], right: dict[str, JsonValue]
) -> dict[str, JsonValue]:
    """Reducer for ``safety_flags`` — merge (AD-9 spine verb "append" on a dict).

    AD-9 spine types ``safety_flags`` as a ``dict`` with reducer "append". For a
    dict the natural "append" is a key-merge: ``{**left, **right}``. This is a
    SHALLOW merge — a key present in both keeps the ``right`` value (per-key
    overwrite). The internal flag value-shape is deferred (AD-9 "field semantics
    defer"): whether values should concat/deep-merge when a key repeats is NOT
    locked yet, so we do not invent that structure here. Once the flag shape is
    locked in its story, this reducer may become a deep-merge/concat — but for
    POC the merge is the honest, non-inventing semantics.

    The reducer never whole-dict overwrites (it always carries ``left``'s keys
    that ``right`` does not touch).
    """
    return {**left, **right}


# ---------------------------------------------------------------------------
# InvestigationState — 13-key AD-9 spine TypedDict
# ---------------------------------------------------------------------------


class InvestigationState(TypedDict, total=False):
    """Graph state spine — 13 top-level keys (AD-9). Plain JSON-safe dicts.

    ``total=False``: nodes return **partial** state (AD-4) — never all 13 keys.
    Scalar / set-once keys are NOT annotated, so LangGraph applies its default
    overwrite reducer (= AD-4 "replace" / set-once). Collection keys carry their
    AD-4 reducer via ``Annotated``.
    """

    # 1 — immutable per run; fail-fast mismatch on resume (assert_schema_version).
    schema_version: int
    """State schema version (AD-9 rule 4). Read on resume → mismatch raises."""

    # 2 — set once (ingress grouping).
    incident_id: str | None
    """Optional H3 grouping id (FR-2 / DEC-1). None until grouped."""

    # 3 — set once (ingress). Nested shape ⊆ IncidentTrigger §3.4 (.model_dump()).
    trigger: dict[str, JsonValue]
    """IncidentTrigger §3.4 (18 fields + incident_id); raw_payload inline POC."""

    # 4 — upsert (merge). incident_context_builder fills service/namespace/window.
    context: Annotated[dict[str, JsonValue], upsert_context]
    """Initial investigation context (§3.5 incident_context_builder)."""

    # 5 — append + dedupe. preplanning_playbook_retriever (§4.2 / FR-3).
    playbook_hits: Annotated[list[_Item], append_dedupe_playbook_hits]
    """Playbooks relevant to the trigger (retriever, Epic 3)."""

    # 6 — upsert by id. hypothesis_planner (FR-4). H01..: id, priority, plan, status.
    hypotheses: Annotated[list[_Item], upsert_hypotheses]
    """Candidate hypotheses; upsert keeps plan replans lossless."""

    # 7 — replace (default overwrite). current plan.
    plan: dict[str, JsonValue] | None
    """Current execution plan (None until planned)."""

    # 8 — append + dedupe (tool, query, timestamp_range) (AD-10). executor_router.
    tool_calls: Annotated[list[_Item], append_dedupe_tool_calls]
    """Executed read-only tool calls; dedupe by (tool, query, timestamp_range)."""

    # 9 — append + dedupe (source_name, query, timestamp_range). Evidence §3.6.
    evidence: Annotated[list[_Item], append_dedupe_evidence]
    """Normalized evidence objects (9-field §3.6 tier, FR-6 / AD-6)."""

    # 10 — replace (default overwrite). reflector: floor_pass, ceiling, categorical.
    sufficiency: dict[str, JsonValue]
    """Sufficiency verdict (FR-8 / AD-12 floor + AD-7 ceiling)."""

    # 11 — append (merge). read-only violations blocked (audit accumulation).
    safety_flags: Annotated[dict[str, JsonValue], append_safety_flags]
    """Accumulated safety flags (read-only boundary, AD-3)."""

    # 12 — replace (default overwrite). routing: replan / gather_more / write.
    next_action: str
    """Reflector/emitter routing decision."""

    # 13 — set once. RCA report (FR-9).
    report: dict[str, JsonValue] | None
    """Final RCA report (None until rca_writer, Epic 5)."""


# Sanity: the spine has EXACTLY 13 top-level keys (leader DEEP counts this).
assert len(InvestigationState.__annotations__) == 13, (  # noqa: PLR2004
    f"AD-9 spine must have exactly 13 top-level keys, got "
    f"{len(InvestigationState.__annotations__)}: "
    f"{sorted(InvestigationState.__annotations__)}"
)


def create_initial_state(
    incident_id: str | None = None,
    trigger: dict[str, JsonValue] | None = None,
    schema_version: int = SCHEMA_VERSION,
) -> InvestigationState:
    """Build a fresh JSON-safe default state.

    Avoids the shared-mutable-default footgun (a new dict/list per call). Used by
    tests (round-trip sample) and — later, Story 3-5 — to seed the compiled
    graph. Every value is JSON-safe (empty list/dict/None/scalar).

    The caller-supplied ``trigger`` is shallow-copied so a caller that keeps a
    handle and mutates it later cannot mutate the seeded state underneath the
    graph (aliasing guard; the empty-default path already returns a fresh dict).
    """
    return InvestigationState(
        schema_version=schema_version,
        incident_id=incident_id,
        trigger=dict(trigger) if trigger is not None else {},
        context={},
        playbook_hits=[],
        hypotheses=[],
        plan=None,
        tool_calls=[],
        evidence=[],
        sufficiency={},
        safety_flags={},
        next_action="",
        report=None,
    )


__all__ = [
    "InvestigationState",
    "JsonValue",
    "SCHEMA_VERSION",
    "append_dedupe_evidence",
    "append_dedupe_playbook_hits",
    "append_dedupe_tool_calls",
    "append_safety_flags",
    "assert_schema_version",
    "create_initial_state",
    "upsert_context",
    "upsert_hypotheses",
]
