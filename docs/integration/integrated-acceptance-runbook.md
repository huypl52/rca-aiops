# AIOps Integrated Acceptance Runbook — RCA AI Agent POC

**Project:** 26-rca-aiops  
**Status:** Leadership-readable runbook for per-target integrated RCA acceptance  
**Purpose:** Guide one acceptance run for a specific target stack and record whether the target is certified.

## 1. What this run is for

This runbook covers **one target stack** at a time.

It is the final acceptance step after:
- backend / UAT validation is complete
- demo microservice smoke validation is complete where applicable
- the target has been onboarded to the AIOps integration standard

Do not use this runbook to claim generic product readiness. It is for **per-target certification**.

## 2. Run inputs

Capture these before the run starts:
- target application / stack name
- environment / namespace
- owning team
- trigger source(s)
- observability sources available
- topology / ownership metadata source
- run owner and reviewer

## 3. Acceptance run structure

### Step 1 — Inject or reproduce the fault
Record:
- fault injected or reproduced
- how it was triggered
- when it started
- whether it was synthetic, replayed, or live

### Step 2 — Observe the trigger / symptom
Record:
- alert / event / symptom details
- source of the trigger
- timestamps
- any visible service impact

### Step 3 — Collect observability evidence
Collect read-only evidence from the integrated target:
- metrics
- logs
- traces / APM, if available
- runtime / infra metadata
- change / deploy metadata
- topology / ownership metadata

### Step 4 — Run the agent investigation
Record:
- whether the investigation ran
- investigation reference or run ID, if emitted
- evidence collected by the agent
- whether the workflow stayed read-only

### Step 5 — Review RCA output
Capture:
- RCA output / result
- suspected root cause or insufficient-evidence result
- confidence signal
- evidence references
- caveats or follow-up notes

### Step 6 — Conclude the run
Set the final result to one of:
- **PASS** — integrated RCA output is credible, traceable, and acceptable for the target
- **FAIL** — run completed, but output or evidence failed acceptance
- **BLOCKED** — run could not complete because of missing metadata, adapter gaps, or environment issues

## 4. Evidence checklist

For each run, capture:
- fault / reproduction proof
- trigger / symptom proof
- observability evidence links
- investigation proof
- RCA output proof
- final conclusion proof
- caveats or blockers

## 5. Pass / fail criteria

### PASS
All of the following are true:
- fault or symptom is real and documented
- trigger is visible and tied to the target
- observability evidence is collected and linked
- agent investigation ran
- RCA output is traceable to evidence
- conclusion is defensible for the target

### FAIL
One or more of the following are true:
- evidence is incomplete or inconsistent
- RCA result is unsupported
- run is traceable, but the outcome is not acceptable
- safety or audit expectations were violated

### BLOCKED
The run cannot proceed because of:
- missing trigger source
- missing observability source
- missing service identity or topology metadata
- read-only adapter not available
- no reliable fault reproduction path

## 6. Safety rules

- Keep all evidence access read-only.
- Do not use remediation actions as proof of RCA quality.
- Do not infer PASS without run evidence.
- Preserve the audit trail from trigger to conclusion.
- Record caveats instead of smoothing over uncertainty.

## 7. Run record template

| Field | Value |
|---|---|
| Target |  |
| Environment |  |
| Fault / symptom |  |
| Trigger source |  |
| Observability sources used |  |
| Investigation ran | Yes / No |
| RCA output / result |  |
| Conclusion | PASS / FAIL / BLOCKED |
| Caveats |  |
| Reviewer |  |
| Date |  |

## 8. Certification rule

A target is certified only when:
- onboarding checklist is complete enough to support the run
- integrated acceptance run is PASS
- caveats, if any, are explicit and accepted

## 9. References

- `docs/integration/integration-standard.md`
- `docs/integration/onboarding-checklist.md`
