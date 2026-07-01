# LLM Insertion Plan for RCA Runtime

## Purpose

This document defines a **practical path to introduce real LLM-powered reasoning** into the current RCA/AIOps runtime without breaking the validated parts of the system:

- read-only safety boundary
- deterministic contracts
- evidence-based reporting
- auditability
- onboarding/certification flow

It is intentionally incremental.

The goal is **not** to replace the whole system with free-form model behavior.
The goal is to add LLM capability only where it materially improves RCA quality.

---

## Current runtime baseline

The current runtime is best understood as:

- **workflow/orchestration:** real
- **read-only adapters/tooling:** real
- **UAT/backend contracts:** real
- **LLM reasoning path:** mostly not yet active by default

See also:

- `docs/current-rca-runtime-truth-table.md`
- `docs/aiops-integration-standard.md`
- `docs/aiops-integrated-acceptance-runbook.md`

---

## Design principle

## Keep the system hybrid

The target architecture should be:

> **deterministic control plane + LLM-assisted reasoning plane**

Meaning:

### Deterministic parts should stay deterministic
- trigger normalization
- read-only enforcement
- plan safety validation
- adapter dispatch
- checkpointing/resume
- evidence schema validation
- sign-off / audit fields

### LLM should be inserted only where reasoning quality matters
- hypothesis generation
- evidence summarization
- contradiction handling
- confidence refinement
- narrative RCA synthesis

This preserves the strongest parts of the current system while adding intelligence where rules alone are weak.

---

## Recommended insertion order

## Phase 1 — LLM hypothesis planner

### Why first
The current planner is rule-based and minimal. This is the most natural first place to gain value from an LLM.

### What the LLM should do
Input:
- normalized incident context
- service identity / topology context
- playbook hits
- evidence gathered so far

Output:
- ranked hypotheses
- evidence collection plan per hypothesis
- explicit uncertainty notes

### What must remain deterministic around it
- hypothesis output schema
- max hypothesis count
- stable, zero-padded, sequential hypothesis IDs
- downstream plan validation
- read-only enforcement

### Success criteria
- produces better hypotheses than current rule-based source
- does not bypass `plan_validator`
- preserves deterministic envelopes even if model content varies

### Recommended status
**First LLM insertion point. Highest priority.**

---

## Phase 2 — LLM evidence summarizer

### Why second
Even when evidence is collected correctly, raw logs/metrics/traces are hard to compress into operator-usable summaries.

### What the LLM should do
Input:
- tool raw output
- source type
- query metadata
- bounded excerpt/window

Output:
- concise evidence summary
- contradiction/support hints
- no free-form root-cause conclusion here

### What must remain deterministic around it
- evidence object schema
- `raw_excerpt` retention
- no evidence invention
- if summarization fails, fall back to deterministic summary

### Success criteria
- summaries become clearer for humans
- evidence remains citation-backed
- no synthetic facts appear that are absent from raw evidence

### Recommended status
**Second LLM insertion point. Medium-to-high priority.**

---

## Phase 3 — LLM confidence assessor / reflector enrichment

### Why third
Confidence is important, but it should not be the first live LLM dependency. The current reflector already has a strong deterministic fail-closed backbone.

### What the LLM should do
Input:
- normalized evidence set
- hypothesis set
- floor-check outcome
- contradiction/support structure

Output:
- refined confidence estimate
- evidence sufficiency judgment
- rationale for `write` vs `replan` vs `gather_more`

### What must remain deterministic around it
- floor check stays first and unoverrideable
- floor fail must still fail closed
- routing vocabulary stays locked
- bounded fallback if model fails

### Success criteria
- better discrimination between weak and strong evidence sets
- fewer false-positive RCA writes
- still never overrides deterministic floor fail

### Recommended status
**Third insertion point. Only after planner + summarizer are stable.**

---

## Phase 4 — LLM RCA narrative writer

### Why fourth, not first
The current RCA writer is safe because it is citation-constrained and deterministic. Replacing it too early would increase presentation quality but also increase hallucination risk.

### What the LLM should do
Input:
- evidence-backed root-cause candidates
- citations
- confidence verdict
- uncertainty/open questions

Output:
- concise operator-facing RCA narrative
- clearly cited reasoning
- explicit uncertainty section
- no remediation by default unless product scope changes

### What must remain deterministic around it
- only cited evidence can back claims
- no claim without `raw_excerpt`
- confidence authority remains the reflector output
- report envelope/schema remains fixed

### Success criteria
- report becomes easier to read and explain
- no uncited claim appears
- output remains audit-safe

### Recommended status
**Fourth insertion point. Nice-to-have after core reasoning works.**

---

## What should NOT become LLM-first

These areas should stay deterministic by default:

### Trigger normalization
Reason: schema and mapping correctness matter more than model flexibility.

### Plan validation
Reason: safety boundary must not depend on model judgment.

### Tool dispatch / executor routing
Reason: routing must stay constrained, inspectable, and read-only.

### Evidence object validation
Reason: schema validity is a contract problem, not a reasoning problem.

### Checkpointing / resume
Reason: durability is infrastructure logic, not reasoning logic.

### Final certification / acceptance status
Reason: sign-off is an evidence-governed process, not a model opinion.

---

## Runtime architecture target

## Target hybrid flow

1. deterministic trigger ingest
2. deterministic context assembly
3. LLM-assisted hypothesis generation
4. deterministic plan validation
5. deterministic read-only execution
6. deterministic evidence normalization with optional LLM summarization
7. deterministic floor check
8. optional LLM confidence refinement
9. deterministic or LLM-assisted cited RCA writing
10. deterministic report storage / audit trail

This preserves the current safety and audit posture while improving reasoning quality step by step.

---

## Model integration contract

Any real LLM insertion should follow these constraints.

## Input constraints
- bounded context windows
- pre-normalized structured input
- no raw unrestricted cluster dump
- no direct tool execution authority in the model layer

## Output constraints
- strict schema
- bounded list sizes
- explicit uncertainty field
- no hidden control words outside approved routing/output vocabularies

## Failure behavior
- timeout -> deterministic fallback
- malformed output -> retry once or fallback
- provider unavailable -> fallback, never break investigation lifecycle

## Audit requirements
- record which node used model reasoning
- record model/provider/version when applicable
- preserve the raw evidence used for the decision
- preserve fallback/degradation path when model output is discarded

---

## Recommended implementation strategy

## Step 1 — Add one LLM seam for hypothesis generation only

Do this first because it yields the highest gain with the lowest safety risk.

Implementation target:
- replace the default planner source only in an opt-in runtime profile
- keep rule-based planner as fallback
- compare outputs in side-by-side evaluation mode before making it default

## Step 2 — Add LLM summarization behind deterministic evidence objects

Do this second so humans get better evidence readability while the evidence contract stays stable.

## Step 3 — Add confidence/reflection enrichment

Only after integrated acceptance runs show that the planner + summarizer path reliably improves real incidents.

## Step 4 — Upgrade RCA report generation if needed

Do this last. It is presentation value, not the highest-leverage reasoning fix.

---

## Rollout profiles

## Profile A — deterministic baseline
Use for:
- CI
- contract tests
- offline reproducibility
- safety benchmarking

## Profile B — assisted reasoning
Use for:
- staging
- shadow evaluations
- side-by-side incident comparisons

LLM inserted at:
- planner
- summarizer

## Profile C — production candidate
Use for:
- controlled live incidents
- integrated RCA acceptance
- operator trials

LLM inserted at:
- planner
- summarizer
- optional reflector
- optional writer

The product should be able to state which profile is active for a given target stack.

---

## Evaluation plan

A node should only graduate from deterministic-only to LLM-enabled default after passing all 3 layers below.

## Layer 1 — offline eval
- benchmark scenarios
- regression against current deterministic baseline
- no schema break
- no safety break

## Layer 2 — shadow run
- same incident processed by deterministic and LLM-assisted modes
- compare hypothesis quality, evidence quality, report usefulness
- operator review required

## Layer 3 — integrated acceptance
- real or staging target stack
- fault -> trigger -> evidence -> RCA report
- certify only if the LLM-assisted path improves or at least does not degrade incident handling

---

## Recommended first milestone

If only one LLM milestone is funded next, it should be:

## **LLM-backed hypothesis planner with deterministic fallback**

Use `docs/llm-hypothesis-planner-runtime-profile.md` as the narrow runtime contract for this first seam.

Why:
- highest reasoning upside
- lowest safety risk
- easiest to keep inside strict contracts
- addresses the current weak point most directly

---

## Product messaging guidance

Safe message:

> The RCA platform is designed as a hybrid system: deterministic control and evidence safety, with selective LLM reasoning inserted where it materially improves hypothesis generation and evidence interpretation.

Unsafe message:

> The current system is already a fully LLM-driven RCA agent.

That second statement is not supported by current runtime reality.

---

## Bottom line

The correct path is **not** to “LLM-ify everything.”
The correct path is:

1. keep deterministic safety/control contracts
2. add LLM first to **hypothesis planning**
3. then to **evidence summarization**
4. then optionally to **confidence refinement**
5. only later to **final narrative writing**

This gives the product a credible path from today’s deterministic POC to a real LLM-powered RCA system without losing safety, auditability, or onboarding discipline.

---

## Unresolved questions

1. Which provider/model family will be used first for hypothesis planning?
2. Will the first LLM path be staging-only, or available behind a runtime flag in all environments?
3. Should the deterministic planner remain permanently available as a fallback, or only during transition?
4. What is the minimum acceptance threshold for saying the LLM planner is better than the current rule-based baseline?
