"""floor_check — §4.1 AD-12 sufficiency rule-floor MECHANISM (Story 4.1 — FR-7 / FR-8 / AD-12 DEC-3).

**A PURE FUNCTION + DECLARATIVE REGISTRY, NOT a graph node.** This is the deterministic anti-hallucination
backbone the LLM ceiling (4.3, AD-7) CANNOT override (DEC-3 — "LLM không override sàn"). The reflector
node (4.3, ``graph/nodes/reflector.py``) will call ``floor_check`` and write
``state.sufficiency.floor_pass``. **4.1 ships the MECHANISM only; 4.3 wires the node.**

This mirrors the established mechanism→node split: 2-1 (registry, pure) → 2-3 (router uses it) → 3-5
(node wires router); 3-2 (planner) → 3-5 (node). Here: **4-1 = mechanism (pure fn), 4-3 = node.**

LOCKED MECHANISM (do NOT redesign — defer only CONTENT/numbers):

  1. **Predicate LANGUAGE (AD-12 rule 4 — lock the language, defer the content).** Operator ENUM is
     EXACTLY ``{label-exact, substring, regex}`` — NO semantic/LLM path:
       - ``label-exact`` → ``evidence[field] == value`` (exact string equality).
       - ``substring``   → ``value in evidence[field]`` (substring containment; field must be str).
       - ``regex``       → ``re.search(value, evidence[field]) is not None`` (field must be str).
     Matcher target-field ENUM is EXACTLY ``{source_name, summary, query}`` — the deterministic STRING
     fields of a §3.6 evidence dict (NOT ``raw_excerpt`` [nullable], NOT ``confidence`` [float], NOT
     ``timestamp_range`` [dict], NOT ``supports``/``contradicts`` [lists]; ``source_type`` is the
     separate top-level filter). Schema-validation REJECTS a matcher whose ``field`` is outside this ENUM.

  2. **Floor spec shape.** Each registry entry (keyed by ``canonical_trigger``) =
     ``{min_count: int (>=1), source_type: str (non-empty), matcher: {field, op, value}}``. A spec is
     SATISFIED for an evidence list when the count of items where
     ``(evidence["source_type"] == spec.source_type) AND (<op>(evidence[field], value) is true)`` is
     ``>= min_count``. Count is order-independent (deterministic verdict). A trigger with "no floor" is
     ABSENCE of a spec → fail-closed (NOT ``min_count: 0``; schema rejects ``min_count < 1``).

  3. **``FloorResult``** = frozen dataclass ``{floor_pass, matched_count, min_count, reason}`` — a PURE
     function of inputs (deterministic). ``reason`` is deterministic human-readable
     (``"pass"`` / ``"fail: matched N < min_count M"`` / ``"fail-closed: unknown-trigger"``).

  4. **DI factory:** ``build_floor_check(*, registry) -> FloorChecker`` where the checker's signature IS
     ``floor_check(canonical_trigger, evidence) -> FloorResult`` (matches the AC 2-arg form; the registry
     is injected at factory time, NOT a positional arg). 4.3 builds the checker ONCE, calls per iteration.

  5. **Unknown-trigger → fail-closed (AD-12, anti-hallucination):** a ``canonical_trigger`` with NO
     registry entry → ``FloorResult(False, 0, 0, "fail-closed: unknown-trigger")``. NEVER fail-open.

  6. **Schema-validate-at-load = fail-fast (CI #4 part b):** ``load_floor_registry(specs, *, version=1)``
     is a PURE loader (NO file IO — the composition root / 4.3 reads the YAML). It VALIDATES every entry
     against the locked schema and raises ``FloorSchemaError`` on ANY violation — unknown op, field
     outside the ENUM, ``min_count`` missing/non-int/<1 (or bool), ``source_type`` missing/empty,
     matcher missing a required key, ``value`` non-str/empty, invalid regex, top-level not a mapping.
     NEVER silent.

  7. **Never raises at CHECK time (Constraint 5):** a malformed EVIDENCE item (missing/non-str field) →
     that item does NOT count; the checker still returns a FloorResult. (A malformed REGISTRY entry is
     different — that fails-fast at LOAD, not here.)

ONE-WAY (AD-1 / gate #2 HARD-FAIL): this module imports STDLIB ONLY (``re`` + ``dataclasses`` +
``typing`` + ``collections.abc`` + ``types``). NO ``models`` (operate over evidence DICTS, not
``Evidence`` objects — AD-9: state keeps dicts; Pydantic only at the port = 4.2). NO ``config`` import,
NO file IO (the loader takes already-parsed data; the composition root reads the YAML). Even more
layer-pure than ``graph/fuzzy_explore.py``. lint-imports: 1 contract kept / 0 broken.

CONTENT DEFERRED (D3 — do NOT invent): the actual ``{min_count, source_type, field, op, value}`` chosen
per ``canonical_trigger``; the confidence cutoff (D4); the registry version number + migration (mechanism
only — default 1). The default registry is EMPTY → every trigger fail-closed (the HONEST POC state;
real floor content calibrates via benchmark, D3). Mirrors 3.5's honest degenerate default.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

# ONE-WAY (AD-1 / gate #2): STDLIB ONLY. NO models / config / tools / graph back-edge / file IO.

# ---------------------------------------------------------------------------
# LOCKED ENUMs (AD-12 rule 4 — the predicate LANGUAGE; mechanism, not content)
# ---------------------------------------------------------------------------

#: Operator ENUM — the ONLY allowed matcher operators. NO semantic/LLM path.
OPERATORS: Final[frozenset[str]] = frozenset({"label-exact", "substring", "regex"})

#: Matcher target-field ENUM — the deterministic STRING fields of a §3.6 evidence dict.
MATCHER_FIELDS: Final[frozenset[str]] = frozenset({"source_name", "summary", "query"})

#: Default registry version (mechanism; specific number + migration DEFERRED).
DEFAULT_VERSION: Final[int] = 1

# Locked reason strings (deterministic human-readable FloorResult.reason).
_REASON_PASS: Final[str] = "pass"
_REASON_FAIL_CLOSED: Final[str] = "fail-closed: unknown-trigger"


# ---------------------------------------------------------------------------
# Schema-validation exception (load-time fail-fast — CI #4 part b)
# ---------------------------------------------------------------------------


class FloorSchemaError(ValueError):
    """Raised by ``load_floor_registry`` when a registry entry violates the locked schema.

    Fail-fast at LOAD (never silent) — the deterministic anti-hallucination backbone must reject a
    malformed floor rule before it can silently weaken a verdict. Subclasses ``ValueError`` so callers
    may catch either specifically or generically.
    """


# ---------------------------------------------------------------------------
# LOCKED data shapes (frozen — AD-12 determinism; FloorResult is the 4.1→4.3 seam)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FloorMatcher:
    """A single locked-language predicate: ``<op>(evidence[field], value)``.

    ``field`` ∈ :data:`MATCHER_FIELDS`, ``op`` ∈ :data:`OPERATORS`, ``value`` is a non-empty str. Frozen
    (AD-12 — a floor rule is immutable once validated). Mirrors the registry matcher shape
    ``{field, op, value}``.
    """

    field: str
    op: str
    value: str


@dataclass(frozen=True, slots=True)
class FloorSpec:
    """A floor rule for one ``canonical_trigger``: count threshold + source filter + matcher.

    SATISFIED for an evidence list when the count of items where
    ``(evidence["source_type"] == source_type) AND (<op>(evidence[field], value))`` is ``>= min_count``.
    Frozen (AD-12).
    """

    min_count: int
    source_type: str
    matcher: FloorMatcher


@dataclass(frozen=True, slots=True)
class FloorRegistry:
    """Immutable validated registry: ``canonical_trigger -> FloorSpec`` + a version tag (AD-12 rule 6).

    Built ONLY by :func:`load_floor_registry` (schema-validated) or the empty default. ``specs`` is a
    read-only :class:`types.MappingProxyType` so a registry cannot be mutated after load.
    """

    specs: Mapping[str, FloorSpec]
    version: int


@dataclass(frozen=True, slots=True)
class FloorResult:
    """Pure deterministic verdict of :func:`floor_check` for one (trigger, evidence) pair.

    The 4.1→4.3 carry-forward SEAM: the reflector (4.3) reads ``floor_pass`` to write
    ``state.sufficiency.floor_pass`` and route ``gather_more``; ``matched_count``/``min_count``/``reason``
    are deterministic audit detail. Frozen + documented — keep stable.
    """

    floor_pass: bool
    matched_count: int
    min_count: int
    reason: str


#: The checker signature — ``floor_check(canonical_trigger, evidence) -> FloorResult``. Registry injected
#: at factory time (:func:`build_floor_check`), NOT a positional arg (matches the AC 2-arg form).
FloorChecker = Callable[[str, Sequence[Mapping[str, object]]], FloorResult]


# ---------------------------------------------------------------------------
# §2.5 — registry loader + schema-validation-at-load (PURE, IO-free, fail-fast)
# ---------------------------------------------------------------------------


def _validate_version(version: object) -> int:
    """Validate the registry version is a positive int (mechanism; number DEFERRED). Reject bool."""
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise FloorSchemaError(f"registry version must be int >= 1, got {version!r}")
    return version


def _validate_matcher(raw: object) -> FloorMatcher:
    """Validate a matcher dict ``{field, op, value}`` against the locked ENUMs (fail-fast)."""
    if not isinstance(raw, Mapping):
        raise FloorSchemaError(
            f"matcher must be a mapping {{field, op, value}}, got {type(raw).__name__}"
        )
    # ``field`` / ``op`` membership in the frozenset also rejects missing/None/non-str (not in the set).
    field = raw.get("field")
    if field not in MATCHER_FIELDS:
        raise FloorSchemaError(
            f"matcher.field must be one of {sorted(MATCHER_FIELDS)}, got {field!r}"
        )
    op = raw.get("op")
    if op not in OPERATORS:
        raise FloorSchemaError(f"matcher.op must be one of {sorted(OPERATORS)}, got {op!r}")
    value = raw.get("value")
    if not isinstance(value, str) or not value:
        raise FloorSchemaError(f"matcher.value must be a non-empty str, got {value!r}")
    if op == "regex":
        # Fail-fast: an invalid regex MUST be rejected at LOAD, not crash floor_check at match time.
        try:
            re.compile(value)
        except re.error as exc:
            raise FloorSchemaError(f"matcher.value is an invalid regex {value!r}: {exc}") from exc
    return FloorMatcher(field=field, op=op, value=value)


def _validate_spec(raw: object) -> FloorSpec:
    """Validate one floor-spec dict against the locked schema (fail-fast)."""
    if not isinstance(raw, Mapping):
        raise FloorSchemaError(f"floor spec must be a mapping, got {type(raw).__name__}")
    min_count = raw.get("min_count")
    # Reject bool (bool is an int subclass — ``True`` must not silently count as ``min_count=1``).
    if isinstance(min_count, bool) or not isinstance(min_count, int) or min_count < 1:
        raise FloorSchemaError(f"min_count must be int >= 1, got {min_count!r}")
    source_type = raw.get("source_type")
    if not isinstance(source_type, str) or not source_type:
        raise FloorSchemaError(f"source_type must be a non-empty str, got {source_type!r}")
    matcher = _validate_matcher(raw.get("matcher"))
    return FloorSpec(min_count=min_count, source_type=source_type, matcher=matcher)


def load_floor_registry(
    specs: Mapping[str, object],
    *,
    version: int = DEFAULT_VERSION,
) -> FloorRegistry:
    """PURE loader: validate already-parsed registry data against the locked schema; return immutable.

    Takes the TOP-LEVEL mapping (keys = ``canonical_trigger``, values = floor-spec dicts) — NOT a file
    path. The composition root (4.3) reads ``config/floor_registry.yaml`` and passes the parsed mapping;
    this keeps :mod:`graph.floor_check` IO-free + layer-pure (NO ``config`` import, NO file IO).

    Fail-fast (CI #4 part b): every entry is validated; ANY schema violation raises
    :class:`FloorSchemaError`. NEVER silent. Returns an immutable :class:`FloorRegistry`
    (``MappingProxyType`` specs).

    Args:
        specs: already-parsed top-level mapping ``{canonical_trigger: {min_count, source_type, matcher}}``.
        version: registry version tag (default :data:`DEFAULT_VERSION`; mechanism only).

    Returns:
        an immutable, schema-validated :class:`FloorRegistry`.

    Raises:
        FloorSchemaError: if the top-level is not a mapping, a key is missing/empty/non-str, a spec or
            matcher violates the locked schema (see :func:`_validate_spec` / :func:`_validate_matcher`),
            or the version is invalid.
    """
    if not isinstance(specs, Mapping):
        raise FloorSchemaError(
            f"registry top-level must be a mapping (canonical_trigger -> floor spec), "
            f"got {type(specs).__name__}"
        )
    validated: dict[str, FloorSpec] = {}
    for trigger, raw_spec in specs.items():
        if not isinstance(trigger, str) or not trigger:
            raise FloorSchemaError(
                f"canonical_trigger key must be a non-empty str, got {trigger!r}"
            )
        # Defensive duplicate guard (a dict input cannot truly duplicate keys, but this documents the
        # intent + is robust if a caller ever builds the mapping from pairs).
        if trigger in validated:
            raise FloorSchemaError(f"duplicate canonical_trigger {trigger!r}")
        validated[trigger] = _validate_spec(raw_spec)
    return FloorRegistry(specs=MappingProxyType(validated), version=_validate_version(version))


# ---------------------------------------------------------------------------
# §2.4 — predicate matching + floor_check (pure deterministic; never raises)
# ---------------------------------------------------------------------------


def _match_one(evidence: Mapping[str, object], spec: FloorSpec) -> bool:
    """Does ONE evidence item satisfy the spec's (source_type AND matcher)? Defensive; never raises."""
    if evidence.get("source_type") != spec.source_type:
        return False
    field_value = evidence.get(spec.matcher.field)
    # Defensive: the matched field must be a str (a missing/non-str field does not count — Constraint 5).
    if not isinstance(field_value, str):
        return False
    op = spec.matcher.op
    value = spec.matcher.value
    if op == "label-exact":
        return field_value == value
    if op == "substring":
        return value in field_value
    # op == "regex" — value was compile-validated at LOAD, so re.search cannot raise re.error here.
    return re.search(value, field_value) is not None


def build_floor_check(*, registry: FloorRegistry) -> FloorChecker:
    """DI factory: build a ``floor_check`` checker closing over an injected :class:`FloorRegistry`.

    Returns a pure deterministic checker ``floor_check(canonical_trigger, evidence) -> FloorResult``
    (the registry is injected at factory time, NOT a positional arg — matches the AC 2-arg form). The
    reflector (4.3) builds the checker ONCE and calls it per iteration. NEVER raises (Constraint 5):
    unknown-trigger → fail-closed; malformed evidence item → does not count; non-str trigger /
    non-iterable evidence → fail-closed / empty (defensive).

    Args:
        registry: the validated :class:`FloorRegistry` (build via :func:`load_floor_registry`).

    Returns:
        a :data:`FloorChecker`.
    """

    def floor_check(
        canonical_trigger: str,
        evidence: Sequence[Mapping[str, object]],
    ) -> FloorResult:
        # Unknown-trigger → fail-closed (AD-12, anti-hallucination). A non-str trigger is "unknown".
        if not isinstance(canonical_trigger, str):
            return FloorResult(False, 0, 0, _REASON_FAIL_CLOSED)
        spec = registry.specs.get(canonical_trigger)
        if spec is None:
            return FloorResult(False, 0, 0, _REASON_FAIL_CLOSED)
        # Defensive: non-iterable / non-sequence evidence → no items to count (never raises).
        try:
            items: list[Mapping[str, object]] = [
                item for item in evidence if isinstance(item, Mapping)
            ]
        except TypeError:
            items = []
        matched_count = sum(1 for item in items if _match_one(item, spec))
        if matched_count >= spec.min_count:
            return FloorResult(True, matched_count, spec.min_count, _REASON_PASS)
        return FloorResult(
            False,
            matched_count,
            spec.min_count,
            f"fail: matched {matched_count} < min_count {spec.min_count}",
        )

    return floor_check


def build_default_floor_check() -> FloorChecker:
    """Composition-root default: an EMPTY registry → EVERY ``canonical_trigger`` fail-closed.

    This is the HONEST POC state (real floor content calibrates via benchmark, D3 — DEFERRED). An empty
    registry means no trigger has a floor spec → every check returns
    ``FloorResult(False, 0, 0, "fail-closed: unknown-trigger")``. Documented as degenerate — do NOT
    invent fake rules. Mirrors 3.5's honest degenerate default planner.
    """
    return build_floor_check(
        registry=FloorRegistry(specs=MappingProxyType({}), version=DEFAULT_VERSION)
    )


__all__ = [
    "DEFAULT_VERSION",
    "MATCHER_FIELDS",
    "OPERATORS",
    "FloorChecker",
    "FloorMatcher",
    "FloorRegistry",
    "FloorResult",
    "FloorSchemaError",
    "FloorSpec",
    "build_default_floor_check",
    "build_floor_check",
    "load_floor_registry",
]
