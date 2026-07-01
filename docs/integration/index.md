# Integration Docs Bundle

**Project:** 26-rca-aiops  
**Status:** Current-runtime integration guide  
**Purpose:** Help another team onboard a target stack against the RCA runtime that exists today, without overclaiming breadth that is not yet validated.

## What this bundle is

This bundle is a practical companion to the repo's existing integration and acceptance docs.

Use it when you need to answer:
- what real environment the current RCA runtime expects around the backend
- what the current runtime actually expects from alerts, metrics, logs, and evidence
- how incoming triggers map into the investigation contract
- whether a target stack is ready for an acceptance run
- what examples are safe to copy or adapt today

## What this bundle is not

This bundle is **not**:
- a claim that the product is universal plug-and-play
- a future-state architecture spec
- a blanket certification for arbitrary target stacks
- a replacement for per-target integrated acceptance

The verified proof currently established (Phase 2, 2026-07-01):
- seeded incident class: `DependencyTimeout`
- validated service: `order-service`
- runtime path: durable / full compiled graph
- planner path: provider-backed OpenAI-compatible seam — **live-exercised** (LLM-generated hypothesis plans confirmed in E2E output)
- alert ingestion: Alertmanager webhook + direct POST both return `202`
- observability stack: all 6 components ready (Prometheus, Alertmanager, Loki, Alloy, Grafana, event-watcher)
- final outcome: grounded RCA output with non-empty `root_cause`, non-empty `evidence_backing`, and real `raw_excerpt` citations on the demo stack

What is still not proven:
- broader incident-class coverage beyond `DependencyTimeout`
- broader service coverage beyond `order-service`
- repeatability across many consecutive runs
- production-grade security, tenancy, and self-observability controls

See:
- `docs/current-rca-runtime-truth-table.md`
- `docs/uat/integrated-rca-acceptance-run.md`
- `docs/integration-readiness-gap-assessment.md`
- `docs/production-readiness-gap-assessment.md`
- `docs/operator-runbook.md`
- `plans/reports/integration-run-phase2-2026-07-01.md`

## Read this bundle in order

1. `docs/integration/runtime-and-environment-requirements.md`  
   Start here if you need a real Kubernetes-backed environment around the RCA backend and want to understand runtime modes, env vars, namespaces, and startup verification.

2. `docs/integration/environment-bootstrap-runbook.md`  
   Use this for the practical deployment order and command-level bootstrap flow across `demo`, `observability`, and `rca`.

3. `docs/integration/execution-checklist.md`  
   Use this as the step-by-step operator checklist for the live run and evidence capture.

4. `docs/integration/observability-contract.md`  
   Use this for the current runtime assumptions around metrics, logs, traces, evidence, and floor rules.

5. `docs/integration/alert-payload-mapping.md`  
   Use this to map supported ingress payloads into the normalized investigation trigger shape.

6. `docs/integration/examples.md`  
   Use the examples to see what a valid payload, evidence item, and checklist outcome look like.

7. `docs/integration/readiness-checklist.md`  
   Use this as the gate before calling a target stack ready for integrated acceptance.

8. `docs/production-readiness-gap-assessment.md`  
   Use this for the canonical production readiness verdict and gap assessment.

9. `docs/operator-runbook.md`  
   Use this for the canonical operator handoff and production deployment runbook.

10. `docs/integration/handoff-and-maintenance.md`  
   Use this as the operator/maintainer onboarding guide: how to bootstrap, verify, troubleshoot, and maintain the RCA system.

11. `docs/integration/roadmap-and-metrics.md`  
   Use this for backlog prioritization: five product epics, acceptance metrics, MVP cut, and wave planning.

## Reference map

### Integration bundle
- `docs/integration/runtime-and-environment-requirements.md` — môi trường thật cần gì, runtime modes nào, env vars nào quan trọng
- `docs/integration/environment-bootstrap-runbook.md` — thứ tự dựng `demo` / `observability` / `rca`, command-level bootstrap flow
- `docs/integration/observability-contract.md` — contract hiện tại cho metrics / logs / traces / evidence / floor rules
- `docs/integration/alert-payload-mapping.md` — map payload từ ingress sources vào normalized trigger shape
- `docs/integration/examples.md` — ví dụ practical cho alert, trigger, evidence, readiness interpretation
- `docs/integration/readiness-checklist.md` — checklist PASS / PARTIAL / FAIL / N/A trước khi gọi target stack là ready
- `docs/production-readiness-gap-assessment.md` — canonical production readiness verdict and hardening gaps
- `docs/operator-runbook.md` — canonical operator handoff and deployment runbook
- `docs/integration/handoff-and-maintenance.md` — operator/maintainer onboarding, bootstrap, verify, troubleshoot, maintain
- `docs/integration/roadmap-and-metrics.md` — five epic impact map, acceptance metrics, MVP cut, wave plan

### Canonical docs this bundle operationalizes
These remain the primary source documents:
- `docs/aiops-integration-standard.md`
- `docs/aiops-onboarding-checklist.md`
- `docs/aiops-integrated-acceptance-runbook.md`
- `docs/current-rca-runtime-truth-table.md`
- `docs/integration-readiness-gap-assessment.md`
- `docs/PROJECT_SPECS.md`
- `docs/uat/integrated-rca-acceptance-run.md`

Use the bundle for practical onboarding. Use the canonical docs for policy, scope boundaries, and sign-off context.

## Goal to pass the current integration blockers

The working goal is:

> Dựng môi trường Kubernetes thật (`demo` + `observability` + `rca`) để tích hợp RCA agents end-to-end, hoàn thiện bộ docs `docs/integration/` và xác minh flow `alert → investigation → grounded RCA report`.

A target should only be treated as having passed the current blocker set when **all** of these are true:

1. **Environment is real and runnable**
   - `demo`, `observability`, and `rca` layers are deployed
   - `docker`, `kubectl`, and `kind` (or equivalent cluster tooling) are available on the execution host
   - the backend service is reachable and correctly wired to the trigger sources

2. **Runtime mode is correct**
   - the team knows whether the backend is in minimal mode or durable/full-graph mode
   - if grounded RCA is the goal, the richer RCA path is intentionally enabled rather than assumed
   - planner/provider mode is explicit when the LLM seam is needed

3. **Observability contract is satisfied**
   - alert sources are wired
   - service and namespace identity are stable
   - metrics/logs/evidence are queryable in a deterministic incident window
   - read-only evidence access is preserved

4. **Target-stack readiness is explicitly checked**
   - the readiness checklist is filled out honestly
   - floor-rule gaps are known
   - the team distinguishes PASS / PARTIAL / FAIL instead of assuming integration readiness

5. **End-to-end RCA is proven, not assumed**
   - a supported alert enters via the documented ingest path
   - investigation is created and can be polled by `investigation_id`
   - the flow reaches a defensible terminal result
   - the final RCA report is grounded, with non-empty evidence-backed output on the validated path

6. **Docs are complete enough for handoff**
   - another team can read `docs/integration/` in order and understand:
     - what environment to prepare
     - how to bootstrap it
     - what payloads/contracts are expected
     - how to decide whether the target is actually ready

## Recommended operator flow

1. Read the runtime truth table to understand what is and is not proven.
2. Read `docs/integration/runtime-and-environment-requirements.md` to understand the real environment required.
3. Use `docs/integration/environment-bootstrap-runbook.md` to stand up or verify the environment.
4. Confirm the target stack satisfies the observability contract.
5. Map the target's alert payloads into the supported ingestion contract.
6. Fill out the readiness checklist.
7. Run per-target integrated acceptance using `docs/aiops-integrated-acceptance-runbook.md`.

## Scope guardrails

Use wording like:
- current ingestion path supports...
- current runtime uses...
- recommended onboarding fields...
- not yet broadly validated...

Avoid implying:
- broad trace-driven RCA validation
- broad planner/tool breadth beyond the proven path
- floor registry coverage beyond the checked-in seeded rule set
- automatic certification for a new target stack
