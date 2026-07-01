# Current RCA Runtime Truth Table

## Purpose

This document states **what the RCA/AIOps system is actually doing today at runtime**, what is only a **designed seam**, and what is still **deferred**.

Use this to avoid overclaiming that the current POC is already a fully LLM-powered, production-grade RCA agent.

---

## Executive summary

The current system is best described as:

> **A LangGraph-based RCA workflow with deterministic/rule-based default logic and read-only evidence adapters, where LLM-powered reasoning is designed as a future seam rather than the default runtime path.**

Important implications:

- **LangGraph is present** as the workflow/orchestration engine.
- **LLM API usage is not the default runtime behavior.**
- Several critical reasoning nodes currently use **deterministic / rule-based defaults**.
- The deployed/default dispatcher can still run a **minimal runner** instead of the full compiled graph unless durable/full-graph wiring is enabled.

---

## Source references

Primary source references for this truth table:

- `README.md`
- `docs/PROJECT_SPECS.md`
- `graph/runner.py`
- `graph/compiled.py`
- `graph/nodes/hypothesis_planner.py`
- `graph/nodes/evidence_normalizer.py`
- `graph/nodes/reflector.py`
- `graph/nodes/rca_writer.py`
- `services/dispatch.py`
- `services/durable.py`
- `routers/app.py`
- `tests/test_dispatch_readstore_resume.py`

---

## Runtime truth table

| Area | Current reality | Evidence | Product interpretation |
|---|---|---|---|
| Workflow engine | **Active** | `README.md:3`, `docs/PROJECT_SPECS.md:224-241` | The system does implement a Plan-Execute-Reflect workflow shape. |
| LangGraph graph assembly | **Implemented** | `graph/compiled.py:242-342` | The 8-node graph exists and can be compiled with real ENV/REF/WRT nodes. |
| Default dispatcher runner | **Minimal by default** | `graph/runner.py:183-219`, `services/dispatch.py:379-390` | The default runtime path is not automatically the full RCA graph. |
| Full compiled graph runner | **Available, but opt-in via composition/wiring** | `graph/compiled.py:618-707`, `services/durable.py:40-80` | The richer runtime path exists, but is not the universal default path. |
| Hypothesis generation | **Env-gated provider-backed seam with deterministic fallback** | `graph/nodes/hypothesis_planner.py:16-19`, `graph/hypothesis_sources.py:1-29`, `graph/hypothesis_sources.py:290-311` | The planner can be bound to a provider-backed source at deployment time, but the deterministic source remains the default. |
| Evidence normalization | **Deterministic** | `graph/nodes/evidence_normalizer.py:3-10`, `58-63` | The system normalizes evidence without LLM summarization by default. |
| Sufficiency / reflection | **Deterministic floor + deterministic default ceiling** | `graph/nodes/reflector.py:11-20`, `46-52`, `76-78` | The anti-hallucination gate is real, but not currently powered by a live LLM evaluator. |
| RCA writing | **Deterministic projection from state/evidence** | `graph/nodes/rca_writer.py:11-15`, `58-64` | Report generation is structured and safe, but not free-form LLM synthesis. |
| Read-only evidence access | **Implemented and enforced** | `README.md:30-33`, `docs/PROJECT_SPECS.md:243-255` | This is one of the strongest validated parts of the current system. |
| External LLM API path | **Present for the planner seam; opt-in, provider-gated, and live-validated on the OpenAI-compatible rerun path** | `graph/hypothesis_sources.py`, `docs/uat/integrated-rca-acceptance-run.md` | The system now has a proven provider-backed planner path, but it is still non-default and narrowly validated. |
| Integrated RCA on live demo stack | **Grounded RCA success proven on the seeded `DependencyTimeout/order-service` demo path** | `docs/uat/integrated-rca-acceptance-run.md`, `docs/uat/uat-closeout-bundle.md` | The alert-driven demo path now reaches `success` with non-empty `root_cause`, non-empty `evidence_backing`, and real citations. Broader target-stack certification is still pending. |

---

## What is actually happening today

## 1. The project really does implement agent-style workflow orchestration

The workflow described in the project spec is real:

- incident context build
- playbook retrieval
- hypothesis planning
- plan validation
- executor routing
- evidence normalization
- reflection
- RCA writing

References:

- `docs/PROJECT_SPECS.md:224-241`
- `graph/compiled.py:263-329`

So this is **not** just a CRUD backend pretending to be an RCA system.

---

## 2. But “agentic workflow” does not currently mean “LLM-powered reasoning”

The repo repeatedly states that several nodes are currently:

- deterministic
n- pure
- no LLM
- no wall-clock
- no random
- no IO

This is a deliberate POC choice to keep the system:

- reproducible
- CI-testable
- bounded
- safer under read-only constraints

Examples:

- `graph/nodes/hypothesis_planner.py:16-19`
- `graph/nodes/evidence_normalizer.py:8-10`
- `graph/nodes/reflector.py:76-78`
- `graph/nodes/rca_writer.py:14-15`

---

## 3. Hypothesis planning is currently rule-based by default

The planner explicitly says:

- default source = deterministic rule-based source
- real LLM source = deferred / swappable later

References:

- `graph/nodes/hypothesis_planner.py:16-19`
- `graph/nodes/hypothesis_planner.py:187-205`

Meaning:

- the system has a **slot** where LLM reasoning can be added
- that slot is **not the default production path today**

---

## 4. Reflector and RCA writer are also deterministic by default

### Reflector
The reflector currently uses:

- deterministic floor check
- deterministic default confidence behavior
- hard fail-closed ordering

References:

- `graph/nodes/reflector.py:11-20`
- `graph/nodes/reflector.py:46-52`

### RCA writer
The writer is a deterministic projector over state/evidence, not a live generative model call.

References:

- `graph/nodes/rca_writer.py:11-15`
- `graph/nodes/rca_writer.py:44-64`

Meaning:

- current RCA output is structured and safe
- but not yet the same thing as a model-rich investigative report writer

---

## 5. The default runtime path may still be minimal

This is the most important operational truth.

The default dispatcher uses `ContextBuilderRunner()` unless a different dispatcher is wired in:

- `services/dispatch.py:386-390`

And `ContextBuilderRunner` only:

- builds initial state
- runs `incident_context_builder`
- returns `status="success"`
- returns `report=None`

Reference:

- `graph/runner.py:183-219`

This is also reflected in tests:

- `tests/test_dispatch_readstore_resume.py:410-414`

So a “successful investigation” in the default/minimal path does **not** necessarily mean the full RCA graph executed.

---

## 6. The full graph is available, but not always the active runtime default

`build_default_compiled_runner()` assembles the richer path with:

- real evidence normalizer
- real reflector
- real RCA writer
- full compiled LangGraph

Reference:

- `graph/compiled.py:624-629`
- `graph/compiled.py:690-707`

But this is wired into the app only through the durable/env-gated path:

- `services/durable.py:40-80`
- `routers/app.py:88-94`

And `services/durable.py` explicitly says:

- when `RCA_CHECKPOINT_DB` is **unset**, the app remains on the minimal `ContextBuilderRunner` path

Reference:

- `services/durable.py:46-47`

---

## What has been validated vs not yet validated

## Validated well

### Backend / workflow / contracts
- ingest normalization
- async dispatch/read-store
- read-only registry boundary
- checkpoint/resume behavior
- evidence normalization contract
- auditability/read-store flow

See UAT docs:

- `docs/uat/uat-coverage-matrix.md`
- `docs/uat/uat-execution-log.md`
- `docs/uat/uat-closeout-bundle.md`

### Demo microservice smoke
- demo services reachable
- gateway/upstream wiring works
- direct smoke pass on all 5 demo services

See:

- `docs/uat/demo-microservice-smoke-status.md`

---

## Validated on the seeded demo path (Phase 2, 2026-07-01)

### Live integrated RCA on the demo stack
The env-gated durable rerun on the demo `DependencyTimeout/order-service` path recorded:

- investigation reached terminal `success`
- `next_action = write`
- `report != null`
- `evidence_count = 3`
- `tool_calls_count = 3`
- report confidence `{ceiling_confidence: 0.75, categorical: high}`
- `root_cause`: non-empty, with ranked candidates carrying real citations
- `evidence_backing`: non-empty, with `raw_excerpt` citations from Prometheus evidence

See:

- `docs/uat/integrated-rca-acceptance-run.md`

Meaning:

- the full graph progresses to a terminal success state on the seeded demo path
- the sufficiency floor and provider-backed planner seam are both active
- the LLM planner is live-exercised: Phase 2 evidence shows LLM-generated hypothesis plans that differ from the deterministic fallback
- the RCA artifact is grounded with real evidence citations, not a thin terminal-success shell

### Still not broadly validated

The above proof is narrow. It does not yet cover:
- multiple incident classes beyond `DependencyTimeout`
- multiple service topologies beyond `order-service`
- repeatability across many consecutive runs
- production-scale observability and security controls

---

## Product truth: what we can and cannot claim today

## Safe claims

We can safely say the current product is:

- a **LangGraph-based RCA workflow platform**
- **read-only by design and enforcement**
- **deterministic and testable by default**
- **integration-ready** via adapters/contracts/checklists/runbooks
- **not yet fully certified** as a strong RCA-quality engine on a target stack

## Unsafe claims

We should **not** currently say:

- “the system is already a fully LLM-powered RCA agent”
- “the product is plug-and-play for arbitrary app servers”
- “live integrated RCA is already broadly proven end-to-end across target stacks”

---

## Practical interpretation for roadmap

## Current state

### What exists now
- workflow skeleton: **real**
- read-only adapters and registry: **real**
- deterministic RCA contracts: **real**
- UAT/backend validation: **real**
- demo smoke validation: **real**

### What is now live (Phase 2)
- LLM-powered hypothesis generation (env-gated, live-validated on the demo path)
- durable/full-graph RCA with grounded output (env-gated via `RCA_CHECKPOINT_DB`)
- Alertmanager webhook ingestion (envelope unwrapping)

### What is still a seam
- richer confidence assessment (deterministic ceiling, not LLM-evaluated)
- richer summarization / narrative synthesis (RCA writer is deterministic projection)
- stronger integrated RCA behavior on live targets beyond the seeded demo path

### What remains to become “LLM-powered RCA for real”
1. wire an actual LLM-backed planner/assessor/summarizer path
2. ensure that full compiled graph is the intended runtime path for target deployments
3. pass integrated RCA acceptance on a live/staging target stack
4. certify per-target onboarding via the new integration standard + acceptance runbook

---

## Bottom line

The current system is:

> **an RCA platform with a real agentic workflow shape, where the LLM hypothesis planner seam is now live-validated on the seeded demo path. Other reasoning nodes (reflector, RCA writer) remain deterministic. Broader target-stack certification is still pending.**

That is not a failure.
It means the project has already built:

- control flow
- safety boundaries
- evidence contracts
- onboarding strategy
- a live LLM planner seam with deterministic fallback

What remains is breadth (more incident classes, more services), hardening (repeatability, quality gates), and productionization (security, packaging, self-observability).

---

## Recommended next actions

1. Use the Phase 1 planner profile as the narrow implementation contract for the first LLM seam.
2. Decide whether the product should stay primarily deterministic, or become explicitly LLM-powered.
3. If LLM-powered is the goal, define the first real runtime LLM insertion points:
   - hypothesis planner
   - evidence summarizer
   - confidence assessor
4. Make the target deployment path explicit:
   - minimal context-builder mode
   - full compiled graph mode
5. Re-run integrated acceptance after fixing the current evidence/report blocker.

---

## Unresolved questions

1. Which node should be the first production LLM insertion point: planner, summarizer, or reflector?
2. Should full compiled graph become the default deployment path, or remain opt-in until integrated acceptance passes consistently?
3. What target live/staging system will be used for the first certified integrated RCA run?
