# LLM Hypothesis Planner Runtime Profile — RCA AI Agent POC

**Project:** 26-rca-aiops  
**Status:** Phase-1 runtime contract / scope guard  
**Purpose:** Define the narrow, env-gated planner seam for an LLM-backed hypothesis planner with deterministic fallback.

## 1. Intent

This profile describes only the first LLM insertion point:

- the hypothesis planner
- behind an explicit runtime gate
- with the deterministic planner preserved as fallback

It exists to prevent scope creep. This is **not** a full LLM conversion of the RCA runtime.

## 2. In-scope behavior

When the Phase 1 profile is enabled, the planner may use an LLM to propose or rank hypotheses from:

- normalized incident context
- service identity / topology context
- playbook hints
- evidence gathered so far

The planner output must remain inside the existing planner contract:

- bounded hypothesis list
- deterministic envelope shape
- stable hypothesis IDs
- downstream plan validation unchanged
- read-only enforcement unchanged

## 3. Runtime gate

The LLM planner must be opt-in and explicitly gated by runtime configuration.

Recommended gate semantics:

- disabled by default
- requires a configured provider/model family
- provider binding stays deployment-specific; the seam can be wired to Anthropic or OpenAI depending on environment
- OpenAI-compatible deployments may also provide a custom API base URL and model alias through environment configuration
- falls back to the deterministic source if the provider is unavailable, times out, or returns malformed output

If the gate is not enabled, the current deterministic planner remains the runtime path.

## 4. Deterministic fallback rules

Fallback must preserve current behavior:

- no exception should escape into the graph
- no new control flow should bypass `plan_validator`
- no write / remediation authority should be introduced
- no new nondeterministic state should become mandatory for the planner to run

Fallback conditions include:

- missing provider configuration
- provider timeout
- provider error
- schema mismatch
- empty or unusable model output

## 5. Explicit non-goals

This profile does **not** include:

- evidence summarization
- reflector / confidence model changes
- RCA narrative writer changes
- tool dispatch changes
- checkpointing changes
- integration acceptance changes
- replacing every deterministic node with an LLM-backed equivalent

## 6. Acceptance criteria for the Phase 1 seam

The Phase 1 planner seam is acceptable only if all of the following remain true:

- the system can run with the deterministic planner alone
- the LLM path is opt-in and environment-gated
- the fallback path is deterministic and safe
- planner output still satisfies the existing schema
- plan validation and read-only boundaries are unchanged
- overclaiming is avoided in runtime and docs
- provider-specific support is only described as live when it has been separately validated

## 7. References

- `docs/architecture/llm-insertion-plan-for-rca-runtime.md`
- `docs/current-rca-runtime-truth-table.md`
- `graph/nodes/hypothesis_planner.py`
- `graph/compiled.py`
