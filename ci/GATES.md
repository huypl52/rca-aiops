# CI Invariant Gates (AD-13)

Reference for the 6 architectural-invariant gates. Every architecture decision
(AD-1..AD-12) maps to ≥1 CI guard (AD-13). Gates are HARD-FAIL: a violation
blocks merge, no opt-out, no `continue-on-error`.

| # | Gate | AD | Status (Story 0.1) | Filled by | Bind |
| --- | --- | --- | --- | --- | --- |
| 1 | Read-only registry (no write/exec/patch/...) | AD-3 (BLOCKER) | **SKELETON WIRED** ✓ | Story 2.1 (real registry) | `ci/gate1_readonly_registry.py` |
| 2 | Dependency-direction one-way (no back-edge/circular) | AD-1, AD-2 | **WIRED** ✓ | — (living contract) | `uv run lint-imports` |
| 3 | Type-coherence 2-tier round-trip | AD-9 | **WIRED** ✓ | Story 0.3 | `pytest tests/ci/test_gate3_type_coherence.py` |
| 4 | Floor determinism (pure-function + registry schema) | AD-12, DEC-3 | **WIRED** ✓ | Story 4.1 (mechanism) | `pytest tests/ci/test_gate4_floor_determinism.py` |
| 5 | Contract schema preservation (18/9-field no drift) | AD-6 | **WIRED** ✓ | Story 0.2 | `pytest tests/ci/test_gate5_contract_schema.py` |
| 6 | Benchmark determinism (11-scenario + calibration) | FR-10, AD-13 #6 | placeholder | **Epic 6** | `eval/` harness |

## Gate #1 — read-only registry (AD-3 BLOCKER)

Tool/adapter MUST NOT expose `write/exec/patch/delete/scale/rollback/restart/remediate`.
`kubectl debug/exec/patch` MUST NOT exist in the registry. Enforced at code/registry
level, NOT via LLM (AD-3, FR-5).

- **Deny-set:** `ci/denyset.py` — `WRITE_VERBS` (8 verbs) + `WRITE_PATTERNS` (5 regexes). Single source of truth (imported by gate #1 + Story 2.1 registry).
- **Scanner:** `ci/gate1_readonly_registry.py` — AST walk (def/async-def/attribute/class name ∈ WRITE_VERBS) + regex scan (WRITE_PATTERNS) over `adapters/` + `tools/`.
- **Negative test:** `tests/ci/test_gate1_readonly.py` — injects forbidden verbs/patterns → gate exit 1.

Spec §3.8 ground truth (7 forbidden): restart · rollback · scale · delete · patch · exec · remediation. The 8-verb set covers all 7 + catch-all `write`.

## Gate #2 — dependency-direction (AD-1 / AD-2)

One-way chain `routers → services → graph → adapters → tools`. No back-edge
(adapter↛graph, adapter↛services, tools↛graph, tools↛services, graph↛routers),
no circular import.

- **Contract:** `[tool.importlinter]` `layers` in `pyproject.toml`.
- **Bind:** `uv run lint-imports` (exit 1 on BROKEN).
- **Negative test:** `tests/ci/test_gate2_deps.py` — injects `adapters → graph` back-edge → contract BROKEN.

## Gate #5 — contract schema preservation (AD-13 #5 / AD-6)

The Pydantic contract models MUST NOT drift from spec §3.4 (IncidentTrigger =
18 fields) / §3.6 (Evidence = 9 fields). Any add / rename / remove → gate FAIL.

- **Source-of-truth field-set:** `ci/contract_schema.py` — `SPEC_INCIDENT_TRIGGER_FIELDS`
  (18, table order, row 18 = `raw_payload_ref`) + `SPEC_EVIDENCE_FIELDS` (9) + tier
  tuples + enum domains. Spec-derived, NOT derived from the models (a gate that
  derives its expected-set from the model is tautological).
- **Bind:** `uv run pytest tests/ci/test_gate5_contract_schema.py -v` (HARD-FAIL).
- **Positive:** asserts `IncidentTrigger` field-set == 18 §3.4 + `incident_id`, Evidence
  == 9 §3.6, tier correctness (required non-null / optional-nullable None / derived
  `[]`), `timestamp_range {start,end}`, enum domains.
- **Negative (FAIL-on-drift):** `tests/ci/test_gate5_contract_schema.py` — injects an
  invented field via `pydantic.create_model` (add), drops a field (remove), renames
  (drop+add) → assertion `AssertionError` each time (drift caught).

## Gate #3 — type-coherence 2-tier round-trip (AD-13 #3 / AD-9)

The `InvestigationState` TypedDict (graph layer) must stay type-coherent with the
Pydantic port contract. Two assertions, BOTH must pass to merge (HARD-FAIL).

- **Bind:** `uv run pytest tests/ci/test_gate3_type_coherence.py -v`.
- **(a) Shape (2-tier AD-9):** nested `state.trigger` keys ⊆ IncidentTrigger port
  field-set (18 §3.4 + `incident_id`) AND every `state.evidence` item keys ⊆ Evidence
  port field-set (9 §3.6). Source-of-truth = `ci.contract_schema` (spec-derived, NOT
  derived from the TypedDict — avoids a tautological drift gate, same lesson as gate #5).
- **(b) Round-trip:** sample `InvestigationState` → `JsonPlusSerializer.dumps_typed` →
  `loads_typed` → `assert ==` (deep equality). AD-9 "serializer = LangGraph built-in,
  NO custom serializer". Covers list-dedupe, scalar replace, hypothesis upsert,
  nested dict/list/None/scalars.
- **JSON-safe invariant (AD-9 rule 1 "plain JSON-safe dicts"):** stdlib `json.dumps(state)`
  must succeed — NOT JsonPlusSerializer (which, being msgpack+extensions, round-trips
  `datetime`/`set` and would NOT trip on them). `json.dumps` is the guard that rejects the
  non-JSON-safe values we actually care about (`datetime`/`set`/custom objects). (Caveat:
  `json.dumps` does NOT reject >64-bit ints, which JsonPlusSerializer *does* — so the two
  are not a strict superset relation; for the AD-9 invariant the `datetime`/`set` axis is
  the operative one, and `json.dumps` enforces it.)
- **Negative (FAIL proven):** inject `datetime`/`set` → `json.dumps` raises `TypeError`;
  inject shape-drift (trigger/evidence key outside port contract) → (a) raises
  `AssertionError`; `schema_version` mismatch → `assert_schema_version` raises `ValueError`.
- **13-key spine:** gate also asserts `InvestigationState.__annotations__` == exactly the
  13 AD-9 top-level keys (no invented/missing key).

## Gate #4 — Floor determinism (AD-13 #4 / AD-12 / DEC-3)

The sufficiency rule-floor (the deterministic anti-hallucination backbone the LLM ceiling in 4.3 /
AD-7 CANNOT override — DEC-3 "LLM không override sàn") MUST be a provably PURE function, and its
declarative registry MUST fail-fast on a malformed schema. Both must hold to merge (HARD-FAIL).

- **Source-of-truth mechanism:** `graph/floor_check.py` — STDLIB-ONLY pure module (NO models / config /
  tools / graph back-edge / file IO). Predicate LANGUAGE locked: operator ENUM `{label-exact, substring,
  regex}`; matcher field ENUM `{source_name, summary, query}`; floor spec `{min_count>=1, source_type,
  matcher}`; `FloorResult{floor_pass, matched_count, min_count, reason}` frozen. `load_floor_registry`
  schema-validates-at-load (fail-fast `FloorSchemaError`); unknown-trigger → fail-closed (NEVER fail-open).
- **Registry data:** `config/floor_registry.yaml` — LOCKED DATA LOCATION. POC default EMPTY (D3 content
  DEFERRED — every trigger fail-closed; honest degenerate state, no invented rules). Loaded by the
  composition root (reflector 4.3) via `yaml.safe_load` → `load_floor_registry`.
- **Bind:** `uv run pytest tests/ci/test_gate4_floor_determinism.py -v` (HARD-FAIL).
- **(a) Pure-function determinism (AD-12):** same `(canonical_trigger, evidence)` → byte-identical
  `FloorResult` across repeated calls; order-independent count; **PYTHONHASHSEED-safe** (proven across
  fresh interpreter processes with DIFFERENT hash seeds → identical serialized verdict); AST: ZERO
  forbidden nondeterminism sources (no random/time/datetime/uuid imported).
- **(b) Registry schema-validate-at-load (fail-fast):** `load_floor_registry` RAISES `FloorSchemaError`
  for EVERY §2.5 violation kind (unknown op, field outside ENUM, min_count missing/<1/non-int/bool,
  source_type missing/empty, matcher missing key / not-a-mapping / value empty-or-non-str / invalid
  regex, top-level not-a-mapping, key non-str/empty, bad version); AND the SHIPPED `floor_registry.yaml`
  loads cleanly through the loader (a malformed YAML is a silent production regression caught at gate
  time, never in a verdict).
- **Negative (FAIL proven):** inject each violation kind → `FloorSchemaError` at LOAD (parametrized);
  a non-deterministic verdict under PYTHONHASHSEED → assertion divergence.

## Gate #6 — placeholder (Epic 6)

Remaining placeholder step in `.github/workflows/ci.yml` with `TODO(Epic 6)` trace.
Filled when the `eval/` 11-scenario benchmark harness exists. NOT a silently passing
gate — it prints its pending definition so reviewers see the gap.
