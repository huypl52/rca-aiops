"""plan_validator — §3.5 PE-R Plan read-only GATE node (Story 3.3 — FR-4/FR-5 / AD-3 / §4.3/§4.4/§3.8).

The **fourth** §3.5 node (flow ``ICB→PBR→HYP→VAL→EXR→ENV→REF``). It is a **pure
VALIDATION** node — the **GRAPH-level SECOND layer** of the read-only boundary
(defense-in-depth):

  - **Layer 1 (HARD enforcement) = the read-only tool registry (2-1) + CI gate #1.**
    Registration of any deny-verb tool is REJECTED (CI #1 HARD-FAIL). This is the
    load-bearing structural guard — a write tool simply cannot be registered, so
    ``executor_router`` (3.5) can never dispatch it.
  - **Layer 2 (this node) = the pre-dispatch graph gate.** ``plan_validator`` inspects
    ``state.plan`` and rejects offending (write/exec/patch/probe-đột-xuất) OR vague
    plans BEFORE ``executor_router`` (3.5) ever sees them, driving ``replan`` back to
    ``hypothesis_planner`` (3.2). It is defense-in-depth, NOT a duplicate of registry
    enforcement — it guards against a plan that NAMES a write action even if no such
    tool is registered (e.g. a free-text ``kubectl exec`` command string in the plan).

It makes **NO adapter call** (unlike 3-1), **NO ``executor_router`` call**, executes
NOTHING. It REUSES the canonical ``ci.denyset`` (single source of truth) — it does
NOT reinvent a verb list.

LOCKED mechanism (do NOT redesign):
  1. **Input = ``state.plan`` (the current plan under consideration; ``dict | None``).**
     The "which hypothesis's plan is promoted to ``state.plan``" SELECTION is graph
     wiring (3.5) — NOT this node's job. It validates THE plan in ``state.plan``; it
     does NOT iterate ``state.hypotheses`` and invents NO selection step.
  2. **Read-only check — REUSE ``ci.denyset``; do NOT reinvent.** Imports
     ``from ci.denyset import WRITE_PATTERNS, WRITE_VERBS``. Scans the plan's string
     content for:
       - **WRITE_VERBS** — exact-token, case-insensitive match over every string leaf
         (see :func:`_verb_matches`). Tokens are alphanumeric runs split on
         non-alphanumeric chars; an exact-set membership avoids false positives
         (``exec`` does NOT match inside ``execute_metric`` / ``process_exec_summary``)
         while STILL catching snake-case forms (``restart_pods`` → token ``restart``
         → MATCH; note regex ``\\b`` would WRONGLY miss these because ``\\w`` includes
         ``_``). Covers §3.8's 7 forbidden + catch-all ``write``.
       - **WRITE_PATTERNS** — ``re.Pattern.search`` over the JSON-serialized plan +
         each leaf (catches command-string forms: ``kubectl debug/exec/patch``,
         ``rollout restart/undo``, ``helm uninstall``, ``terraform destroy``, ``rm -rf``).
     Either hit → **read-only violation**. The module AST-proves NO hardcoded duplicate
     verb list — it MUST import ``ci.denyset`` (the single source of truth).
  3. **Specificity check — the plan must identify the evidence to gather.** A valid plan
     has non-empty ``tool`` + ``query`` + ``timestamp_range`` (the evidence-identifying
     trio; aligned with §3.6 Evidence required fields + carry-forward 2-3-A1's dedupe key
     ``timestamp_range``). Missing/empty ANY → **vague** (reject/replan, but NOT a
     security violation → no ``safety_flags``). The exact field set is a factory param
     (default the trio); the VALUES are DEFERRED.
  4. **Verdict → partial state (AD-4):**
       - **PASS** (read-only + specific): ``next_action = "proceed"`` (routing signal →
         EXR). No ``safety_flags``.
       - **REJECT read-only violation**: ``safety_flags`` dict entry (security AUDIT —
         ``{type:"plan_readonly_violation", matched:<token>, detail:<...>}``) AND
         ``next_action = "replan"`` (→ HYP).
       - **REJECT vague** (inspecific, but read-only-clean): ``next_action = "replan"``
         (→ HYP). **NO ``safety_flags``** — vagueness is not a security violation.
  5. **``next_action`` is the routing signal.** Values used here: ``"proceed"`` |
     ``"replan"``. (``"proceed"`` is plan_validator-introduced; ``next_action`` is a
     free-form routing ``str`` with the replace reducer, so this is fine — documented.)
  6. **Graceful degrade (Constraint 5) — NEVER raises into the graph.** Missing / None /
     non-dict ``state.plan`` → never raises; verdict = ``next_action = "replan"``
     (nothing valid to execute; the graph loops back to HYP, bounded by ``max_iterations``
     FR-7). Wrapped defensively.
  7. **AD-4 partial state** — return ONLY the keys written: always ``next_action``;
     ``safety_flags`` ONLY on a read-only violation. No invented keys. Does NOT write
     ``plan``/``hypotheses``/``evidence``/``tool_calls``.
  8. **DI seam = factory for consistency + future-injectability** (mirrors 1-3/3-1/3-2):
     ``build_plan_validator(*, required_fields=("tool","query","timestamp_range"))``. The
     deny-set is a STATIC import (NOT injected — it is the canonical source). The factory
     makes the specificity field-set configurable (the seam for future hardening, e.g.
     an allowed-tools set — **DEFERRED**; the registry already catches unregistered tools
     at 3.5, so plan_validator stays registry-free).

Probe-burst interpretation (leader FLAG): active/disruptive "probe-đột-xuất" forms
(restart / scale / exec / kubectl-debug) are caught by ``WRITE_VERBS`` + ``WRITE_PATTERNS``
HERE (string-level); an UNKNOWN tool name (a "probe-burst" as an unregistered tool) is
caught by ``executor_router``'s ``registry.lookup`` KeyError envelope at 3.5 (registry =
2-1). This node is registry-free and does NOT duplicate that unregistered-tool rejection.

3.2 interaction note (leader FLAG): 3.2's default hypothesis plan is
``{playbook_id, playbook_title}`` — it legitimately FAILS this specificity check (no
``tool``/``query``/``timestamp_range``) → ``replan``. That is HONEST fail-closed behavior
(AD-12/FR-7), NOT a bug. 3.3 tests inject plans WITH the trio (pass) and WITHOUT (reject)
and do NOT depend on 3.2's default output.

ONE-WAY (AD-1 / gate #2): imports ``graph.state`` (same layer) + ``ci.denyset`` (ALLOWED —
``ci/`` is NOT in importlinter ``root_packages`` {routers,services,graph,adapters,tools}, so
it is OUTSIDE the layered contract; precedent: ``tools/registry.py:27`` already imports
``ci.denyset``) + stdlib only. **CRITICAL: this node does NOT import ``tools``/``registry``**
— the unregistered-tool case is 3.5's job. NEVER ``routers``/``services``/``adapters``/
``models``/``tools`` (back-edge forbidden).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping

from ci.denyset import WRITE_PATTERNS, WRITE_VERBS
from graph.state import InvestigationState, JsonValue

# ONE-WAY (AD-1 / gate #2): graph.state (same layer) + ci.denyset (NOT a contracted layer;
# precedent tools/registry.py:27) + stdlib ONLY. NO tools/adapters/models/routers/services.

_DEFAULT_REQUIRED_FIELDS: tuple[str, ...] = ("tool", "query", "timestamp_range")
"""POC specificity trio — the evidence-identifying fields (§3.6 + carry-forward 2-3-A1).
The MECHANISM (require non-empty identifying fields) is locked; the exact field SET is an
injected factory param and the field VALUES are **DEFERRED** (a 3.3/4.x concern). This is
the offline-test POC default, NOT a tuned final."""

_VIOLATION_TYPE: str = "plan_readonly_violation"
"""Discriminator for a ``safety_flags`` entry written by this node (security audit trail)."""

# Split a string into alphanumeric tokens (a-z, 0-9) — every non-alphanumeric char is a
# separator. This is the "word boundary" the read-only deny-set needs: regex `\b` would
# WRONGLY treat `_` as a word char (it is in `\w`), missing snake-case offending forms like
# `restart_pods` / `exec_metric`. Tokenize-then-exact-match catches those AND avoids
# false positives (`exec` inside `execute_metric` → token `execute` ≠ `exec`; benign
# `http_requests_total` → tokens none of which is a forbidden verb).
_TOKEN_SPLIT = re.compile(r"[^a-zA-Z0-9]+")


def _collect_strings(plan: Mapping[str, JsonValue]) -> list[str]:
    """Recursively collect every string leaf from the JSON-safe plan + the serialized form.

    Defense-in-depth: the deny-set is scanned over (a) each individual string leaf AND (b)
    the full ``json.dumps`` of the plan. ``WRITE_VERBS`` runs as tokenize-exact-match on
    the leaves; ``WRITE_PATTERNS`` runs as ``re.Pattern.search`` over the serialized form
    (command strings like ``kubectl exec ...`` survive serialization). Both layers scanned.
    """
    strings: list[str] = []

    def _walk(value: JsonValue) -> None:
        if isinstance(value, str):
            strings.append(value)
        elif isinstance(value, list):
            for item in value:
                _walk(item)
        elif isinstance(value, dict):
            for item in value.values():
                _walk(item)

    for v in plan.values():
        _walk(v)
    # Also scan the serialized whole (catches command-string patterns + any ordering nuance).
    strings.append(json.dumps(dict(plan), ensure_ascii=False, sort_keys=True))
    return strings


def _verb_matches(strings: list[str]) -> list[str]:
    """Return the distinct WRITE_VERBS found as exact tokens (case-insensitive) in ``strings``.

    Token-by-``_TOKEN_SPLIT`` then lowercase exact-set membership. Dedupes (one audit entry
    per distinct offending verb) while preserving first-seen order (deterministic).
    """
    found: list[str] = []
    seen: set[str] = set()
    for s in strings:
        for tok in _TOKEN_SPLIT.split(s.lower()):
            if tok and tok in WRITE_VERBS and tok not in seen:
                seen.add(tok)
                found.append(tok)
    return found


def _pattern_matches(strings: list[str]) -> list[str]:
    """Return the distinct WRITE_PATTERNS matches (``re.Pattern.search``) in ``strings``.

    Each match contributes its matched substring as the audit token. Dedupes (one entry per
    distinct matched command-string form) while preserving first-seen order (deterministic).
    """
    found: list[str] = []
    seen: set[str] = set()
    for s in strings:
        for pat in WRITE_PATTERNS:
            match = pat.search(s)
            if match is not None:
                matched = match.group(0)
                if matched not in seen:
                    seen.add(matched)
                    found.append(matched)
    return found


def _scan_readonly_violations(plan: Mapping[str, JsonValue]) -> list[str]:
    """Return the ordered, distinct read-only deny-set tokens matched anywhere in the plan.

    Verbs (exact-token) first, then command-string patterns. Each token is one audit entry.
    Returns ``[]`` for a read-only-clean plan.
    """
    strings = _collect_strings(plan)
    return [*_verb_matches(strings), *_pattern_matches(strings)]


def _has_field(plan: Mapping[str, JsonValue], field: str) -> bool:
    """True iff ``plan[field]`` is present and non-empty (specificity check).

    Empty string / empty dict / empty list / None / missing → not specific. Other truthy
    scalars (numbers, bools) count as present. The VALUE shape is DEFERRED — only the
    "identifies the evidence to gather" non-emptiness is locked here.
    """
    value: object = plan.get(field)
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, dict | list):
        return len(value) > 0
    return bool(value)


def _is_specific(plan: Mapping[str, JsonValue], required_fields: tuple[str, ...]) -> bool:
    """True iff EVERY required identifying field is present and non-empty."""
    return all(_has_field(plan, f) for f in required_fields)


def build_plan_validator(
    *,
    required_fields: tuple[str, ...] = _DEFAULT_REQUIRED_FIELDS,
) -> Callable[[InvestigationState], dict[str, JsonValue]]:
    """Factory: build the §3.5 plan_validator read-only GATE node.

    Returns a node ``(state) -> partial-state-dict`` that:
      - reads ``state["plan"]`` defensively (missing/None/non-dict → graceful degrade);
      - scans it for read-only deny-set violations (REUSES ``ci.denyset`` — verbs +
        command-string patterns);
      - checks specificity (every ``required_fields`` entry present + non-empty);
      - writes the verdict: always ``next_action`` (``"proceed"`` | ``"replan"``);
        ``safety_flags`` (a dict of audit entries) ONLY on a read-only violation;
      - NEVER raises into the graph (Constraint 5).

    Args:
        required_fields: the evidence-identifying trio (default ``tool``/``query``/
            ``timestamp_range``). The MECHANISM is locked; the SET is configurable and the
            VALUES are DEFERRED.

    Returns:
        a §3.5 node returning PARTIAL state — always ``{"next_action": ...}`` and, on a
        read-only violation only, also ``{"safety_flags": {...}}`` (AD-4 — no other keys).
    """

    def plan_validator(state: InvestigationState) -> dict[str, JsonValue]:
        # Constraint 5 — never raise: a missing/None/non-dict plan is nothing valid to
        # execute → replan (the graph loops back to HYP, bounded by max_iterations FR-7).
        plan = state.get("plan")
        if not isinstance(plan, Mapping):
            return {"next_action": "replan"}

        # Layer 2 read-only gate (defense-in-depth; registry 2-1 is the HARD layer).
        violations = _scan_readonly_violations(plan)
        if violations:
            # Security AUDIT — one ``safety_flags`` entry per distinct offending token.
            # ``safety_flags`` is a dict (key-merge reducer); enumerate deterministic keys
            # ``pv_NNN`` so distinct tokens in one call accumulate (a repeated key across
            # replans shallow-overwrites — the per-flag deep-merge shape is DEFERRED).
            flags: dict[str, JsonValue] = {}
            for idx, matched in enumerate(violations, start=1):
                flags[f"pv_{idx:03d}"] = {
                    "type": _VIOLATION_TYPE,
                    "matched": matched,
                    "detail": f"plan content matched read-only deny-set token '{matched}'",
                }
            return {"next_action": "replan", "safety_flags": flags}

        # Vague (read-only-clean but not specific) → replan, NO safety_flags (not a
        # security violation, just insufficient to identify evidence).
        if not _is_specific(plan, required_fields):
            return {"next_action": "replan"}

        # PASS — read-only + specific; route to executor_router (3.5).
        return {"next_action": "proceed"}

    return plan_validator


__all__ = ["build_plan_validator"]
