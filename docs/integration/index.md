# Integration Docs Bundle

**Project:** 26-rca-aiops  
**Status:** Current-runtime integration guide  
**Purpose:** Help another team onboard a target stack against the RCA runtime that exists today, without overclaiming breadth that is not yet validated.

## What this bundle is

This bundle is the practical path for target-stack onboarding and integrated acceptance.

Use it when you need to answer:
- what environment the RCA backend expects
- what the current runtime expects from alerts, metrics, logs, and evidence
- how supported trigger payloads map into the investigation contract
- whether a target stack is ready for an acceptance run
- which docs are policy versus procedure

## What this bundle is not

This bundle is **not**:
- a claim that the product is universal plug-and-play
- a future-state architecture spec
- a blanket certification for arbitrary target stacks
- a replacement for per-target integrated acceptance

## Truth model

Use these distinctions consistently:
- `docs/current-rca-runtime-truth-table.md` = canonical statement of **current runtime truth**
- this bundle = **how to onboard and operate against the currently supported runtime**
- `docs/architecture/*` = **future-shape or planning material**, not present-tense operator truth

## Read this bundle in order

1. `docs/integration/runtime-and-environment-requirements.md`  
   Real Kubernetes-backed environment requirements, runtime modes, env vars, and startup verification.

2. `docs/integration/environment-bootstrap-runbook.md`  
   Practical deployment order and command-level bootstrap flow across `demo`, `observability`, and `rca`.

3. `docs/integration/execution-checklist.md`  
   Step-by-step operator checklist for a live run and evidence capture.

4. `docs/integration/observability-contract.md`  
   Current assumptions around metrics, logs, traces, evidence, and floor rules.

5. `docs/integration/alert-payload-mapping.md`  
   Mapping from supported ingress payloads into the normalized investigation trigger shape.

6. `docs/integration/examples.md`  
   Safe-to-copy examples for payloads, evidence, and readiness interpretation.

7. `docs/integration/readiness-checklist.md`  
   Gate before calling a target stack ready for integrated acceptance.

8. `docs/integration/onboarding-checklist.md`  
   Per-target onboarding checklist and maturity gate.

9. `docs/integration/integration-standard.md`  
   Canonical onboarding contract and required integration domains.

10. `docs/integration/integrated-acceptance-runbook.md`  
    Per-target integrated RCA acceptance runbook.

11. `docs/integration/readiness-gap-assessment.md`  
    What still blocks broad integration-ready claims.

12. `docs/production-readiness-gap-assessment.md`  
    Production hardening verdict and remaining operational gaps.

13. `docs/operator-runbook.md`  
    Production deployment and operator handoff.

14. `docs/integration/handoff-and-maintenance.md`  
    Ongoing bootstrap / verify / troubleshoot / maintain guide.

15. `docs/integration/roadmap-and-metrics.md`  
    Backlog prioritization, acceptance metrics, MVP cut, and wave planning.

## Canonical docs this bundle operationalizes

These remain the primary policy or sign-off references:
- `docs/current-rca-runtime-truth-table.md`
- `docs/integration/integration-standard.md`
- `docs/integration/onboarding-checklist.md`
- `docs/integration/integrated-acceptance-runbook.md`
- `docs/integration/readiness-gap-assessment.md`
- `docs/production-readiness-gap-assessment.md`
- `docs/operator-runbook.md`
- `docs/PROJECT_SPECS.md`

Use this bundle for practical onboarding. Use the canonical docs for policy, scope boundaries, and sign-off context.

## Recommended operator flow

1. Read the runtime truth table to understand what is and is not proven.
2. Read `docs/integration/runtime-and-environment-requirements.md` to understand the required environment.
3. Use `docs/integration/environment-bootstrap-runbook.md` to stand up or verify the environment.
4. Confirm the target stack satisfies the observability contract.
5. Map the target's alert payloads into the supported ingestion contract.
6. Fill out the onboarding and readiness checklists honestly.
7. Run per-target integrated acceptance using `docs/integration/integrated-acceptance-runbook.md`.

## Scope guardrails

Use wording like:
- current ingestion path supports...
- current runtime uses...
- recommended onboarding fields...
- not yet broadly validated...

Avoid implying:
- broad trace-driven RCA validation
- broad planner/tool breadth beyond the proven path
- automatic certification for a new target stack
- that planning docs under `docs/architecture/` are present-tense operator truth
