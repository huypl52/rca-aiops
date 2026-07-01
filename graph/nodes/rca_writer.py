"""rca_writer — §3.5 PE-R WRT node: cited RCA report (Story 5.1 — FR-9 / AD-6 / AD-7 / AD-9 / AD-12 / T9).

The **eighth and LAST** §3.5 node (flow ``ICB→PBR→HYP→VAL→EXR→ENV→REF→WRT→END``; reached only when the
reflector routes ``write``). It is the **output-side anti-hallucination backbone** — the twin of DEC-3
(loop-side): DEC-3 makes an *unsafe conclusion* textually unreachable on the loop side (a floor-Fail never
consults the ceiling — the assessor call sits after the early-return); the writer makes an *uncited
root-cause claim* textually unreachable on the output side (an evidence with a null/absent ``raw_excerpt`` can
never become a citation — the citation path requires a non-empty str excerpt). **No evidence → no claim;
drop, never invent.**

It is a **pure deterministic projector**: it reads ``state.evidence`` + ``state.hypotheses`` +
``state.sufficiency`` and returns ``{"report": <dict>}`` — a STATE DICT (AD-9 — Pydantic ONLY at the port;
there is NO ``models/report.py``). It calls NO tools, performs NO dispatch / NO adapter call (read-only
investigator — §3.8 / AD-3, enforced by CI #1). Deterministic (AD-12 — no LLM / clock / random / IO). Never
raises (Constraint 5 — malformed state → an honest empty report).

This mirrors the established DI-factory node pattern (1-3 / 3-1 / 3-2 / 3-3 / 3-4 / 3.5 / 4.2 / 4.3):
``build_rca_writer()`` returns a node ``(state) -> {"report": <dict>}``. WRT is a PURE PROJECTOR — it takes
NO injected deps (precedent ``build_plan_validator``); the leader's ``(*, <deps>)`` template allows empty
deps. It writes NO ``next_action`` (the ``WRT→END`` edge is unconditional — WRT is terminal).

LOCKED MECHANISM (do NOT redesign):

  1. **AD-6 — every root-cause claim cites ≥1 evidence with a NON-NULL ``raw_excerpt`` (the backbone).** The
     hypothesis has NO statement field (its claim rides inside ``plan``); the ONLY hypothesis→evidence
     linkage is ``evidence.supports`` (a list of hypothesis ids, 9-field §3.6 tier). So a hypothesis H is a
     citable root-cause candidate IFF ≥1 evidence carries a non-empty-str ``raw_excerpt`` AND ``H.id`` ∈
     ``evidence.supports``. A hypothesis with NO such citation is NEVER a root-cause claim — it is DROPPED to
     ``open_questions`` (no-evidence → no-claim; drop, never invent). A null/absent-``raw_excerpt`` evidence
     is textually UNREACHABLE as a citation (the WRT twin of DEC-3 — the unsafe output is unreachable by
     construction, not merely asserted-against).

  2. **AD-7 — single-authority confidence (PROJECT, never recompute).** ``report.confidence`` =
     ``{ceiling_confidence, categorical}`` projected VERBATIM from ``state.sufficiency``. The writer NEVER
     re-runs the floor / ceiling assessor — ``sufficiency`` (the 4-3 reflector verdict) IS the authority. A
     ``sufficiency`` whose value a re-derivation would estimate differently is projected AS-IS (honest
     authority > a recomputed estimate).

  3. **AD-9 — report is a STATE DICT (set-once).** The report stays a plain JSON-safe ``dict`` on the 13-key
     spine (key #14 ``report``); there is NO Pydantic ``Report`` model. Pydantic runs ONLY at the port
     (``models.Evidence`` is validated at ENV 4-2; the writer reads already-validated dicts). The ``report``
     reducer is the default scalar-replace; WRT is terminal (``WRT→END``) so the report is set ONCE.

  4. **Report shape (6 keys, FR-9 — concise / 1-màn hình).**
       - ``root_cause`` — ranked candidate list (priority ASC, id ASC). Each candidate:
         ``{rank, hypothesis_id, priority, citations: [{raw_excerpt, source_name, source_type,
         timestamp_range}]}``. Empty list when nothing is grounded (honest).
       - ``evidence_backing`` — the flat cited union (every evidence that backed ≥1 candidate), deduped by
         identity + sorted. Each: ``{raw_excerpt, source_name, source_type, timestamp_range, summary}``.
       - ``confidence`` — ``{ceiling_confidence, categorical}`` projected verbatim from ``sufficiency``
         (AD-7); both ``None`` when ``sufficiency`` is absent/non-dict.
       - ``open_questions`` — hypothesis ids that could NOT be grounded (no citation), sorted ascending.
       - ``uncertainty`` — honest "chưa chắc / cần thêm" projected from ``sufficiency`` (the reflector's
         ``gap`` when present, else a matched/min margin note, else ``""``); never invented prose.
       - ``remediation`` — ``[]`` (T9 / D12 — remediation text is OFF by default; the field is PRESENT but
         empty, NEVER invented — AC3 default off).

  5. **Determinism (AD-12).** No LLM, no wall-clock, no random, no IO. Every emitted list is sorted by an
     explicit tuple key (PYTHONHASHSEED-safe). Same state → identical report across calls AND across
     PYTHONHASHSEED.

  6. **Never-raise (Constraint 5).** Malformed state / non-list evidence or hypotheses / non-dict sufficiency
     / a non-Mapping ``state`` → deterministic degrade to an honest EMPTY report (the 6 keys, all empty/None).
     NEVER a propagated exception — the node always returns a valid ``{"report": <dict>}`` partial.

ONE-WAY (AD-1 / gate #2 HARD-FAIL): imports ``graph.state`` (same layer) + stdlib ONLY
(``collections.abc`` / ``typing``). NO ``services``/``routers``/``adapters``/``tools``/``models`` back-edge
(the writer reads already-validated dicts, NOT ``Evidence`` objects — AD-9). NO ``graph.compiled`` (WRT is
terminal — it writes NO ``next_action``; the ``WRT→END`` edge is unconditional). NO ``json`` (the citation
``raw_excerpt`` is ALREADY a serialized str in the evidence dict, produced by ENV 4-2; the writer only reads
it — avoiding the forbidden ``.dumps``/``.loads`` attribute surface). NO file IO, no
``random``/``time``/``datetime``/``uuid``. lint-imports: 1 contract kept / 0 broken.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import cast

from graph.state import InvestigationState, JsonValue

# ONE-WAY (AD-1 / gate #2): graph.state (same layer) + stdlib ONLY. NO models/tools/adapters/services/routers
# back-edge (reads already-validated dicts — AD-9). NO graph.compiled (terminal node — no routing). NO json
# (raw_excerpt is already a serialized str from ENV 4-2). NO random/time/datetime/uuid/IO.

# ---------------------------------------------------------------------------
# LOCKED constants (determinism — bounds/sentinels, NOT invented content)
# ---------------------------------------------------------------------------

#: The first rank assigned to the top root-cause candidate (rank ascends from here). POC default.
_FIRST_RANK: int = 1
#: Sort sentinel: a hypothesis with a missing/non-numeric ``priority`` ranks LAST among candidates. POC.

#: Module-level numeric constants are the ONLY numerics in this module; every bound is named here and the
#: node logic references them BY NAME (ZERO bare numeric literals inline in any function body — D4/AC4,
#: AST-scanned in tests). ``_PRIORITY_SENTINEL`` is a plain literal (NOT ``10**9``) so the AST no-inline-
#: numerics scan recognizes it as a module-level constant.

_PRIORITY_SENTINEL: int = 1000000000

# Honest "cần thêm" margin-note vocabulary (projected from sufficiency fields; never invented prose).
_UNCERTAINTY_MARGIN_PREFIX: str = "floor margin: matched "
_UNCERTAINTY_MARGIN_MID: str = " of min "
_UNCERTAINTY_NONE: str = ""


def _read_hypotheses(state: Mapping[str, object]) -> list[Mapping[str, object]]:
    """Read ``state["hypotheses"]`` as a list of Mapping DEFENSIVELY (non-list → empty). Never raises."""
    raw = state.get("hypotheses")
    if not isinstance(raw, list):
        return []
    return [h for h in raw if isinstance(h, Mapping)]


def _read_evidence(state: Mapping[str, object]) -> list[Mapping[str, object]]:
    """Read ``state["evidence"]`` as a list of Mapping DEFENSIVELY (non-list → empty). Never raises."""
    raw = state.get("evidence")
    if not isinstance(raw, list):
        return []
    return [e for e in raw if isinstance(e, Mapping)]


def _read_sufficiency(state: Mapping[str, object]) -> Mapping[str, object]:
    """Read ``state["sufficiency"]`` as a Mapping DEFENSIVELY (non-dict → empty). Never raises.

    The 4-3 reflector verdict is the AD-7 authority; the writer PROJECTS it (never recomputes). An absent /
    non-dict verdict projects as ``None`` confidence + ``""`` uncertainty (honest — we know nothing).
    """
    raw = state.get("sufficiency")
    return raw if isinstance(raw, Mapping) else {}


def _is_number_or_none(value: object) -> bool:
    """``value`` is None or a non-bool int/float (a ``bool`` is NOT a valid confidence projection)."""
    return value is None or (isinstance(value, int | float) and not isinstance(value, bool))


def _is_plain_int(value: object) -> bool:
    """``value`` is a non-bool int (for matched/min_count margin projection)."""
    return isinstance(value, int) and not isinstance(value, bool)


def _as_str(value: object) -> str:
    """Project ``value`` as a str defensively (non-str → ``""``). Used for deterministic sort/identity keys."""
    return value if isinstance(value, str) else ""


def _window_start(window: object) -> str:
    """The ``timestamp_range.start`` str (``""`` when absent/non-str) — a deterministic sort-key component."""
    if not isinstance(window, Mapping):
        return ""
    start = window.get("start")
    return start if isinstance(start, str) else ""


def _window_end(window: object) -> str:
    """The ``timestamp_range.end`` str (``""`` when absent/non-str) — a deterministic sort-key component."""
    if not isinstance(window, Mapping):
        return ""
    end = window.get("end")
    return end if isinstance(end, str) else ""


def _evidence_key(evidence: Mapping[str, object]) -> tuple[str, str, str, str, str]:
    """Deterministic identity/sort key for an evidence dict — PYTHONHASHSEED-safe (tuple of str leaves).

    ``(source_name, source_type, query, start, end)``. Used to dedupe ``evidence_backing`` and to sort both
    citations and backing deterministically. Never raises.
    """
    window = evidence.get("timestamp_range")
    return (
        _as_str(evidence.get("source_name")),
        _as_str(evidence.get("source_type")),
        _as_str(evidence.get("query")),
        _window_start(window),
        _window_end(window),
    )


def _timestamp_range(window: object) -> dict[str, JsonValue]:
    """Project the evidence ``timestamp_range`` ``{start, end?}`` defensively (non-Mapping → ``{}``)."""
    if not isinstance(window, Mapping):
        return {}
    out: dict[str, JsonValue] = {}
    start = window.get("start")
    if isinstance(start, str):
        out["start"] = start
    end = window.get("end")
    if isinstance(end, str):
        out["end"] = end
    return out


def _citation(evidence: Mapping[str, object]) -> dict[str, JsonValue]:
    """A single root-cause citation — the 4 Evidence fields a claim MUST surface (FR-9 backing).

    ``raw_excerpt`` is NON-NULL by construction: this is only built from a citable evidence (non-empty-str
    excerpt) — AD-6 no-RC-without-evidence.
    """
    return {
        "raw_excerpt": cast(JsonValue, evidence.get("raw_excerpt")),
        "source_name": cast(JsonValue, _as_str(evidence.get("source_name"))),
        "source_type": cast(JsonValue, _as_str(evidence.get("source_type"))),
        "timestamp_range": cast(JsonValue, _timestamp_range(evidence.get("timestamp_range"))),
    }


def _backing_entry(evidence: Mapping[str, object]) -> dict[str, JsonValue]:
    """An ``evidence_backing`` row — the citation fields PLUS the ``summary`` (FR-9 evidence backing)."""
    return {
        "raw_excerpt": cast(JsonValue, evidence.get("raw_excerpt")),
        "source_name": cast(JsonValue, _as_str(evidence.get("source_name"))),
        "source_type": cast(JsonValue, _as_str(evidence.get("source_type"))),
        "timestamp_range": cast(JsonValue, _timestamp_range(evidence.get("timestamp_range"))),
        "summary": cast(JsonValue, _as_str(evidence.get("summary"))),
    }


def _cited_evidence_index(
    evidence: list[Mapping[str, object]],
) -> dict[str, list[Mapping[str, object]]]:
    """AD-6 citation index: ``hypothesis_id -> [citable evidence backing it]``.

    An evidence backs a hypothesis H IFF it carries a NON-EMPTY-str ``raw_excerpt`` AND ``H.id`` is in its
    ``supports`` list. A null/absent-``raw_excerpt`` evidence contributes to NO hypothesis — it is textually
    unreachable as a citation (the WRT twin of DEC-3). Insertion order follows the evidence list (deterministic;
    callers sort the per-hypothesis lists explicitly).
    """
    index: dict[str, list[Mapping[str, object]]] = {}
    for ev in evidence:
        excerpt = ev.get("raw_excerpt")
        if not isinstance(excerpt, str) or not excerpt:
            continue  # AD-6: no non-null citation → NEVER citable (drop, never invent)
        supports = ev.get("supports")
        if not isinstance(supports, list):
            continue  # no hypothesis linkage → cannot back any claim
        for hid in supports:
            if isinstance(hid, str) and hid:
                index.setdefault(hid, []).append(ev)
    return index


def _candidate_sort_key(
    candidate: tuple[Mapping[str, object], str, list[Mapping[str, object]]],
) -> tuple[int | float, str]:
    """Deterministic candidate rank key: (priority ASC, id ASC).

    Takes a ``(hypothesis, hypothesis_id, cited)`` candidate tuple (unpacked — NO index literals, per the
    AST no-inline-numerics discipline). A missing/non-numeric/non-int-float ``priority`` sorts LAST
    (sentinel); a ``bool`` priority (int subclass) is rejected to the sentinel. Ties break by
    ``hypothesis_id`` ascending (``H01`` < ``H02`` < ...).
    """
    hypothesis, hypothesis_id, _cited = candidate
    priority = hypothesis.get("priority")
    rank_priority: int | float = (
        priority
        if isinstance(priority, int | float) and not isinstance(priority, bool)
        else _PRIORITY_SENTINEL
    )
    return (rank_priority, hypothesis_id)


def _candidate_entry(
    rank: int,
    hypothesis_id: str,
    hypothesis: Mapping[str, object],
    cited: list[Mapping[str, object]],
) -> dict[str, JsonValue]:
    """A ``root_cause`` candidate row: ``{rank, hypothesis_id, priority, citations}`` (citations sorted)."""
    citations = [_citation(ev) for ev in sorted(cited, key=_evidence_key)]
    return {
        "rank": rank,
        "hypothesis_id": hypothesis_id,
        "priority": cast(JsonValue, hypothesis.get("priority")),
        "citations": cast(JsonValue, citations),
    }


def _confidence(sufficiency: Mapping[str, object]) -> dict[str, JsonValue]:
    """AD-7 single-authority: project ``{ceiling_confidence, categorical}`` VERBATIM from sufficiency.

    Never recomputed. A non-numeric / bool ``ceiling_confidence`` or a non-str ``categorical`` projects as
    ``None`` (honest — we project the authority, defensively narrowed to valid JSON values).
    """
    cc = sufficiency.get("ceiling_confidence")
    cat = sufficiency.get("categorical")
    return {
        "ceiling_confidence": cast(JsonValue, cc) if _is_number_or_none(cc) else None,
        "categorical": cast(JsonValue, cat) if isinstance(cat, str) else None,
    }


def _uncertainty(sufficiency: Mapping[str, object]) -> str:
    """Honest "chưa chắc / cần thêm" projected from sufficiency (the authority); never invented prose.

    The reflector's ``gap`` ("chưa đủ — cần thêm ...") when present; else a deterministic matched/min margin
    note; else ``""``. No LLM, no invented wording (every token is a constant or a sufficiency value).
    """
    gap = sufficiency.get("gap")
    if isinstance(gap, str) and gap:
        return gap
    matched = sufficiency.get("matched_count")
    min_count = sufficiency.get("min_count")
    if _is_plain_int(matched) and _is_plain_int(min_count):
        return f"{_UNCERTAINTY_MARGIN_PREFIX}{matched}{_UNCERTAINTY_MARGIN_MID}{min_count}"
    return _UNCERTAINTY_NONE


def _empty_report() -> dict[str, JsonValue]:
    """The honest EMPTY report (6 keys, all empty/None) — the Constraint-5 degrade fallback.

    Identical to what :func:`_build_report` produces for an empty-but-well-formed state, so the degrade path
    and the happy empty path surface the SAME honest report.
    """
    return {
        "root_cause": cast(JsonValue, []),
        "evidence_backing": cast(JsonValue, []),
        "confidence": cast(JsonValue, {"ceiling_confidence": None, "categorical": None}),
        "open_questions": cast(JsonValue, []),
        "uncertainty": _UNCERTAINTY_NONE,
        "remediation": cast(JsonValue, []),
    }


def _build_report(state: Mapping[str, object]) -> dict[str, JsonValue]:
    """Build the 6-key cited RCA report from ``state`` (pure deterministic projector; defensive reads).

    AD-6 (no-RC-without-evidence): a hypothesis is a ``root_cause`` candidate IFF it has ≥1 citable evidence;
    otherwise it is dropped to ``open_questions``. AD-7 (single-authority): confidence is projected verbatim
    from ``sufficiency``. Every emitted list is sorted by an explicit key (AD-12). Defensive reads make this
    never-raise for any Mapping ``state`` (the outer :func:`build_rca_writer` wrap covers a non-Mapping state).
    """
    hypotheses = _read_hypotheses(state)
    evidence = _read_evidence(state)
    sufficiency = _read_sufficiency(state)

    cited_by_hyp = _cited_evidence_index(evidence)  # AD-6 citation index

    # Partition hypotheses: grounded (≥1 citation) → root_cause candidates; ungrounded → open_questions.
    candidates: list[tuple[Mapping[str, object], str, list[Mapping[str, object]]]] = []
    open_question_ids: list[str] = []
    for hypothesis in hypotheses:
        hid = hypothesis.get("id")
        if not isinstance(hid, str) or not hid:
            continue  # malformed hypothesis (no id) → skip entirely (neither candidate nor open-question)
        cited = cited_by_hyp.get(hid, [])
        if cited:
            candidates.append((hypothesis, hid, cited))
        else:
            open_question_ids.append(hid)

    candidates.sort(key=_candidate_sort_key)
    root_cause: list[dict[str, JsonValue]] = [
        _candidate_entry(rank, hid, hypothesis, cited)
        for rank, (hypothesis, hid, cited) in enumerate(candidates, start=_FIRST_RANK)
    ]

    open_questions = sorted(open_question_ids)

    # evidence_backing: the flat cited union across all candidates, deduped by identity + sorted.
    backing_by_key: dict[tuple[str, str, str, str, str], dict[str, JsonValue]] = {}
    for _hypothesis, _hid, cited in candidates:
        for ev in cited:
            key = _evidence_key(ev)
            if key not in backing_by_key:
                backing_by_key[key] = _backing_entry(ev)
    evidence_backing: list[dict[str, JsonValue]] = [
        backing_by_key[k] for k in sorted(backing_by_key)
    ]

    return {
        "root_cause": cast(JsonValue, root_cause),
        "evidence_backing": cast(JsonValue, evidence_backing),
        "confidence": cast(JsonValue, _confidence(sufficiency)),
        "open_questions": cast(JsonValue, open_questions),
        "uncertainty": _uncertainty(sufficiency),
        "remediation": cast(
            JsonValue, []
        ),  # T9 / D12: remediation OFF by default (present but empty)
    }


def build_rca_writer() -> Callable[[InvestigationState], dict[str, JsonValue]]:
    """Factory: build the §3.5 rca_writer (WRT) node (DI seam — mirrors 1-3/3-1/.../4.3; NO required deps).

    WRT is a PURE PROJECTOR over ``state`` — it takes NO injected deps (precedent
    :func:`graph.nodes.plan_validator.build_plan_validator`; the leader's ``(*, <deps>)`` template allows
    empty deps). Returns a node ``(state) -> {"report": <dict>}`` that:
      - reads ``state.evidence`` + ``state.hypotheses`` + ``state.sufficiency`` defensively;
      - builds the 6-key cited RCA report (AD-6 grounded candidates / dropped open-questions; AD-7 projected
        confidence; AD-12 deterministic; T9 remediation off);
      - returns AD-4 partial state ``{"report": <dict>}`` (exactly ONE key; the report is a STATE DICT — AD-9);
      - NEVER raises (Constraint 5): a malformed / non-Mapping ``state`` → the honest EMPTY report.

    Returns:
        a §3.5 terminal node returning PARTIAL state ``{"report": <dict>}`` (AD-4 — exactly one key).
    """

    def rca_writer(state: InvestigationState) -> dict[str, JsonValue]:
        try:
            report = _build_report(state)
        except Exception:  # noqa: BLE001 — a malformed/non-Mapping state must NEVER break the graph (Constraint 5)
            report = _empty_report()
        return {"report": cast(JsonValue, report)}

    return rca_writer


__all__ = ["build_rca_writer"]
