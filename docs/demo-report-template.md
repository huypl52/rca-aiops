# Demo Report Template

**Project:** 26-rca-aiops  
**Status:** Demo-result template  
**Purpose:** Record one demo or acceptance-style walkthrough without overstating the runtime.

## 1. Run summary

| Field | Value |
|---|---|
| Demo date |  |
| Presenter |  |
| Audience |  |
| Environment |  |
| Cluster type |  |
| Demo mode | Lifecycle only / Validated direct Prometheus report path / Validated live Grafana trigger path |
| Primary scenario | DependencyTimeout / DNSFailureLogSpike |
| Target service | order-service / user |
| Namespace | demo |
| Primary live path | Direct Prometheus alert → investigation → cited RCA report / Grafana Loki alert → backend ingest acceptance |
| Secondary or excluded paths | Kubernetes-event / any unrehearsed path |

## 2. Runtime mode declaration

Record exactly which runtime path was active.

| Item | Value |
|---|---|
| `RCA_CHECKPOINT_DB` present | Yes / No |
| Provider-backed planner env present | Yes / No |
| Expected runtime path | Minimal path / Validated direct Prometheus report path / Durable-full-graph path |
| Verified before demo | Yes / No |
| Notes |  |

## 3. Trigger used

| Field | Value |
|---|---|
| Trigger source | Direct Prometheus alert / Grafana alert / Kubernetes event |
| Endpoint used |  |
| Fingerprint / identifier |  |
| Alert / event name |  |
| Severity |  |
| Start time |  |
| Payload summary |  |

## 4. Environment proof

Record the minimum environment evidence.

| Check | Result | Notes / Evidence |
|---|---|---|
| `docker`, `kubectl`, `kind` available | PASS / FAIL / BLOCKED |  |
| `demo` namespace ready | PASS / FAIL / BLOCKED |  |
| `observability` namespace ready | PASS / FAIL / BLOCKED |  |
| `rca` namespace ready | PASS / FAIL / BLOCKED |  |
| Prometheus path healthy | PASS / FAIL / BLOCKED |  |
| Grafana path healthy | PASS / FAIL / BLOCKED |  |
| `rca-backend` service reachable | PASS / FAIL / BLOCKED |  |
| `/health` returns OK | PASS / FAIL / BLOCKED |  |
| Backend `/metrics` available | PASS / FAIL / BLOCKED |  |

## 5. Ingest and investigation proof

| Check | Result | Notes / Evidence |
|---|---|---|
| Trigger POST returned `202` | PASS / FAIL / BLOCKED |  |
| Response contained `investigation_id` | PASS / FAIL / BLOCKED |  |
| Investigation could be polled | PASS / FAIL / BLOCKED |  |
| Status transitioned as expected | PASS / FAIL / BLOCKED |  |

## 6. Investigation response snapshot

Fill with the strongest truthful statement.

| Field | Value |
|---|---|
| Investigation ID |  |
| Terminal status | running / success / partial / failed / blocked |
| `report` present | Yes / No |
| Poll response excerpt |  |

## 7. RCA output review

Complete this section only if `report` is non-null.

| Field | Value |
|---|---|
| `root_cause` non-empty | Yes / No |
| `evidence_backing` non-empty | Yes / No |
| `confidence` present | Yes / No |
| `open_questions` captured | Yes / No |
| `uncertainty` captured | Yes / No |
| `remediation` empty as expected | Yes / No |

### RCA notes

- Root-cause summary:
- Evidence excerpt summary:
- Why the output was or was not credible:

## 8. Read-only and honesty check

| Check | Result | Notes |
|---|---|---|
| Demo stayed read-only on the RCA side | PASS / FAIL |  |
| Presenter avoided claiming full RCA when `report` was null | PASS / FAIL |  |
| Caveats were stated explicitly | PASS / FAIL |  |

## 9. Final verdict

Choose one:
- **PASS** — the intended demo scope worked and was presented honestly
- **FAIL** — the demo ran, but the intended scope did not hold up
- **BLOCKED** — the demo could not complete because environment/runtime prerequisites were missing

### Verdict details

| Field | Value |
|---|---|
| Verdict | PASS / FAIL / BLOCKED |
| Scope actually demonstrated |  |
| Main blocker or success factor |  |
| Follow-up action |  |

## 10. Recommended next step

Pick one:
- keep using the validated direct Prometheus demo language
- use the validated live Grafana trigger language only when the real alert and backend `202` were both seen in that environment
- verify and promote Kubernetes events only after a separate rehearsal
- harden environment before the next demo
- narrow the audience claim to operator workflow only

## 11. Evidence bundle

Store references or paste short excerpts for:
- tooling checks
- rollout checks
- runtime env checks
- trigger request/response
- poll response
- RCA report excerpt if present

## 12. Unresolved questions

- Did the environment truly run the validated direct Prometheus path, or only intend to?
- Is the chosen scenario still the strongest stakeholder-facing story after the latest runtime changes?
- What audience claim is approved for the next demo: operator workflow, RCA capability, or integration readiness?
