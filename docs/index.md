# Docs Index

This index is the entry point for the repo docs tree.

## Start here

Choose the shortest path for your job:

- **What is true right now?** → `docs/current-rca-runtime-truth-table.md`
- **How do I deploy or operate the backend?** → `docs/operator-runbook.md`
- **How do I onboard or evaluate a target stack?** → `docs/integration/index.md`
- **How do I rerun the validated demo?** → `docs/demo/index.md`
- **Where are planning and future-shape docs?** → `docs/architecture/index.md`
- **What is the original foundation/spec?** → `docs/PROJECT_SPECS.md`

## Navigation map

### Core current-state docs
- `docs/current-rca-runtime-truth-table.md` — canonical runtime truth; use this to avoid overclaiming
- `docs/operator-runbook.md` — production deployment and operator workflow
- `docs/production-readiness-gap-assessment.md` — production hardening verdict and remaining gaps
- `docs/PROJECT_SPECS.md` — foundational spec and original architecture context

### Integration docs
- `docs/integration/index.md` — curated integration bundle and reading order
- `docs/integration/integration-standard.md` — canonical onboarding/integration contract
- `docs/integration/onboarding-checklist.md` — per-target onboarding checklist
- `docs/integration/integrated-acceptance-runbook.md` — per-target integrated acceptance run
- `docs/integration/readiness-gap-assessment.md` — what still blocks broad integration-ready claims

### Demo docs
- `docs/demo/index.md` — demo landing page and role map
- `docs/demo/guide.md` — canonical validated demo truth, run order, GO / NO-GO, fallback policy
- `docs/demo/operator-cheatsheet.md` — command-first quick reference
- `docs/demo/presenter-script.md` — talk track and branch handling only
- `docs/demo/report-template.md` — reusable evidence/verdict template
- `docs/demo/ui-direction.md` — product/UI direction for the incident console

### Architecture and planning docs
- `docs/architecture/index.md` — planning/reference landing page
- `docs/architecture/llm-insertion-plan-for-rca-runtime.md` — LLM insertion target shape
- `docs/architecture/llm-hypothesis-planner-runtime-profile.md` — planner/runtime profile detail

## Reorganization notes

This cleanup is **archive-first, not delete-first**:
- current docs stay in-repo
- demo docs are grouped under `docs/demo/`
- planning/future-shape docs are grouped under `docs/architecture/`
- integration policy docs now live beside the practical integration bundle under `docs/integration/`

Top-level `docs/` is intentionally kept small so the first scan shows only the highest-value entry points.
