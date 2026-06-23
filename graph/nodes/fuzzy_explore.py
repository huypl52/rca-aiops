"""fuzzy_explore — §4.3 fuzzy sub-graph explore (Story 3.4 — FR-4 / A1 / spec §4.3).

**A DIFFERENT KIND OF STORY than 3.1/3.2/3.3** (each was ONE §3.5 node). This module is **NOT a
node.** The §3.5 node table has EXACTLY 8 nodes (``ICB→PBR→HYP→VAL→EXR→ENV→REF(+WRT)``) — there is
NO "explore" node. ARCHITECTURE-SPINE.md Capability→Map (line 279) maps FR-4 — **including the fuzzy
sub-graph explore** — to ``graph/hypothesis_planner`` + ``plan_validator``, NOT to a new node. The
"internal sub-graph" the spec names IS the **EXISTING** PE-R loop
(``HYP→VAL→EXR→ENV→REF→HYP``), which **3.5 wires** and **4.x (reflector)** drives. So 3.4 delivers the
**fuzzy-detection + hypothesis-expansion CAPABILITY that FEEDS that loop** — offline-testable,
deterministic — and explicitly does NOT build the loop.

A1 LOCK — PE-R ONLY, NO ReAct (THE load-bearing constraint, leader DEEP spotlight #1):
  The expanded hypothesis set is fed to the EXISTING PE-R loop. There is **NO** ReAct reasoner, **NO**
  ``thought``/``action``/``observation`` cycle, **NO** outer ``while``-loop, **NO** separate agent,
  **NO** new graph node/edge. The "sub-graph khám phá nội bộ" = the existing loop now carrying a
  RICHER (exploratory) hypothesis set. This module introduces NONE of those — it is a thin SELECTOR
  (fuzzy? expansion_source : base_source) composed over 3.2's ``hypothesis_planner``.

  **The discarded design (do NOT build it):** the OLD PRD memlog (``prd-26-rca-aiops-2026-06-23/
  .memlog.md`` line 12) literally says *"§4.3 Hypothesis Planning (FR-4, PE-R + degrade ReAct cho
  fuzzy)"*. That "degrade ReAct for fuzzy" idea was **REVERSED by the reconcile decision A1**. The
  canonical truth is epics.md FR-4 (line 58) + Story 3.4 (lines 474-491): *"PE-R là pattern duy
  nhất; scenario fuzzy → sub-graph nội bộ PE-R (KHÔNG switch ReAct)"*. If you find yourself adding a
  ReAct reasoner, an outer while-loop, a thought/action/observation cycle, or a separate agent —
  STOP. That is the discarded design. A1 = stay in PE-R.

LOCKED mechanism (do NOT redesign):
  1. **NO new node / edge / state-key.** The 13-key AD-9 spine is UNCHANGED (there is NO
     fuzzy/explore key, and we add NONE). The fuzzy expansion MANIFESTS as additional entries in the
     EXISTING ``hypotheses`` list, merged via the existing ``upsert_hypotheses`` reducer (0-3).
  2. **detect_fuzzy — a pure deterministic EXACT-TOKEN membership test.**
     ``detect_fuzzy(canonical_trigger, *, fuzzy_set) -> bool`` = ``canonical_trigger ∈ fuzzy_set``.
     ``canonical_trigger`` is a PascalCase domain enum (§3.4), so exact-set membership is the correct,
     deterministic, no-false-positive test (NOT substring/regex/LLM). ``None``/missing/non-str trigger
     → ``False`` (not fuzzy → normal path; never raises — mirrors 3.1's defensive
     ``canonical_trigger`` read). The MECHANISM is LOCKED; the SET is injected (factory param); POC
     default = ``{"DNSFailureLogSpike", "CertificateErrorDetected"}`` (the spec's named fuzzy
     examples). Deterministic (AST-proven: no ``random``/``time``/``datetime``/``uuid``).
  3. **Exploratory EXPANSION source — a Protocol-compatible HypothesisSource emitting a BROADER
     exploratory descriptor set.** A pure function ``(context, playbook_hits, evidence) -> list[
     descriptor WITHOUT id]``, structurally compatible with 3.2's ``HypothesisSource``. It emits
     multiple candidate root-causes (the "mở rộng hypothesis" of the spec) — MORE than 3.2's
     single-path-per-playbook default for the same inputs. The expansion CONTENT (which candidate
     root-causes per trigger) is **DEFERRED** — a POC deterministic stub; the real multi-cause LLM
     expansion is the AD-10 designated swappable non-determinism point (3-5/app/Epic 7).
  4. **build_fuzzy_aware_hypothesis_planner — COMPOSE over 3.2 (zero duplication).**
     ``build_fuzzy_aware_hypothesis_planner(*, fuzzy_set, base_source, expansion_source,
     max_hypotheses)`` builds TWO 3.2 planners — one over ``base_source`` (the non-fuzzy default),
     one over ``expansion_source`` — and the returned node SELECTS which to call per ``state``:
     reads ``state["trigger"]["canonical_trigger"]`` DEFENSIVELY → ``detect_fuzzy`` → fuzzy calls the
     expansion planner, else the base planner. **id-stamping (``H01..``) + shape discipline + merge +
     graceful degrade + partial-state are ALL delegated to 3.2's ``build_hypothesis_planner``** — this
     module does NOT reimplement ``_stamp_ids``, does NOT stamp ids, does NOT reimplement
     merge/dedupe. This is the same reuse discipline 3.2 applied to 0-3's reducer.
  5. **AC2 (max-iter → partial "chưa đủ") is a GRAPH-LEVEL bound, NOT built here.** The expansion is
     a SINGLE bounded operation (it does NOT loop — it emits a capped set once per planner call). Full
     convergence / max-iter→partial is realized by **3.5's compiled-graph runner** (carry-forward
     1-A4: runner MUST honor ``max_iterations``) + **4.x's reflector** (partial "chưa đủ"). 3.4
     CONTRIBUTES the bounded expansion that feeds that loop; it does NOT claim AC2 "done".
  6. **Graceful degrade (Constraint 5) — NEVER raises into the graph.** Missing/non-dict trigger /
     non-str ``canonical_trigger`` → not fuzzy → base planner (which itself degrades to
     ``{"hypotheses": []}`` on empty inputs / a source raise / malformed state). The canonical-trigger
     read is defensive and never raises.
  7. **AD-4 partial state — return EXACTLY one key ``{"hypotheses": [...]}``** (inherited from 3.2's
     delegated planners). No ``next_action``/``safety_flags``/invented keys (those belong to 3.3/4.x).

ONE-WAY (AD-1 / gate #2 HARD-FAIL): imports ``graph.state`` (same layer) +
``graph.nodes.hypothesis_planner`` (SAME graph layer — reuse ``build_hypothesis_planner``,
``HypothesisSource``, ``_rule_based_source``, ``_DEFAULT_MAX_HYPOTHESES``) + stdlib ONLY. **NO
``tools``/``adapters``/``models``/``routers``/``services``** (back-edge forbidden). graph→graph is
same-layer (allowed). ``lint-imports`` 1 kept / 0 broken. (graph→ci would also be allowed but is NOT
needed here.)
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from graph.nodes.hypothesis_planner import (
    _DEFAULT_MAX_HYPOTHESES,
    HypothesisSource,
    _rule_based_source,
    build_hypothesis_planner,
)
from graph.state import InvestigationState, JsonValue

# ONE-WAY (AD-1 / gate #2): graph.state (same layer) + graph.nodes.hypothesis_planner (SAME graph
# layer — REUSED, not copied) + stdlib ONLY. NO tools/adapters/models/routers/services (back-edge
# forbidden). graph→graph is same-layer, allowed.

_DEFAULT_FUZZY_SET: frozenset[str] = frozenset({"DNSFailureLogSpike", "CertificateErrorDetected"})
"""POC default fuzzy-trigger set — the spec's named fuzzy examples (Story 3.4 AC). The MECHANISM
(exact-token membership) is locked; the SET is an injected factory param. This is the offline-test
POC default, NOT a tuned/calibrated final set (which candidate triggers count as "fuzzy" is a
benchmark concern, DEFERRED)."""

# POC defaults for the exploratory expansion source's descriptor fields. These are aligned with 3.2's
# POC defaults (``_DEFAULT_PRIORITY`` / ``_DEFAULT_STATUS``) and are self-contained here to keep the
# expansion source dependency-light (no extra private-name import). The priority SCALE + status ENUM
# vocabulary are **DEFERRED** (inherited from 3.2's DEFERRED semantics) — these are stable POC
# placeholders, NOT tuned values.
_EXPLORATORY_PRIORITY: int = 1
"""POC deterministic priority for an exploratory candidate hypothesis (aligned w/ 3.2's default)."""

_EXPLORATORY_STATUS: str = "proposed"
"""POC deterministic status for an exploratory candidate hypothesis (aligned w/ 3.2's default;
status vocab DEFERRED). Awaiting ``plan_validator`` (3.3), same lifecycle as 3.2's hypotheses."""

# POC exploratory candidate root-causes — a DETERMINISTIC stub set emitted by the expansion source.
# This is the "mở rộng hypothesis" of the spec: when the trigger is fuzzy, the planner broadens
# beyond the single-path-per-playbook default to several candidate root-causes. The CONTENT (which
# candidate root-causes map to which fuzzy trigger) is **DEFERRED** (playbook/benchmark); here we
# lock the seam EXISTS as a deterministic pure function with generic stub candidates. The number of
# candidates (>1) is what makes the expansion BROADER than the non-fuzzy path for the same inputs.
_EXPLORATORY_CANDIDATES: tuple[dict[str, JsonValue], ...] = (
    {
        "priority": _EXPLORATORY_PRIORITY,
        "plan": {"candidate_root_cause": "candidate_a", "exploratory": True},
        "status": _EXPLORATORY_STATUS,
    },
    {
        "priority": _EXPLORATORY_PRIORITY,
        "plan": {"candidate_root_cause": "candidate_b", "exploratory": True},
        "status": _EXPLORATORY_STATUS,
    },
    {
        "priority": _EXPLORATORY_PRIORITY,
        "plan": {"candidate_root_cause": "candidate_c", "exploratory": True},
        "status": _EXPLORATORY_STATUS,
    },
)


def detect_fuzzy(canonical_trigger: str | None, *, fuzzy_set: frozenset[str]) -> bool:
    """Pure deterministic EXACT-TOKEN membership test: is ``canonical_trigger`` a fuzzy trigger?

    Returns ``True`` iff ``canonical_trigger`` is a ``str`` AND a member of ``fuzzy_set`` (exact-token
    match — ``canonical_trigger`` is a PascalCase domain enum, §3.4, so membership is the correct,
    no-false-positive test; NOT substring/regex/LLM). ``None`` / non-str → ``False`` (not fuzzy → the
    caller selects the normal base source; never raises — mirrors 3.1's defensive ``canonical_trigger``
    read). Deterministic (AD-12): no LLM, no wall-clock, no random.

    Args:
        canonical_trigger: the §3.4 ``canonical_trigger`` (PascalCase enum) or ``None``/non-str.
        fuzzy_set: the injected set of fuzzy triggers (POC default ``_DEFAULT_FUZZY_SET``).

    Returns:
        ``True`` iff ``canonical_trigger`` is a fuzzy trigger (exact member of ``fuzzy_set``).
    """
    if not isinstance(canonical_trigger, str):
        return False
    return canonical_trigger in fuzzy_set


def _exploratory_source(
    context: Mapping[str, JsonValue],  # noqa: ARG001 — deterministic; consumed by the real LLM source
    playbook_hits: Sequence[Mapping[str, JsonValue]],  # noqa: ARG001 — deterministic; POC stub ignores
    evidence: Sequence[Mapping[str, JsonValue]],  # noqa: ARG001 — deterministic; consumed at 4.x/LLM
) -> list[dict[str, JsonValue]]:
    """DETERMINISTIC POC exploratory expansion source (AD-12): emit a BROAD candidate root-cause set.

    Protocol-compatible with 3.2's :class:`HypothesisSource` (same signature; descriptors carry
    ``priority``/``plan``/``status`` and NO ``id`` — 3.2's node stamps it). When a fuzzy trigger is
    detected, the planner selects THIS source to broaden the hypothesis set beyond 3.2's
    single-path-per-playbook default — this is the "mở rộng hypothesis" of the spec. The emitted set
    is BROADER (≥2 candidate root-causes) than the non-fuzzy path would emit for the same inputs
    (e.g. with empty ``playbook_hits`` the base source emits 0; this source emits the candidate set).

    The expansion CONTENT (which candidate root-causes map to which fuzzy trigger — DNS vs cert,
    resolver vs latency vs coredns, etc.) is **DEFERRED** to the playbook/benchmark; here we lock the
    seam EXISTS as a deterministic pure function with generic stub candidates (``candidate_a/b/c``).
    The real multi-cause LLM expansion is the AD-10 designated swappable non-determinism point, wired
    at the composition root (3-5/app) or Epic 7 (**DEFERRED**).

    ``context`` / ``playbook_hits`` / ``evidence`` are accepted for Protocol compatibility (the real
    LLM source consumes the service + playbooks + evidence gathered so far) but are intentionally
    unused here, keeping this default deterministic + minimal.
    """
    # A defensive COPY of each stub descriptor (callers/reducers must never alias the module constant;
    # the node stamps ids into NEW dicts via 3.2's _stamp_ids, but the source-level dicts are fresh
    # per call so a future mutating source does not corrupt the frozen tuple).
    return [dict(candidate) for candidate in _EXPLORATORY_CANDIDATES]


def build_fuzzy_aware_hypothesis_planner(
    *,
    fuzzy_set: frozenset[str] = _DEFAULT_FUZZY_SET,
    base_source: HypothesisSource = _rule_based_source,
    expansion_source: HypothesisSource = _exploratory_source,
    max_hypotheses: int = _DEFAULT_MAX_HYPOTHESES,
) -> Callable[[InvestigationState], dict[str, JsonValue]]:
    """Factory: build a §4.3 fuzzy-aware hypothesis planner COMPOSED over 3.2's hypothesis_planner.

    Returns a node ``(state) -> {"hypotheses": [...]}`` that, per ``state``, SELECTS which hypothesis
    source feeds 3.2's planner:

      - reads ``state["trigger"]["canonical_trigger"]`` DEFENSIVELY (missing/non-dict/non-str →
        ``None``);
      - ``detect_fuzzy(canonical_trigger, fuzzy_set=fuzzy_set)`` → **fuzzy** selects the
        ``expansion_source`` (a broader exploratory candidate set); **not-fuzzy** selects the
        ``base_source`` (3.2's rule-based default);
      - DELEGATES id-stamping (``H01..``) + shape discipline + merge + graceful degrade + partial-state
        to 3.2's :func:`build_hypothesis_planner` — TWO 3.2 planners are built at factory time (one
        over each source); the node calls the SELECTED one. This module does NOT reimplement
        ``_stamp_ids``, does NOT stamp ids, does NOT reimplement merge/dedupe (the reducer owns merge).

    The expanded set feeds the EXISTING PE-R loop (``HYP→VAL→EXR→ENV→REF→HYP``, wired by 3.5, driven
    by 4.x). There is NO ReAct reasoner / outer loop / separate agent / new node or edge (A1 LOCK —
    see the module docstring + the discarded "degrade ReAct cho fuzzy" PRD memlog note).

    Args:
        fuzzy_set: the injected set of fuzzy triggers (POC default ``_DEFAULT_FUZZY_SET``). The SET is
            DEFERRED (benchmark); the membership-test MECHANISM is locked.
        base_source: the non-fuzzy ``HypothesisSource`` (default 3.2's ``_rule_based_source``).
        expansion_source: the fuzzy exploratory ``HypothesisSource`` (default
            :func:`_exploratory_source`). The real multi-cause LLM expansion is DEFERRED (3-5/app/E7).
        max_hypotheses: cap on emitted hypotheses (POC default 3.2's ``_DEFAULT_MAX_HYPOTHESES``; the
            number is DEFERRED).

    Returns:
        a §4.3 node returning PARTIAL state ``{"hypotheses": [...]}`` (AD-4 — exactly one key,
        inherited from the delegated 3.2 planners).
    """
    # Build TWO 3.2 planners at factory time — one over each source. ALL id-stamping / shape / merge /
    # degrade / partial-state discipline is DELEGATED here (zero duplication of 3.2's _stamp_ids).
    base_planner = build_hypothesis_planner(base_source, max_hypotheses=max_hypotheses)
    expansion_planner = build_hypothesis_planner(expansion_source, max_hypotheses=max_hypotheses)

    def fuzzy_aware_hypothesis_planner(state: InvestigationState) -> dict[str, JsonValue]:
        # Select the source per state via a DEFENSIVE canonical-trigger read (never raises on a
        # missing/non-dict trigger or a non-str canonical_trigger — mirrors 3.1's defensive read).
        # The selected planner (3.2) reads context/playbook_hits/evidence and degrades gracefully.
        canonical = _read_canonical_trigger(state)
        if detect_fuzzy(canonical, fuzzy_set=fuzzy_set):
            return expansion_planner(state)
        return base_planner(state)

    return fuzzy_aware_hypothesis_planner


def _read_canonical_trigger(state: Mapping[str, object]) -> str | None:
    """Read ``state["trigger"]["canonical_trigger"]`` defensively (never raises).

    Returns the ``canonical_trigger`` ``str`` when present, else ``None`` (missing ``trigger`` key /
    non-dict ``trigger`` / missing or non-str ``canonical_trigger``). ``None`` ⇒ not fuzzy ⇒ the
    caller selects the normal base source. Mirrors 3.1's defensive ``canonical_trigger`` read.
    """
    trigger = state.get("trigger")
    if not isinstance(trigger, Mapping):
        return None
    canonical = trigger.get("canonical_trigger")
    if not isinstance(canonical, str):
        return None
    return canonical


__all__ = [
    "HypothesisSource",
    "build_fuzzy_aware_hypothesis_planner",
    "detect_fuzzy",
]
