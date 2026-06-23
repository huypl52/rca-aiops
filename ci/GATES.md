# CI Invariant Gates (AD-13)

Reference for the 6 architectural-invariant gates. Every architecture decision
(AD-1..AD-12) maps to ≥1 CI guard (AD-13). Gates are HARD-FAIL: a violation
blocks merge, no opt-out, no `continue-on-error`.

| # | Gate | AD | Status (Story 0.1) | Filled by | Bind |
| --- | --- | --- | --- | --- | --- |
| 1 | Read-only registry (no write/exec/patch/...) | AD-3 (BLOCKER) | **SKELETON WIRED** ✓ | Story 2.1 (real registry) | `ci/gate1_readonly_registry.py` |
| 2 | Dependency-direction one-way (no back-edge/circular) | AD-1, AD-2 | **WIRED** ✓ | — (living contract) | `uv run lint-imports` |
| 3 | Type-coherence 2-tier round-trip | AD-9 | placeholder | **Story 0.3** | `pytest` (InvestigationState ⊆ Pydantic + round-trip) |
| 4 | Floor determinism (pure-function + registry schema) | AD-12 | placeholder | **Epic 4** | `pytest` (floor_check) |
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

## Gates #3, #4, #6 — placeholders (Story 0.1)

Remaining placeholder steps in `.github/workflows/ci.yml` with `TODO(<epic>)` trace.
Each is filled when the corresponding artifact exists. They are NOT silently passing
gates — each prints its pending definition so reviewers see the gap.
