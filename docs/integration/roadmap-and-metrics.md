# RCA Roadmap and Impact Map

**Project:** 26-rca-aiops  
**Status:** Product handoff artifact, aligned to the verified Phase 3 baseline  
**Purpose:** Convert the brainstormed FR/story map into a backlog-prioritization view that an engineering lead or product owner can use without reading implementation detail.

## 1. Source of truth

This roadmap is anchored to:
- `docs/current-rca-runtime-truth-table.md`
- `docs/llm-insertion-plan-for-rca-runtime.md`
- `docs/aiops-integrated-acceptance-runbook.md`
- `docs/integration/index.md`
- `docs/production-readiness-gap-assessment.md`
- `docs/operator-runbook.md`

The PRD/story map is the implementation decomposition. This document collapses that detail into five product epics and three delivery waves.

## 2. Five product epics

### Epic 1 - Intake, runtime mode, and incident grouping

Why it matters:
- Gets the right incident into the system and prevents operators from mistaking minimal mode for full RCA mode.

Acceptance metrics:
- Supported trigger POST returns `202` with `investigation_id`
- Runtime mode is explicit at startup: minimal or durable/full-graph
- Trigger payload validation rejects malformed input without ambiguity
- One incident can be tracked deterministically across retries or grouped by the chosen contract

Risk if omitted:
- The system may appear healthy while producing a reduced investigation path.
- Operators will spend time debugging payloads instead of diagnosing incidents.

MVP cut:
- One supported trigger path, explicit runtime-mode logging, deterministic grouping contract, no ambiguous success state.

Later cuts:
- Broader trigger-source coverage
- Smarter grouping for flap/retry scenarios

### Epic 2 - Read-only evidence layer

Why it matters:
- Determines whether the RCA output is grounded in actual observability data rather than inference alone.

Acceptance metrics:
- Evidence is collected read-only only
- Prometheus, logs, and K8s/runtime evidence are queryable for the incident window
- Evidence objects preserve `raw_excerpt` and source metadata
- Evidence retrieval is stable enough to repeat during an incident review

Risk if omitted:
- The platform can explain a fault only abstractly, not with audit-grade proof.
- The strongest operator trust signal, `raw_excerpt`-backed evidence, will be missing.

MVP cut:
- One reliable read-only source path per evidence type needed for the seeded RCA flow.

Later cuts:
- More evidence sources
- Better cross-source correlation and log/trace enrichment

### Epic 3 - Hypothesis and sufficiency engine

Why it matters:
- Converts evidence into ranked investigation paths and decides when the system has enough signal to write.

Acceptance metrics:
- Hypotheses are ranked and bounded
- Floor/sufficiency checks fail closed
- The planner seam improves or matches the deterministic baseline on the seeded path
- Confidence output is calibrated against actual correctness, not just generated

Risk if omitted:
- The system can collect evidence but still fail to converge on a defensible conclusion.
- Confidence becomes presentation text instead of a quality signal.

MVP cut:
- Deterministic fallback plus one LLM planner seam with strict fallback behavior.

Later cuts:
- LLM-backed confidence refinement
- Better contradiction handling and evidence sufficiency heuristics

### Epic 4 - RCA report and operator review

Why it matters:
- This is the product surface the on-call user actually reads.

Acceptance metrics:
- Report contains non-empty root-cause candidates
- Report cites real evidence, including `raw_excerpt`
- Report includes open questions and caveats
- Read-store retrieval by `investigation_id` is reliable

Risk if omitted:
- Even a successful investigation is hard to trust, explain, or hand off.

MVP cut:
- Concise report with grounded citations and no remediation by default.

Later cuts:
- Better narrative synthesis
- Better operator-facing formatting and follow-up guidance

### Epic 5 - Evaluation, onboarding, and production hardening

Why it matters:
- Turns a working demo path into something other teams can adopt and maintain.

Acceptance metrics:
- Onboarding checklist is complete enough for a target stack to enter acceptance
- Integrated acceptance passes on more than one scenario/service shape
- Production-readiness gaps are tracked and explicitly assigned
- Deployment uses production-safe secrets, storage, and probes where required

Risk if omitted:
- The team will repeatedly re-discover the same setup, security, and validation issues.
- The product will stay demo-shaped even after the core workflow is solid.

MVP cut:
- A single repeatable acceptance path, plus a clear operator checklist and explicit production-safe vs demo-only split.

Later cuts:
- Broader scenario matrix
- Repeatability and soak testing
- Production-grade secret/storage/network hardening

## 3. Wave roadmap

### Wave 1 - Ship the verified baseline

Goal:
- Make the seeded, grounded RCA path repeatable and operator-safe on the current cluster setup.

Includes:
- Epic 1 minimum
- Epic 2 minimum
- Epic 3 minimum
- Epic 4 minimum

Exit criteria:
- A supported alert reaches `202` and investigation ID
- The investigation reaches a grounded report with evidence citations
- The operator can tell whether the runtime is minimal or durable/full-graph
- The runbook is enough for another operator to repeat the path without tribal knowledge

### Wave 2 - Expand breadth and evaluation

Goal:
- Prove the system is not one-demo-path specific.

Includes:
- Epic 3 later cuts
- Epic 4 later cuts
- Epic 5 evaluation and onboarding breadth

Exit criteria:
- Multiple incident classes pass acceptance
- Multiple service shapes pass acceptance
- Calibration and anti-hallucination measures are tracked against real runs

### Wave 3 - Production readiness

Goal:
- Make the system safe to operate outside the demo baseline.

Includes:
- Epic 5 production hardening
- The production-safe portions of Epics 1-4

Exit criteria:
- Secrets, storage, probes, and access boundaries are production-safe
- Production-readiness verdict is “ready with conditions” or better for the target environment
- Operators have a clear maintenance and rollback posture

## 4. MVP cut vs later cuts

### MVP cut

Deliver the smallest credible end-to-end release:
- one verified alert path
- one grounded RCA report
- explicit runtime-mode visibility
- read-only evidence
- operator runbook coverage

This is the release that answers: “Can another operator run the flow and trust the result?”

### Later cuts

Delay until after the MVP proves stable:
- broad incident matrix
- extra service topologies
- richer LLM-assisted confidence and narrative
- production-grade storage, secrets, and network policy
- multi-tenant or multi-environment concerns

This is the release that answers: “Can we generalize the flow and operate it safely over time?”

## 5. Suggested first-wave wording

Use this wording for handoff or backlog kickoff:

> Wave 1 ships the verified RCA baseline: a repeatable, read-only, evidence-backed investigation flow that accepts supported alerts, makes runtime mode explicit, and returns grounded RCA reports with citations. The goal is not broader automation yet; it is a dependable operator experience on the proven path.

## 6. Handoff summary

If you only keep one thing from this roadmap:

- Wave 1 is about repeatability and trust on the proven path.
- Wave 2 is about breadth and quality measurement.
- Wave 3 is about production safety and maintainability.

That order matters because it keeps the team from turning a working RCA path into an overbuilt but unproven platform.
