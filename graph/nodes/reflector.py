"""reflector — §3.5 PE-R REF node: floor-sàn + confidence-ceiling + DEC-3 routing (Story 4.3 — FR-7 / FR-8 / AD-7 / AD-12 / DEC-3).

The **seventh** §3.5 node (flow ``ICB→PBR→HYP→VAL→EXR→ENV→REF``; ``REF→WRT`` on ``write`` /
``REF→HYP`` on ``gather_more``/``replan``). It is the **R3 hybrid sufficiency gate** that decides whether
the agent may conclude a root cause. On each visit it:

  1. reads ``state["trigger"]["canonical_trigger"]`` DEFENSIVELY (missing/non-str → ``""`` → floor
     fail-closed "unknown-trigger"; mirrors the 3.1/3.4 trigger-source precedent);
  2. runs the **deterministic floor** (4.1 — :func:`graph.floor_check.build_floor_check`, the pure
     anti-hallucination backbone) over ``(canonical_trigger, state.evidence)``;
  3. **DEC-3 (load-bearing):** on ``floor_pass=False`` → ``next_action="gather_more"`` and the ceiling
     is **NEVER consulted** (the assessor is not even referenced on this path — NO root-cause conclusion
     is possible; the LLM ceiling cannot override a deterministic floor-Fail). The verdict carries the
     honest "chưa đủ" ``gap`` (derived from the FloorResult fields); ``ceiling_confidence``/``categorical``
     are ``None``;
  4. on ``floor_pass=True`` → consults the **AD-7 confidence ceiling** (DI assessor seam, deterministic
     default derived from evidence structure, bounded + clamped to ``[0, 1]``), derives the categorical
     ``{low|med|high}`` from the injected mapping, and routes ``write`` (ceiling >= write_threshold) /
     ``replan`` (ceiling < write_threshold), writing the sufficiency verdict (``floor_pass=True`` +
     ceiling numeric + categorical + ``gap=None``).

It writes TWO scalar-replace keys (AD-4): ``state.sufficiency`` (the 7-field verdict dict) and
``state.next_action`` (the LOCKED vocabulary ``{gather_more, replan, write}``, IMPORTED from
:mod:`graph.compiled` — single source of truth; the routing EDGES already wired by 3.5 consume it).

The runner's max-iter exhaustion is advanced to an honest **PARTIAL** carrying the reflector's last
``sufficiency.gap`` — NOT a silent binary ``status="failed"`` (FR-7 / AD-10 #5). That wiring lives in
:mod:`graph.compiled` (``_partial_snapshot``); this node OWNS the verdict the partial carries.

This mirrors the established DI-factory node pattern (1-3 / 3-1 / 3-2 / 3-3 / 3-4 / 3.5 / 4.2):
``build_reflector(*, floor_checker [REQUIRED], confidence_assessor, categorical_mapping, write_threshold)``
returns a node ``(state) -> {"sufficiency": <verdict>, "next_action": <gather_more|replan|write>}``.

LOCKED MECHANISM (do NOT redesign — defer only CONTENT/numbers):

  1. **DEC-3 ordering is structural, not conditional.** The floor is consulted FIRST; the assessor call
     is textually AFTER the ``floor_pass`` early-return, so on a floor-Fail the assessor is provably
     never invoked (a spy/counter records call-count == 0). This is the anti-hallucination backbone:
     no root cause is ever concluded (``write``) without first passing the deterministic floor. The
     ceiling (LLM-swappable, AD-7) can NEVER override a floor-Fail — by construction it is not even asked.

  2. **floor_check (4.1) is consumed, NOT modified.** The reflector builds the checker ONCE (factory
     time) and calls it per visit. ``FloorResult{floor_pass, matched_count, min_count, reason}`` is the
     frozen 4.1→4.3 seam (it does NOT carry ``source_type``; the ``gap`` is derived from its 4 fields).

  3. **AD-7 confidence ceiling — DI seam, deterministic default.**
     :data:`ConfidenceAssessor` = ``(evidence) -> float`` in ``[0.0, 1.0]``. The DEFAULT
     :func:`default_deterministic_confidence_assessor` is PURE/DETERMINISTIC/DERIVED from evidence
     structure (count-based saturation — no LLM/clock/random/IO; PYTHONHASHSEED-safe). An LLM-enriched
     assessor may swap in later via this seam WITHOUT rewiring (the POC default keeps the verdict
     reproducible — AD-12). Never-raise: a raising / non-numeric / out-of-range assessor degrades to the
     confidence floor (never an exception — Constraint 5).

  4. **D4 / AC4 — no hardcoded threshold.** Every threshold / breakpoint / bound is a MODULE-LEVEL
     CONSTANT (clearly marked "POC default — calibrate Epic-6") referenced BY NAME in the node logic.
     ZERO bare numeric literals inline in any function body (AST-scanned in tests). Threshold VALUE
     calibration defers to the Epic-6 benchmark (D4).

  5. **Categorical mapping — DI seam.** :data:`CategoricalMapping` = ``(confidence) -> str`` label
     ``{low|med|high}``. The DEFAULT :func:`default_categorical_mapping` uses the named band constants.
     Never-raise: a raising / non-str mapping degrades to ``"unknown"`` (the routing decision uses the
     NUMERIC ceiling vs write_threshold, so a degraded label never changes the route — Constraint 5).

  6. **Sufficiency verdict shape (7 fields, AD-4 scalar-replace).**
     On floor-Fail: ``{floor_pass: False, ceiling_confidence: None, categorical: None, matched_count,
     min_count, floor_reason, gap: "chưa đủ — ..."}``.
     On floor-Pass: ``{floor_pass: True, ceiling_confidence: <float>, categorical: <str>, matched_count,
     min_count, floor_reason, gap: None}``.
     ``ceiling_confidence``/``categorical`` are ``None`` IFF floor-Fail (DEC-3 invariant); ``gap`` is
     populated IFF floor-Fail. ``matched_count``/``min_count``/``floor_reason`` echo the FloorResult.

  7. **Never-raise (Constraint 5).** Malformed state / non-list evidence / a raising or non-numeric
     assessor / a raising mapping → deterministic degrade (clamp / skip / empty), NEVER a propagated
     exception. The node always returns a valid ``{"sufficiency", "next_action"}`` partial.

  8. **Determinism (AD-12).** No LLM, no wall-clock, no random, no IO in the node. Same
     ``(state, floor_checker, assessor, mapping, write_threshold)`` → identical verdict + next_action
     across calls AND across PYTHONHASHSEED.

ONE-WAY (AD-1 / gate #2 HARD-FAIL): imports ``graph.compiled`` (same layer — for the LOCKED ``NA_*``
routing vocabulary: "import them, do NOT redefine") + ``graph.floor_check`` (same layer — the consumed
4.1 mechanism) + ``graph.state`` (same layer) + stdlib ONLY (``collections.abc`` / ``typing``). NO
``services``/``routers``/``adapters``/``tools`` back-edge. NO ``config``/``yaml``/``pydantic``/LLM import
in the NODE — config + yaml loading live at the composition root (:mod:`graph.compiled`). NO file IO, no
``random``/``time``/``datetime``/``uuid``. lint-imports: 1 contract kept / 0 broken.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import cast

from graph.compiled import NA_GATHER_MORE, NA_REPLAN, NA_WRITE
from graph.floor_check import FloorChecker, FloorResult
from graph.state import InvestigationState, JsonValue

# ONE-WAY (AD-1 / gate #2): graph.compiled (same layer — the LOCKED NA_* routing vocabulary) +
# graph.floor_check (same layer — the consumed 4.1 mechanism) + graph.state (same layer) + stdlib ONLY.
# NO services/routers/adapters/tools back-edge. NO config/yaml/pydantic/LLM/random/time import in the
# node. The composition root (graph.compiled.build_default_compiled_runner) owns the yaml→registry load.

# ---------------------------------------------------------------------------
# POC-default calibration CONSTANTS (D4 / AC4 — calibrate via the Epic-6 benchmark; the node logic
# references these BY NAME — ZERO bare numeric literals inline in any function body). These module-level
# constants are the ONLY numerics in the module; every threshold / breakpoint / bound is named here.
# ---------------------------------------------------------------------------

#: The AD-7 confidence authority FLOOR (clamp lower bound — empty/zero confidence). POC default.
_CONFIDENCE_FLOOR: float = 0.0
#: The AD-7 confidence authority CEILING (clamp upper bound). POC default.
_CONFIDENCE_CEILING: float = 1.0
#: Evidence-count saturation point for the default assessor: ``count >= this`` → confidence saturates at
#: the ceiling. POC default — calibrate Epic-6 (D4).
_EVIDENCE_SATURATION: int = 4
#: Write-decision threshold: a floor-Pass ceiling ``>= this`` routes ``write``; below → ``replan``. POC
#: default — calibrate Epic-6 (D4). THE authoritative threshold (AC4).
DEFAULT_WRITE_THRESHOLD: float = 0.7
#: Categorical band breakpoints {low, med, high} (POC default — calibrate Epic-6, D4). confidence
#: ``< _BAND_LOW_MAX`` → low; ``[_BAND_LOW_MAX, _BAND_MED_MAX)`` → med; ``>= _BAND_MED_MAX`` → high.
_BAND_LOW_MAX: float = 0.4
_BAND_MED_MAX: float = 0.7

# Categorical vocabulary (LOCKED — the {low, med, high} labels + the never-raise degrade fallback).
_CAT_LOW: str = "low"
_CAT_MED: str = "med"
_CAT_HIGH: str = "high"
_CAT_UNKNOWN: str = "unknown"

# Honest "chưa đủ" gap prefix (carried on max-iter → PARTIAL — FR-7 / AD-10 #5).
_GAP_PREFIX: str = "chưa đủ — cần thêm bằng chứng"

#: Confidence ceiling seam — ``(evidence) -> float`` in ``[0.0, 1.0]`` (AD-7 authority). Injected at
#: factory time; the default is pure/deterministic/derived. An LLM-enriched assessor may swap in later.
type ConfidenceAssessor = Callable[[Sequence[Mapping[str, object]]], float]

#: Categorical mapping seam — ``(confidence) -> str`` label ``{low|med|high}``. Injected at factory time.
type CategoricalMapping = Callable[[float], str]


def _clamp_confidence(value: float) -> float:
    """Clamp a numeric to the AD-7 authority range ``[_CONFIDENCE_FLOOR, _CONFIDENCE_CEILING]``.

    Defensive (never-raise): bounds the ceiling so an assessor can never escape ``[0, 1]``.
    """
    if value < _CONFIDENCE_FLOOR:
        return _CONFIDENCE_FLOOR
    if value > _CONFIDENCE_CEILING:
        return _CONFIDENCE_CEILING
    return value


def default_deterministic_confidence_assessor(evidence: Sequence[Mapping[str, object]]) -> float:
    """DEFAULT confidence ceiling — pure deterministic, DERIVED from evidence structure (AD-12 / AC4).

    Every token is a function of ``evidence`` alone:
      - the count of evidence items (structural; no field-name hashing → PYTHONHASHSEED-safe);
      - a saturation term: confidence grows with count until it reaches :data:`_EVIDENCE_SATURATION`
        items, then saturates at the ceiling (diminishing-returns — more evidence past saturation does
        not raise confidence beyond the ceiling).

    No LLM, no wall-clock, no random, no IO (AD-12). The assessor is ONLY consulted on floor-Pass
    (DEC-3) — it can NEVER override a deterministic floor-Fail. Returned value is clamped to ``[0, 1]``.
    """
    items = [item for item in evidence if isinstance(item, Mapping)]
    count = len(items)
    if not count:
        return _CONFIDENCE_FLOOR  # empty evidence → zero confidence (AD-7 honest; the floor still gates)
    saturation = min(count, _EVIDENCE_SATURATION) / _EVIDENCE_SATURATION
    return _clamp_confidence(saturation)


def default_categorical_mapping(confidence: float) -> str:
    """DEFAULT categorical ``{low|med|high}`` derivation from a numeric ceiling (AD-7; AC4 bands).

    Uses the named band constants (:data:`_BAND_LOW_MAX` / :data:`_BAND_MED_MAX`) — ZERO inline
    numerics. Deterministic (AD-12).
    """
    if confidence < _BAND_LOW_MAX:
        return _CAT_LOW
    if confidence < _BAND_MED_MAX:
        return _CAT_MED
    return _CAT_HIGH


def _read_canonical_trigger(state: InvestigationState) -> str:
    """Read ``state["trigger"]["canonical_trigger"]`` DEFENSIVELY (3.1/3.4 precedent).

    Missing / non-Mapping trigger / non-str ``canonical_trigger`` → ``""`` → the floor check returns
    fail-closed "unknown-trigger" (anti-hallucination). Never raises (Constraint 5).
    """
    trigger = state.get("trigger")
    if not isinstance(trigger, Mapping):
        return ""
    canonical = trigger.get("canonical_trigger")
    return canonical if isinstance(canonical, str) else ""


def _read_evidence(state: InvestigationState) -> Sequence[Mapping[str, object]]:
    """Read ``state["evidence"]`` as a Sequence of Mapping DEFENSIVELY (non-list → empty).

    The floor check (4.1) + the assessor both consume this. Never raises (Constraint 5).
    """
    raw = state.get("evidence")
    if not isinstance(raw, list):
        return ()
    items: list[Mapping[str, object]] = []
    for item in raw:
        if isinstance(item, Mapping):
            items.append(cast(Mapping[str, object], item))
    return items


def _assess_confidence(
    assessor: ConfidenceAssessor, evidence: Sequence[Mapping[str, object]]
) -> float:
    """Consult the assessor seam; NEVER-raise (Constraint 5): a raising / non-numeric / out-of-range
    assessor degrades to :data:`_CONFIDENCE_FLOOR` (zero confidence) — deterministic, never an exception.

    A ``bool`` return is rejected (``bool`` is an ``int`` subclass — ``True`` must not silently read as
    confidence ``1.0``). The accepted numeric is clamped to ``[0, 1]``.
    """
    try:
        value = assessor(evidence)
    except Exception:  # noqa: BLE001 — an injected assessor must never break REF (Constraint 5)
        return _CONFIDENCE_FLOOR
    if isinstance(value, bool) or not isinstance(value, int | float):
        return _CONFIDENCE_FLOOR
    return _clamp_confidence(float(value))


def _categorical_label(mapping: CategoricalMapping, confidence: float) -> str:
    """Derive the categorical label via the mapping seam; NEVER-raise (Constraint 5): a raising /
    non-str mapping degrades to :data:`_CAT_UNKNOWN`. (Routing uses the NUMERIC ceiling vs the write
    threshold, so a degraded label never changes the route.)
    """
    try:
        label = mapping(confidence)
    except Exception:  # noqa: BLE001 — an injected mapping must never break REF (Constraint 5)
        return _CAT_UNKNOWN
    return label if isinstance(label, str) and label else _CAT_UNKNOWN


def _fail_gap(floor_result: FloorResult) -> str:
    """Honest "chưa đủ" gap DERIVED from the FloorResult's 4 fields (DEC-3: populated IFF floor-Fail).

    ``FloorResult`` does NOT carry ``source_type`` (the 4.1 seam is intentionally minimal), so the gap
    is expressed in terms of the counts + reason the floor actually exposes — no invented detail.
    """
    return (
        f"{_GAP_PREFIX} "
        f"(matched {floor_result.matched_count}, min {floor_result.min_count}: "
        f"{floor_result.reason})"
    )


def _sufficiency_fail(floor_result: FloorResult) -> dict[str, JsonValue]:
    """floor-Fail verdict (DEC-3): the ceiling was NEVER consulted → ``ceiling_confidence``/``categorical``
    are ``None`` (no RC conclusion is possible); the honest ``gap`` is populated."""
    return {
        "floor_pass": False,
        "ceiling_confidence": None,  # DEC-3: ceiling NOT consulted on floor-Fail
        "categorical": None,  # DEC-3: no categorical without a ceiling
        "matched_count": floor_result.matched_count,
        "min_count": floor_result.min_count,
        "floor_reason": floor_result.reason,
        "gap": _fail_gap(floor_result),  # populated IFF floor-Fail (FR-7 / AD-10 #5 honest)
    }


def _sufficiency_pass(
    floor_result: FloorResult, ceiling_confidence: float, categorical: str
) -> dict[str, JsonValue]:
    """floor-Pass verdict: the ceiling WAS consulted → ``ceiling_confidence`` numeric + ``categorical``
    set; ``gap`` is ``None`` (the floor is met)."""
    return {
        "floor_pass": True,
        "ceiling_confidence": ceiling_confidence,
        "categorical": categorical,
        "matched_count": floor_result.matched_count,
        "min_count": floor_result.min_count,
        "floor_reason": floor_result.reason,
        "gap": None,  # no gap on floor-Pass
    }


def build_reflector(
    *,
    floor_checker: FloorChecker,
    confidence_assessor: ConfidenceAssessor = default_deterministic_confidence_assessor,
    categorical_mapping: CategoricalMapping = default_categorical_mapping,
    write_threshold: float = DEFAULT_WRITE_THRESHOLD,
) -> Callable[[InvestigationState], dict[str, JsonValue]]:
    """Factory: build the §3.5 reflector (REF) node (DI seam — mirrors 1-3/3-1/3-2/3-3/3-4/3.5/4.2).

    Returns a node ``(state) -> partial-state-dict`` that on each visit:
      - reads ``canonical_trigger`` + ``evidence`` defensively;
      - runs the deterministic floor (4.1) FIRST;
      - **DEC-3**: on ``floor_pass=False`` → returns ``{"sufficiency": <fail-verdict>, "next_action":
        NA_GATHER_MORE}`` and the confidence ceiling is NEVER consulted (no RC conclusion);
      - on ``floor_pass=True`` → consults the AD-7 ceiling (clamped), derives the categorical, routes
        ``NA_WRITE`` (ceiling >= write_threshold) / ``NA_REPLAN`` (ceiling < write_threshold), and
        returns ``{"sufficiency": <pass-verdict>, "next_action": <write|replan>}``.

    The ``next_action`` vocabulary ``{gather_more, replan, write}`` is IMPORTED from
    :mod:`graph.compiled` (single source of truth — no drift from the routing edges 3.5 wired).

    Args:
        floor_checker: the REQUIRED :data:`graph.floor_check.FloorChecker` (build via
            :func:`graph.floor_check.build_floor_check`). The pure 4.1 mechanism; consumed, NOT modified.
        confidence_assessor: the :data:`ConfidenceAssessor` ceiling seam (default
            :func:`default_deterministic_confidence_assessor` — pure/deterministic/derived). An
            LLM-enriched assessor may swap in later WITHOUT rewiring. Consulted ONLY on floor-Pass.
        categorical_mapping: the :data:`CategoricalMapping` label seam (default
            :func:`default_categorical_mapping`). Consulted ONLY on floor-Pass.
        write_threshold: the ceiling ``>=``-this threshold for ``write`` vs ``replan`` (default
            :data:`DEFAULT_WRITE_THRESHOLD` — POC; calibrate Epic-6, D4).

    Returns:
        a §3.5 node returning PARTIAL state ``{"sufficiency": <verdict>, "next_action": <str>}``
        (AD-4 — exactly two scalar-replace keys).
    """

    def reflector(state: InvestigationState) -> dict[str, JsonValue]:
        canonical_trigger = _read_canonical_trigger(state)
        evidence = _read_evidence(state)

        # DEC-3 (load-bearing): the deterministic floor FIRST. On floor-Fail the ceiling is NEVER
        # consulted — the assessor call below is textually UNREACHABLE on this branch (a spy records
        # call-count == 0). gather_more; NO root-cause conclusion is possible.
        floor_result = floor_checker(canonical_trigger, evidence)
        if not floor_result.floor_pass:
            return {
                "sufficiency": _sufficiency_fail(floor_result),
                "next_action": NA_GATHER_MORE,  # DEC-3: floor-Fail → gather_more (NEVER write)
            }

        # floor-Pass: NOW (and only now) consult the AD-7 confidence ceiling (DI seam). Routing uses the
        # NUMERIC ceiling vs the write threshold (the categorical label is audit detail, not the route).
        ceiling = _assess_confidence(confidence_assessor, evidence)
        categorical = _categorical_label(categorical_mapping, ceiling)
        next_action = NA_WRITE if ceiling >= write_threshold else NA_REPLAN
        return {
            "sufficiency": _sufficiency_pass(floor_result, ceiling, categorical),
            "next_action": next_action,
        }

    return reflector


__all__ = [
    "CategoricalMapping",
    "ConfidenceAssessor",
    "DEFAULT_WRITE_THRESHOLD",
    "build_reflector",
    "default_categorical_mapping",
    "default_deterministic_confidence_assessor",
]
