# Integration Readiness Gap Assessment

## Purpose

This document states exactly what is still missing for the RCA/AIOps system to move from the current validated demo state to an integration-ready product state.

It is intentionally narrow and operational:
- what is already proven
- what is only partially proven
- what still must be completed before broader integration claims are safe

---

## Current baseline

The system has already proven one real integrated RCA path on the demo microservice stack:
- seeded incident class: `DependencyTimeout`
- validated service: `order-service`
- runtime path: durable / full compiled graph
- planner path: provider-backed OpenAI-compatible seam
- final outcome: terminal `success` with grounded RCA output

What is proven on that path:
- alert ingest works
- investigation lifecycle runs end-to-end
- tool calls execute
- evidence is collected and normalized
- reflection reaches write
- final report contains non-empty `root_cause`
- final report contains non-empty `evidence_backing`
- citations include real `raw_excerpt` values

This means the project is no longer only a workflow shell or a thin-success demo.
It now has at least one live integrated RCA run on the demo stack that produces grounded output.

However, this is still a narrow proof, not a broad integration-ready certification.

---

## What “integration-ready” must mean

The product should only be called integration-ready when a new target application or microservice stack can be onboarded through a defined contract and then pass RCA acceptance in a repeatable, observable, and honest way.

That means:
- the intended runtime mode is explicit
- observability prerequisites are clear
- incident classes have adequate coverage
- evidence grounding quality is measurable
- failure modes are honest
- onboarding can be repeated without custom heroics

---

## Gap summary

The remaining gaps fall into 12 areas:

1. runtime default clarity and deployment mode control
2. broader incident-class coverage
3. broader service coverage
4. executable onboarding standard for target stacks
5. floor registry breadth and governance
6. operationally reliable planner contract
7. measurable RCA quality gates
8. repeatability and stability proof
9. observability for the RCA engine itself
10. honest failure-mode handling
11. security, tenancy, and boundary controls
12. packaging and deployment standardization

---

## 1. Runtime default clarity and deployment mode control

### Current state
- The full RCA path exists and has been validated.
- But the richer durable/full-graph runtime is not yet the universal default interpretation for every deployment.

### Missing
- one canonical deployment mode definition for “real RCA enabled”
- explicit distinction between:
  - minimal mode
  - durable/full-graph RCA mode
- startup validation that reports which mode is active
- fail-fast behavior when a deployment is expected to perform RCA but boots into minimal mode
- a clear operator-facing contract for required environment variables and dependencies

### Why it matters
Without this, a system may appear healthy while actually running a reduced path that cannot produce full RCA results.

### Exit criterion
A deployment can prove at startup whether it is in:
- context-only mode, or
- full integration-ready RCA mode

---

## 2. Broader incident-class coverage

### Current state
- Strong validated path exists for `DependencyTimeout/order-service`.

### Missing
Acceptance scenarios for additional real incident classes, at minimum:
- downstream timeout / dependency degradation
- service crash / pod restart
- 5xx error spike
- latency spike
- CPU saturation
- memory saturation
- DB connection exhaustion or query latency
- queue backlog
- log-only anomaly
- trace-correlated anomaly

### Why it matters
A single passing incident class does not prove that the engine generalizes across common production failure modes.

### Exit criterion
The system passes RCA acceptance on a representative matrix of incident classes, not only one seeded demo path.

---

## 3. Broader service coverage

### Current state
- Strong grounded proof currently exists mainly on `order-service`.

### Missing
Validation on multiple services with different operational shapes, for example:
- edge or gateway-facing API service
- dependency-heavy synchronous service
- stateful or data-bound service
- asynchronous or queue-driven service

### Why it matters
An RCA path that works for one service topology may not work equally well for others.

### Exit criterion
Grounded RCA quality remains acceptable across multiple service shapes, not just one validated service.

---

## 4. Executable onboarding standard for target stacks

### Current state
- Integration standard direction exists conceptually.
- It still needs to become a repeatable executable package.

### Missing
A concrete onboarding contract that tells an external team exactly what is required:
- required alert sources
- required metric families
- required labels and naming conventions
- required or recommended log fields
- required or recommended trace/span attributes
- supported incident payload shapes
- acceptance criteria for onboarding completion

Supporting implementation artifacts are also needed:
- sample OTEL configuration
- sample Prometheus configuration or scrape expectations
- sample Loki/log schema expectations
- alert payload mapping examples
- target-stack readiness checklist

### Why it matters
If onboarding depends on custom interpretation each time, the product is not truly integration-ready.

### Exit criterion
A new target stack can be onboarded using a documented, executable checklist and sample config bundle.

---

## 5. Floor registry breadth and governance

### Current state
- A seeded floor rule was enough to prove one demo path.

### Missing
- floor rules for the main incident families
- policy for minimum evidence per trigger class
- policy for valid source matching per trigger class
- clear governance for adding or updating rules during onboarding
- regression coverage for high-value floor rules

### Why it matters
If floor coverage remains ad hoc, new target systems will keep requiring special-case manual tuning.

### Exit criterion
The floor registry supports the main supported incident classes and has a maintainable change process.

---

## 6. Operationally reliable planner contract

### Current state
- Provider-backed planner seam is real and validated.
- Runtime-safe PromQL planning path is proven.

### Missing
- a durable execution contract for each supported tool family
- schema-safe plan outputs beyond the currently proven narrow path
- explicit handling for provider timeout, malformed output, and non-executable plans
- retry, timeout, and rate-limit policy
- roadmap for safely broadening planner output to logs, Kubernetes events, and other evidence tools

### Why it matters
Proof of life is not yet the same as operational reliability.

### Exit criterion
The planner produces executable, policy-bounded plans reliably under expected runtime conditions.

---

## 7. Measurable RCA quality gates

### Current state
- The system can now produce grounded output on the validated demo path.

### Missing
Quality metrics and acceptance thresholds such as:
- grounded citation rate
- empty `root_cause` rate
- empty `evidence_backing` rate
- usable-report rate
- false-grounding or wrong-link rate
- time-to-report
- run-to-run consistency

Suggested acceptance thresholds should also be defined, for example:
- report must include grounded evidence
- report must include non-empty root-cause claims
- citations must map back to real raw evidence
- confidence must not inflate when grounding is weak

### Why it matters
A system is not integration-ready if report quality cannot be measured and enforced.

### Exit criterion
RCA quality is judged by explicit metrics and pass/fail thresholds, not by anecdotal inspection.

---

## 8. Repeatability and stability proof

### Current state
- One successful integrated run is proven.

### Missing
- repeated reruns of the same scenario
- consistency checks across reruns
- restart/resume drills across multiple investigations
- soak or sequence tests for multiple consecutive investigations
- evidence that passing behavior is stable rather than incidental

### Why it matters
One pass is a milestone. Repeatable passes are what support integration claims.

### Exit criterion
The validated scenarios pass repeatedly with stable investigation behavior and acceptable output consistency.

---

## 9. Observability for the RCA engine itself

### Current state
- Investigation outputs are visible enough to validate individual runs.

### Missing
Engine-level observability, including:
- investigation lifecycle metrics
- node-level timing metrics
- tool-call success/failure counters
- provider latency and error metrics
- checkpoint/resume metrics
- structured logs keyed by `investigation_id`

### Why it matters
An integration-ready RCA engine must itself be operable, diagnosable, and supportable.

### Exit criterion
Operators can observe and troubleshoot the RCA engine with the same discipline expected of other production services.

---

## 10. Honest failure-mode handling

### Current state
- The system already has important fail-closed behavior in parts of the flow.

### Missing
Clear operational handling for:
- insufficient evidence
- provider unavailable
- adapter misconfigured
- unsupported incident class
- runtime mode mismatch
- floor not satisfiable

User-visible or operator-visible outputs should clearly distinguish these states rather than collapsing them into ambiguous failure or thin success.

### Why it matters
Integration-ready systems must fail honestly, not just succeed on good paths.

### Exit criterion
Every major failure class has a distinct, understandable outcome and operator guidance.

---

## 11. Security, tenancy, and boundary controls

### Current state
- Read-only access is one of the strongest validated parts of the system.

### Missing
- target-environment scoping rules
- namespace or tenant isolation expectations
- secret handling standard for provider/API credentials
- audit trail for evidence access and tool usage
- policy for what investigation data may be sent to an external LLM provider
- redaction or sanitization policy if required by target environments

### Why it matters
A technically working RCA engine may still fail integration review if boundary controls are not explicit.

### Exit criterion
Security and boundary behavior are documented, enforceable, and reviewable for real target environments.

---

## 12. Packaging and deployment standardization

### Current state
- The project can be run and validated in its current environment.

### Missing
- a deployment reference for local, staging, and target-cluster use
- standard environment variable contract
- sample manifests, compose files, or deployment templates as appropriate
- checkpoint database lifecycle guidance
- upgrade and migration guidance
- smoke tests after deployment

### Why it matters
Integration-ready means another team can deploy and verify the system without hidden tribal knowledge.

### Exit criterion
Deployment and post-deploy verification are documented and reproducible.

---

## Minimum checklist before claiming “integration-ready”

The product should not be described as integration-ready until all of the following are true:

1. Full-graph RCA mode is explicitly defined as a supported deployment mode.
2. Multiple incident classes pass integrated RCA acceptance.
3. Multiple services pass grounded RCA acceptance.
4. Onboarding checklist and sample configs are executable.
5. Floor registry coverage is broad enough to avoid ad hoc seeding.
6. Planner output contract is operationally reliable.
7. RCA quality is measured by explicit thresholds.
8. Repeatability and restart/resume stability are proven.

---

## Priority order

### P0 — required before broad external integration claims
- standardize full runtime mode
- add 3–5 additional acceptance scenarios
- validate across 2–3 additional service shapes
- convert onboarding standard into an executable checklist and config set
- define RCA quality pass/fail thresholds
- broaden floor registry coverage beyond the seeded demo path

### P1 — strongly recommended next
- broaden planner/tool execution contracts beyond the narrow proven PromQL path
- run repeatability and stability drills
- add self-observability for the RCA engine

### P2 — productionization hardening
- strengthen security and tenancy controls
- standardize packaging and deployment assets
- publish operational dashboards and runbooks

---

## Smallest practical path from current state to integration-ready trial

If the goal is not broad certification yet, but a realistic next-step “integration-ready trial”, the smallest high-value package is:

1. standardize full RCA runtime mode
2. add 3–5 incident acceptance scenarios beyond `DependencyTimeout`
3. validate on 2–3 additional services
4. ship onboarding checklist plus sample observability configs
5. define explicit RCA quality gates

This is the minimum credible step from:
- one proven live RCA path

to:
- a product that can be integrated into another controlled target environment with justified confidence

---

## Executive conclusion

The project has already crossed an important boundary:
- from an RCA architecture proof
- to a live integrated demo-path RCA success with grounded output

What it has not yet crossed is the broader boundary of repeatable integration readiness.

To reach that level, the system now needs breadth, repeatability, explicit operational contracts, and measurable quality gates — not a reinvention of the core architecture.

That is good news:
- the main missing work is expansion, hardening, and standardization
- not proof that the architecture is fundamentally non-viable

---

## Unresolved questions

1. Which additional incident classes should be treated as the first mandatory acceptance matrix?
2. Which 2–3 services in the demo or next target stack should be used for breadth validation?
3. Should durable/full-graph mode become the default deployment mode, or remain opt-in with explicit certification?
4. What evidence redaction policy is required before broader external LLM-backed deployments?
