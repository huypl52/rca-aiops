# AIOps Onboarding Checklist — RCA AI Agent POC

**Project:** 26-rca-aiops  
**Status:** Practical onboarding checklist for a specific target stack  
**Purpose:** Verify the target has the minimum metadata, observability, and evidence wiring needed before an integrated RCA acceptance run.

## How to use this checklist

- Use one copy per target stack or environment.
- Complete the checklist in order.
- Record blockers immediately.
- Do not mark the target certified until the integrated acceptance run passes.

## 1. Target identity and scope

| Item | Status | Notes |
|---|---|---|
| Target application / stack named |  |  |
| Owning team identified |  |  |
| Environment / namespace identified |  |  |
| Service inventory listed |  |  |
| Primary contact / escalation owner named |  |  |

## 2. Trigger and alert sources

| Item | Status | Notes |
|---|---|---|
| Metric alert source available |  |  |
| Log alert source available |  |  |
| Trace / APM source available, if used |  |  |
| Runtime / Kubernetes event source available, if relevant |  |  |
| Change / deploy signal source available, if relevant |  |  |
| Trigger payload includes timestamp and target identity |  |  |

## 3. Observability coverage

| Item | Status | Notes |
|---|---|---|
| Metrics available for core service behavior |  |  |
| Logs searchable by service / environment |  |  |
| Traces or APM usable for RCA context, if present |  |  |
| Runtime / infra metadata available |  |  |
| Change / deploy metadata available |  |  |
| Topology / dependency metadata available |  |  |

## 4. Evidence adapter readiness

| Item | Status | Notes |
|---|---|---|
| Read-only evidence adapters documented |  |  |
| Adapter access is read-only only |  |  |
| Evidence normalization fields mapped |  |  |
| Evidence time-window rules defined |  |  |
| Audit trail / request logging enabled |  |  |

## 5. RCA output readiness

| Item | Status | Notes |
|---|---|---|
| RCA output contract agreed |  |  |
| Root-cause / insufficient-evidence result format defined |  |  |
| Confidence / caveat format defined |  |  |
| Output references source evidence |  |  |
| No remediation action is embedded by default |  |  |

## 6. Safety and fail-closed controls

| Item | Status | Notes |
|---|---|---|
| No write / patch / delete / exec path in evidence access |  |  |
| Fail-closed behavior documented |  |  |
| Auditability expectations documented |  |  |
| Operator review / sign-off owner assigned |  |  |

## 7. Onboarding maturity gate

| Tier | Requirement | Status |
|---|---|---|
| Tier 0 — Discovered | Target identified, but metadata is incomplete |  |
| Tier 1 — Connected | Trigger and identity are wired |  |
| Tier 2 — Observable | Metrics, logs, traces, and metadata are usable |  |
| Tier 3 — Accepted | Integrated RCA acceptance run passed |  |

## 8. Acceptance-run readiness

Before running the acceptance run, confirm:
- target identity is complete
- observability sources are reachable read-only
- evidence adapters are documented
- RCA output contract is known
- blocker owner is assigned if a control is missing

## 9. Blocker log

| Blocker | Severity | Owner | Next action | Status |
|---|---|---|---|---|
|  |  |  |  |  |

## 10. Checklist conclusion

| Field | Value |
|---|---|
| Target status | Not onboarded / Partial / Ready for acceptance / Accepted |
| Reviewer |  |
| Date |  |
| Notes |  |
