"""evidence_normalizer — §3.5 PE-R ENV node: tool_call raw → tiered Evidence (Story 4.2 — FR-6 / AD-6 / AD-9 / AD-12).

The **sixth** §3.5 node (flow ``ICB→PBR→HYP→VAL→EXR→ENV→REF``). It is a **read-only normalizer**: it
converts each DISPATCHED ``tool_call``'s RAW output (already collected by EXR 3.5 — ENV performs NO
dispatch) into a tiered ``Evidence`` object (required / optional-nullable / derived, 9 fields §3.6) WITH a
non-null citation (``raw_excerpt``), Pydantic-validated AT THE PORT (AD-9 — the only place Pydantic runs),
emitted as a plain JSON-safe dict into ``state.evidence`` (append+dedupe, AD-4 — the reducer is in
``graph.state``, UNCHANGED). Deterministic (AD-12 — no LLM / clock / random / IO). Never guesses a field
(AC4 — a raw missing a REQUIRED field → that tool_call's evidence is DROPPED, never filled). Never raises
(Constraint 5 — malformed raw / missing field / validation failure → drop the candidate, return survivors).

This mirrors the established DI-factory node pattern (1-3 / 3-1 / 3-2 / 3-3 / 3-4 / 3.5):
``build_evidence_normalizer(*, summarizer)`` returns a node ``(state) -> {"evidence": [...]}``.

LOCKED MECHANISM (do NOT redesign — defer only summarizer CONTENT):

  1. **Input = ``state.tool_calls`` (read-only; already-dispatched records).** Each EXR record is
     ``{tool, query, timestamp_range, raw}`` (``executor_router.py``), emitted ONLY on a fresh dispatch
     (``dispatched=True`` — never on cache-hit/error), so ``raw`` is always a populated dict. ENV reads
     ``state.tool_calls`` + ``state.context`` (for the ``source_name`` fallback of last resort) and performs
     NO dispatch / NO adapter call (read-only investigator — §3.8 / AD-3, enforced by CI #1).

  2. **Normalize-ALL (deterministic + idempotent).** Every ``tool_calls`` record → one candidate Evidence,
     each invocation. The spine ``append_dedupe_evidence`` reducer (key = ``(source_name, query,
     timestamp_range)``, PYTHONHASHSEED-safe via ``_json_key``) makes this idempotent: re-normalizing the
     same ``tool_calls`` yields identical dicts → identical dedupe keys → ZERO growth (AC2).

  3. **Field derivation — single source of truth (LOCKED precedence; no tool-name→field mapping table):**
       - ``source_type`` (required) ← ``raw["source_type"]`` (the tool DECLARES its source in raw — single
         source of truth; prometheus / loki / kubernetes / playbook / topology). Missing/non-str → DROP.
       - ``source_name`` (required) ← ``raw["source_name"]`` → ``raw["service"]`` → ``state.context["service"]``
         (defensive precedence chain). If none resolve to a non-empty str → DROP.
       - ``query`` (required) ← ``tool_call["query"]`` (the canonical identifying-kwargs string EXR recorded —
         "what was asked"). Pass-through; non-str/empty → DROP.
       - ``timestamp_range`` (required) ← LOCKED precedence: ``raw["time_window"]`` (the tool's OWN query
         window — the structured ``{start, end}`` windowed tools [prometheus/loki] echo; the window the query
         actually covered — most precise) → ``state.context["time_window"]`` (the ICB-built INCIDENT window —
         the window during which this evidence was collected; the honest fallback for point-in-time/static
         tools [k8s_*, search_playbook, topology_read] whose raw carries NO query window) → ``None`` (DROP only
         when BOTH are absent/invalid). The SAME validation applies to both (``start`` non-empty ISO str; ``end``
         nullable). This is NOT guessing — ``context["time_window"]`` is the real incident window. (The EXR
         record's ``timestamp_range`` is a canonical-JSON DEDUPE string, NOT a structured window — never used.)
       - ``summary`` (required) ← ``summarizer(raw, source_type, query)`` (the injected deterministic seam).
         non-str/empty → DROP.
       - ``raw_excerpt`` (optional-nullable, NON-NULL here) ← a deterministic bounded JSON serialization of
         ``raw`` (sorted keys) — the AD-6 citation backing any root-cause claim. Always present for a
         dispatched record (raw is populated). DERIVED from raw, never fabricated.
       - ``confidence`` (optional-nullable) ← ``None`` (honest; DERIVED by the reflector 4-3, NOT ENV).
       - ``supports`` (derived list) ← exact-match hypothesis ids whose ``plan`` matches the originating
         tool_call identity ``{tool, query, timestamp_range}``; ambiguous/no-match stays ``[]`` (honest,
         deterministic, never guessed).
       - ``contradicts`` (derived list) ← ``[]`` (honest empty; no deterministic contradiction source in
         the current production path).

  4. **Port gate (AC4 no-guessing + Constraint 5 never-raise).** Build the candidate dict per (3), then
     validate AT THE PORT: ``Evidence.model_validate(candidate)`` (Pydantic v2 — AD-9: Pydantic ONLY here;
     ``extra="forbid"`` rejects any stray key). On ANY failure (missing required / extra / wrong tier /
     a raised exception) → DROP that tool_call's evidence (return the survivors only). NEVER raise, NEVER
     patch/fill with guesses. On success → ``.model_dump()`` → plain JSON-safe dict → the ``evidence`` list.

  5. **Summarizer seam (LOCKED signature + constraints; CONTENT deferred).**
     ``EvidenceSummarizer = Callable[[Mapping[str, object], str, str], str]`` — ``(raw, source_type, query)
     -> non-empty str``. The DEFAULT :func:`default_deterministic_summarizer` is PURE + DETERMINISTIC +
     DERIVED from real raw structure (counts of list-valued raw fields) + ``source_type`` + a bounded echo of
     ``query`` — NEVER guessed/fabricated (AC4); no LLM, no clock, no random. An LLM-enriched summarizer may
     be swapped later via this seam WITHOUT rewiring (the POC default keeps the pipeline reproducible — AD-12).

  6. **AD-6 (no-RC-without-evidence):** ENV is the DATA PRODUCER — it CONTRIBUTES the citation (non-null
     ``raw_excerpt``) + honest empty ``supports``/``contradicts``. The actual RC-BLOCK enforcement is
     DOWNSTREAM (reflector 4-3 / rca_writer 5-1); ENV does not gate. State explicitly: every EMITTED evidence
     carries a non-null ``raw_excerpt`` (no claim-grade evidence without a backing excerpt).

ONE-WAY (AD-1 / gate #2 HARD-FAIL): imports ``graph.state`` (same layer) + ``models.evidence`` (graph→models
is LEGAL — ``models`` is NOT a contracted layer; precedent ``tools→ci``; gate #2 green) + stdlib ONLY
(``json`` / ``collections.abc``). NO ``services``/``routers``/``adapters``/``tools`` back-edge. NO file IO
(config/yaml loading is the 4-3 reflector composition root's job, NOT ENV's). ``pydantic`` is NOT imported
directly here — the port gate catches ``Exception`` broadly (Constraint 5: never raise) so this module's
import surface stays {models, graph, stdlib}. lint-imports: 1 contract kept / 0 broken.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import cast

from graph.state import InvestigationState, JsonValue
from models.evidence import Evidence

# ONE-WAY (AD-1 / gate #2): graph.state (same layer) + models.evidence (graph→models LEGAL — models is NOT a
# contracted layer; precedent tools→ci) + stdlib ONLY. NO services/routers/adapters/tools back-edge. NO file IO.
# pydantic is NOT imported here (the port gate catches Exception broadly — Constraint 5; keeps the import
# surface {models, graph, stdlib}).

# ---------------------------------------------------------------------------
# LOCKED constants (deterministic citation bounds — bounds, NOT invented content)
# ---------------------------------------------------------------------------

# Bounded echo of the canonical query inside the summary (keeps summaries bounded + deterministic).
_SUMMARY_QUERY_BUDGET: int = 120

# Bounded raw citation excerpt length (chars). A citation SLICE of raw — derived, never fabricated; truncated
# mid-JSON is acceptable for an excerpt (it backs a claim, it is not re-parsed).
_RAW_EXCERPT_BUDGET: int = 512


#: Summarizer seam — ``(raw, source_type, query) -> non-empty deterministic summary str``. Injected at factory
#: time; the default is pure/deterministic/derived (AC4). An LLM-enriched summarizer may swap in later.
type EvidenceSummarizer = Callable[[Mapping[str, object], str, str], str]


def _bounded(text: str, budget: int) -> str:
    """Deterministic truncation to ``budget`` chars (citation bound — no content invented)."""
    return text[:budget]


def default_deterministic_summarizer(
    raw: Mapping[str, object], source_type: str, query: str
) -> str:
    """DEFAULT summarizer — pure deterministic summary DERIVED from real raw structure (AC4 no-guessing).

    Every token is a function of ``(raw, source_type, query)``:
      - ``source_type`` — the real declared source (already validated non-empty str by the caller);
      - the total count of items across all list-valued raw fields (e.g. ``result`` / ``streams`` / ``pods`` /
        ``events`` / ``hits`` / ``lines`` / ``services``) — a structural count, NOT a hardcoded field-name
        mapping (it sums ANY list value raw carries);
      - a bounded echo of ``query`` (the canonical identifying-kwargs string — "what was asked").

    No LLM, no wall-clock, no random, no IO (AD-12). Non-empty (``source_type`` is always present). Never
    fabricates a value not present in the inputs.
    """
    # Structural: total items across every list-valued raw field (sum is order-independent → PYTHONHASHSEED-safe).
    list_item_total = sum(len(value) for value in raw.values() if isinstance(value, list))
    summary = f"{source_type} evidence: {list_item_total} record(s)"
    if isinstance(query, str) and query:
        summary += f" (query={_bounded(query, _SUMMARY_QUERY_BUDGET)})"
    return summary


def _resolve_source_name(raw: Mapping[str, object], context: Mapping[str, object]) -> str | None:
    """Resolve ``source_name`` via the LOCKED precedence chain; None if unresolvable (→ candidate DROP).

    ``raw["source_name"]`` → ``raw["service"]`` → ``state.context["service"]`` (the investigation target —
    ICB's fallback of last resort). First non-empty str wins; NO tool-name→source_name mapping table.
    """
    for candidate in (raw.get("source_name"), raw.get("service")):
        if isinstance(candidate, str) and candidate:
            return candidate
    service = context.get("service")
    if isinstance(service, str) and service:
        return service
    return None


def _valid_window(window: object) -> dict[str, JsonValue] | None:
    """Validate + project a time window ``{start, end?}`` to the Evidence ``timestamp_range`` shape.

    ``start`` MUST be a non-empty ISO str (TimestampRange required non-null); ``end`` is nullable
    (``str | None`` — None while the incident is still firing). Returns None when the window is
    absent/invalid (non-Mapping / ``start`` missing-or-non-str-or-empty) so the caller can try the next
    precedence source. Applied UNIFORMLY to every candidate window (raw's own + the incident window).
    """
    if not isinstance(window, Mapping):
        return None
    start = window.get("start")
    if not isinstance(start, str) or not start:
        return None
    end = window.get("end")
    end_value: JsonValue = end if isinstance(end, str) else None
    return {"start": start, "end": end_value}


def _resolve_timestamp_range(
    raw: Mapping[str, object], context: Mapping[str, object]
) -> dict[str, JsonValue] | None:
    """Derive the Evidence ``timestamp_range`` ``{start, end}`` via LOCKED precedence.

    Precedence (most-precise first):
      1. ``raw["time_window"]`` — the tool's OWN query window (echoed by windowed tools: prometheus/loki;
         the window the query actually covered — most precise).
      2. ``state.context["time_window"]`` — the ICB-built INCIDENT window ``{start, end}``
         (``incident_context_builder`` — the window during which this evidence was collected). The honest
         fallback for point-in-time / static tools (k8s_*, search_playbook, topology_read) whose raw carries
         NO query window — without it those tool types would be SILENTLY DROPPED (leader BLOCKER B1: 6/8 real
         stubs were dropped; the k8s/topology/playbook evidence IS the core root-cause signal).
      3. ``None`` → DROP (only when BOTH windows are absent/invalid).

    The SAME validation (:func:`_valid_window`) applies to both candidate windows (``start`` non-empty ISO
    str; ``end`` nullable). This is NOT guessing — ``context["time_window"]`` is the real incident window.
    The EXR record's ``timestamp_range`` is a canonical-JSON DEDUPE STRING, NOT a structured window (never
    used here).
    """
    for candidate in (raw.get("time_window"), context.get("time_window")):
        window = _valid_window(candidate)
        if window is not None:
            return window
    return None


def _raw_excerpt(raw: Mapping[str, object]) -> str:
    """Deterministic bounded JSON citation of ``raw`` (AD-6 backing excerpt; derived, never fabricated).

    Sorted keys + ``ensure_ascii=False`` → the same raw ALWAYS serializes identically (PYTHONHASHSEED-safe).
    Bounded to :data:`_RAW_EXCERPT_BUDGET` chars (a citation slice; truncation is acceptable for an excerpt).
    """
    blob = json.dumps(dict(raw), sort_keys=True, ensure_ascii=False, default=str)
    return _bounded(blob, _RAW_EXCERPT_BUDGET)


def _canonical_json_text(value: object) -> str | None:
    """Canonical JSON text for deterministic identity comparison; None when ``value`` is not JSON-shaped.

    Used to compare a hypothesis plan's structured ``timestamp_range`` with the executor record's canonical
    JSON string without guessing or relying on dict insertion order.
    """
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001 — defensive: malformed/non-serializable values simply do not match
        return None


def _matching_hypothesis_ids(
    hypotheses: object, record: Mapping[str, object]
) -> list[str]:
    """Exact-match ``supports`` ids for the originating tool_call identity ``{tool, query, timestamp_range}``.

    The EXR/router ``record.query`` field is the CANONICAL JSON of every identifying plan kwarg EXCEPT
    ``timestamp_range`` (mirrors the router dedupe key shape), so support linkage must compare against the
    PLAN'S canonical identifying kwargs — not against a raw ``plan.query`` string directly. A hypothesis
    therefore contributes only when:
      - it is a Mapping with a non-empty ``id``;
      - ``plan.tool`` exactly matches ``record.tool``;
      - canonical JSON of ``plan`` minus ``{tool, timestamp_range}`` exactly matches ``record.query``;
      - canonical JSON of ``plan.timestamp_range`` exactly matches ``record.timestamp_range``.

    Missing / malformed / ambiguous shapes degrade honestly to no support. The result is deduped in encounter
    order and never raises.
    """
    if not isinstance(hypotheses, list):
        return []
    record_tool = record.get("tool")
    record_query = record.get("query")
    record_timestamp_range = record.get("timestamp_range")
    if (
        not isinstance(record_tool, str)
        or not record_tool
        or not isinstance(record_query, str)
        or not record_query
        or not isinstance(record_timestamp_range, str)
        or not record_timestamp_range
    ):
        return []

    matched: list[str] = []
    for hypothesis in hypotheses:
        if not isinstance(hypothesis, Mapping):
            continue
        hypothesis_id = hypothesis.get("id")
        plan = hypothesis.get("plan")
        if not isinstance(hypothesis_id, str) or not hypothesis_id or not isinstance(plan, Mapping):
            continue
        tool = plan.get("tool")
        timestamp_range = _canonical_json_text(plan.get("timestamp_range"))
        identifying_query = _canonical_json_text(
            {key: value for key, value in plan.items() if key not in {"tool", "timestamp_range"}}
        )
        if (
            isinstance(tool, str)
            and tool == record_tool
            and isinstance(identifying_query, str)
            and identifying_query == record_query
            and timestamp_range == record_timestamp_range
            and hypothesis_id not in matched
        ):
            matched.append(hypothesis_id)
    return matched


def build_evidence_normalizer(
    *, summarizer: EvidenceSummarizer = default_deterministic_summarizer
) -> Callable[[InvestigationState], dict[str, JsonValue]]:
    """Factory: build the §3.5 evidence_normalizer (ENV) node (DI seam — mirrors 1-3/3-1/3-2/3-3/3-4/3.5).

    Returns a node ``(state) -> partial-state-dict`` that:
      - reads ``state["tool_calls"]`` (already-dispatched records) + ``state["context"]`` +
        ``state["hypotheses"]`` defensively;
      - for EACH record, derives the 9 Evidence fields per the LOCKED precedence (§3), building a candidate
        dict; a record whose raw misses a REQUIRED field (source_type / resolvable source_name / query /
        a valid window — raw's OWN ``time_window`` OR the incident ``context["time_window"]``) is DROPPED
        (AC4 — never guessed);
      - validates the candidate AT THE PORT (``Evidence.model_validate`` — AD-9; ``extra="forbid"``); ANY
        failure or raised exception → DROP that candidate (Constraint 5 — never raise);
      - returns AD-4 partial state ``{"evidence": [valid_model_dump_dicts, ...]}``.

    Args:
        summarizer: the injected :data:`EvidenceSummarizer` (default :func:`default_deterministic_summarizer`
            — pure/deterministic/derived). An LLM-enriched summarizer may swap in later WITHOUT rewiring.

    Returns:
        a §3.5 node returning PARTIAL state ``{"evidence": [...]}`` (AD-4 — exactly one key).
    """

    def evidence_normalizer(state: InvestigationState) -> dict[str, JsonValue]:
        tool_calls = state.get("tool_calls")
        if not isinstance(tool_calls, list):
            return {"evidence": []}
        context_raw = state.get("context")
        context: Mapping[str, object] = context_raw if isinstance(context_raw, Mapping) else {}
        hypotheses = state.get("hypotheses")

        evidence_list: list[dict[str, JsonValue]] = []
        for record in tool_calls:
            if not isinstance(record, Mapping):
                continue  # malformed record → skip (never raise)
            raw = record.get("raw")
            if not isinstance(raw, Mapping):
                continue  # no raw to normalize → skip

            # --- required fields (single source of truth; missing/non-str → DROP, never guess) ---
            source_type = raw.get("source_type")
            if not isinstance(source_type, str) or not source_type:
                continue
            source_name = _resolve_source_name(raw, context)
            if source_name is None:
                continue
            query = record.get("query")
            if not isinstance(query, str) or not query:
                continue
            timestamp_range = _resolve_timestamp_range(raw, context)
            if timestamp_range is None:
                continue

            # --- summary via the injected deterministic seam (never raise) ---
            try:
                summary = summarizer(raw, source_type, query)
            except Exception:  # noqa: BLE001 — an injected summarizer must never break ENV (Constraint 5)
                continue
            if not isinstance(summary, str) or not summary:
                continue

            supports = _matching_hypothesis_ids(hypotheses, record)

            # --- candidate: EXACTLY the 9 Evidence fields (extra="forbid" honored) ---
            candidate: dict[str, JsonValue] = {
                "source_type": source_type,
                "source_name": source_name,
                "query": query,
                "timestamp_range": timestamp_range,
                "summary": summary,
                "raw_excerpt": _raw_excerpt(raw),  # NON-NULL citation (AD-6) — derived from raw
                "confidence": None,  # honest default; DERIVED by reflector 4-3, NOT ENV
                "supports": cast(JsonValue, supports),  # exact-match linkage; unmatched stays honest-empty
                "contradicts": [],  # honest empty; no deterministic contradiction source yet
            }

            # --- PORT gate (AD-9 Pydantic-only-at-port; AC4 no-guess; Constraint 5 never-raise) ---
            try:
                validated = Evidence.model_validate(candidate)
            except Exception:  # noqa: BLE001 — ValidationError (missing/extra/tier) OR any internal → DROP
                continue
            evidence_list.append(validated.model_dump())

        return {"evidence": cast(JsonValue, evidence_list)}

    return evidence_normalizer


__all__ = [
    "EvidenceSummarizer",
    "build_evidence_normalizer",
    "default_deterministic_summarizer",
]
