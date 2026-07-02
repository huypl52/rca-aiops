# Demo UI Direction — Alert-First RCA Incident Console

> Product/design note for a demo UI over the current RCA runtime.
> Scope: handoff-ready direction. No implementation. Grounded in the repo as of 2026-07-02.

## 1. Product direction

A **single-page, alert-first incident console** for the RCA agent POC. The console is not a generic "chat with AI" surface. The defining interaction is:

> An alert arrives → an **incident** appears in the inbox → the user opens it → they **chat with the agent about that specific incident** (its evidence, plan, hypothesis, RCA).

Everything (chat included) is **incident-scoped**. There is no free-floating assistant. The incident is the anchor; the agent already has context (the alert + the running investigation), and the chat operates inside that context.

Audience: stakeholders / demo viewers + the operator running the demo. Not a production multi-tenant product.

Primary UX loop:

```
alert webhook ──▶ incident in inbox ──▶ open incident detail
                                          │
                     ┌────────────────────┼────────────────────┐
                     ▼                    ▼                    ▼
              status/timeline      RCA report          chat panel
              (investigation)      (on completion)     (incident-scoped)
```

## 2. Backend truth (what the UI actually has today)

Grounded in `routers/`, `services/`, `graph/`, `models/`:

- **Ingest is real.** Three endpoints accept normalized triggers:
  - `POST /api/alerts/prometheus` (PrometheusAlertmanager)
  - `POST /api/alerts/grafana` (Grafana Alerting / Loki)
  - `POST /api/events/kubernetes` (KubernetesEvent)
  - Each returns `202 + investigation_id` (model `InvestigationAccepted`).
- **Read-store is polling-only.** `GET /api/investigations/{id}` → `{status, state_snapshot, report}`. Status lifecycle: `running / success / failed / partial`.
- **No streaming today.** No SSE, no WebSocket. "Live" means client polls `state_snapshot`.
- **No chat surface today.** The agent is a read-only Plan-Execute-Reflect graph. It does not accept user turns, does not ask back, has no conversational node. Any "chat" is a UI-layer construct until a backend endpoint is added.
- **Grafana path is a webhook, not raw logs.** Grafana Alerting/Loki sends an **alert webhook** into RCA (the `GRAFANA_ALERTING_LOKI` trigger). RCA does not ingest a raw log stream from Grafana; the signal is an alert carrying context. The agent fetches logs later via the read-only Loki adapter as evidence.
- **`state_snapshot` reality (POC, must not overpromise):**
  - Populated today: `plan`, `hypotheses`, promoted-plan identity, lifecycle `status`.
  - **Stub / thin today:** `evidence` is empty (`evidence_count=0`) — real `evidence_normalizer` is Story 4-2 (DEFERRED). `reflector` is a stub returning honest `partial` — real reflector is Story 4-3 (DEFERRED).
  - ⇒ The timeline can show **plan + hypotheses + status** richly. **Evidence cards and reflect content will be sparse until 4-2/4-3 land.** The UI must degrade gracefully, not fake these.

This is the hard constraint: the UI shows what the runtime actually produces.

## 3. Information architecture

Four surfaces, one shell:

| Surface | Role | Data source |
|---|---|---|
| **Inbox / incident list** | Alerts "arriving" + open incidents | call (poll or push of an incident index) |
| **Incident detail** | Header (trigger, severity, services, time) + investigation status/timeline | `GET /api/investigations/{id}` |
| **RCA report** | Cause, confidence, playbook hit, cited evidence (when present) | `report` from same GET |
| **Chat panel** | Incident-scoped agent interaction | MVP: grounded pseudo-chat / preset Q&A. Phase 2: true multi-turn |

Note: there is **no incident-list endpoint today** (only single-id GET). See §8 caveat — MVP must either keep a client-side list of seen `investigation_id`s from fired triggers, or that endpoint is a phase-1 backend addition.

## 4. Screen breakdown / wireflow

### 4.1 Inbox — incident list
- Left rail. One row per incident.
- Row fields: severity dot (info/warning/critical), `alert_name`, `canonical_trigger`, source badge (Prometheus / Grafana-Loki / K8s), `status` chip (running/success/failed/partial), timestamp.
- **Arrival behavior:** new alert → new row slides in at top, severity-colored, marked unread. A subtle toast/flash draws the eye (the "alert arrived" moment of the demo).
- Click row → opens **Incident detail** in the main pane.

### 4.2 Incident detail
- **Header:** title (`alert_name`), `canonical_trigger`, severity, affected services (from trigger context), namespace `demo`, fired-at time, source badge.
- **Status strip:** current lifecycle status; a progress indicator across Plan → Execute → Reflect → Report (derived from `status` + presence of `report`).
- **Timeline (center):** derived from `state_snapshot`. Shows plan promotion, hypotheses tried, hypothesis-advance on replan, terminal status. Each step = one entry, time-stamped client-side. Empty-state text is honest ("evidence collection pending runtime support") rather than fabricated cards.

### 4.3 RCA report
- Renders when `status ∈ {success, failed, partial}` (i.e., `report` present).
- Fields: root-cause statement, confidence, playbook hit (if any), cited evidence list (may be empty in POC — show "no evidence surfaced" honestly).
- `partial` is shown as a legitimate outcome, not hidden — it is the agent saying "I could not reach confidence." This is a feature for the demo, not a bug.

### 4.4 Chat panel (right)
- Incident-scoped: header reads "Chat about incident {id}".
- **MVP (phase 1): grounded pseudo-chat + preset Q&A.** The agent does not take free turns. Instead:
  - The agent posts **narrated progress** as one-way chat bubbles (plan chosen, hypothesis advanced, status reached) — same data as the timeline, rendered conversationally.
  - A row of **preset questions** the user can click, e.g. "What did you find?", "Which service is the likely cause?", "How confident are you?". Answers are **rendered from `report` + `state_snapshot`**, not invented. If the underlying field is empty, the answer says so.
- **Phase 2: true multi-turn chat.** Requires a new backend capability (see §5). Free-text turns answered in incident scope.

### 4.5 Notification / arrival behavior
- Real-time arrival in the inbox is the demo's "spark". Since there is no push today, MVP simulates arrival client-side: when the user fires a trigger (or the demo harness fires one), the client mints the row immediately from the `202 + investigation_id` response, then begins polling.
- No browser notifications / sound required for MVP; a visual highlight suffices.

## 5. MVP (phase 1) vs phase 2

### Phase 1 — MVP (ships on the runtime as-is + minimal optional backend)
Goal: a believable, honest single-pass demo.

- Inbox with client-side incident list (from fired-trigger responses; or one small backend `GET /api/investigations` index if added).
- Incident detail: header + status strip + Plan→Report progress.
- Timeline from `state_snapshot` (plan/hypotheses/status rich; evidence/reflector honest-empty where stubbed).
- RCA report rendering for terminal statuses, including graceful `partial`.
- Chat panel = **one-way narrated bubbles + preset Q&A grounded in `report`/snapshot**. No free-text turns.
- Trigger buttons wired to the 3 ingest endpoints using scenarios from `docs/demo-script.md` (e.g., `dependency_timeout` on `payment`).

**What is allowed to be added to the backend in MVP (small):**
- A read-only incident-index endpoint (`GET /api/investigations`) listing known ids — purely additive, does not touch graph or read-only boundary.
- Optional: a single `StaticFiles` mount to serve the UI from FastAPI.

### Phase 2 — true incident-scoped chat (requires new backend surface)
Goal: the user can type arbitrary questions scoped to a finished/running incident.

- New backend capability: an LLM-backed Q&A endpoint scoped to one `investigation_id`, answering **only from that incident's `state_snapshot` + `report`** (grounded retrieval; no remediation, no out-of-scope actions).
- Multi-turn: server keeps a per-incident transcript (in-memory for POC is fine).
- Still **read-only**: the chat cannot mutate state, run tools, or escalate. It explains; it does not act.
- Streaming (SSE) becomes worth adding **only here**, to make typed answers feel live. Not needed in MVP.

## 6. Recommended direction

**Build the single-page alert-first console, phase-1 MVP first, as a self-contained static front-end calling the existing FastAPI endpoints.**

- One file (or a small static folder) under `demo/ui/`, vanilla HTML/JS, no build toolchain, no new heavy dependency (no Streamlit/Gradio, no React). Fits the POC, KISS/YAGNI, does not perturb the 6 CI gates or the read-only boundary.
- Center the UX on the **incident**, with chat as an incident-scoped panel, not a standalone assistant.
- Treat chat as **grounded pseudo-chat + preset Q&A in MVP**; defer true multi-turn to phase 2 with its own backend endpoint.
- Be visibly honest about POC limits: sparse evidence/reflector, `partial` as a real outcome, no push/streaming.

## 7. What NOT to build yet (and why)

- **No true conversational agent in phase 1.** The graph has no human-in-the-loop turn; faking it overpromises. Ship narrated bubbles + preset Q&A instead.
- **No WebSocket/SSE in MVP.** Polling the read-store is enough for a demo and avoids backend changes. Add SSE only when phase-2 typed answers need liveness.
- **No raw-log streaming panel.** Grafana gives RCA an alert webhook, not a log firehose; the agent pulls logs on demand as evidence (currently stubbed). A live tail would misrepresent the pipeline.
- **No remediation / action buttons.** Read-only investigator is a hard boundary (AD-3). No "restart pod", "scale", "rollback". The console must not imply control it does not have.
- **No multi-tenant / auth / persistence beyond POC.** Single namespace `demo`, in-memory lists are fine.
- **No fabricated evidence cards.** Where `evidence_count=0`, say so. Do not invent metrics/logs to fill the timeline.

## 8. Acceptance criteria (for future implementation)

A phase-1 MVP is done when:

1. Firing a trigger (any of the 3 endpoints) causes a new incident row to appear in the inbox within the poll interval, correctly severity/source/status labeled.
2. Opening the incident shows a header whose fields match the fired `IncidentTrigger` (`alert_name`, `canonical_trigger`, severity, source, namespace).
3. The status strip + Plan→Report progress track `running → terminal` consistent with `GET /api/investigations/{id}`.
4. On terminal status, the RCA report renders `cause`, `confidence`, and either cited evidence or an honest empty state — never fabricated.
5. `partial` is rendered as a valid, labeled outcome (not as success or error).
6. Chat panel shows one-way narrated progress and at least 3 preset Q&A items whose answers are sourced from `report`/`snapshot`; an empty underlying field yields an explicit "not available" answer.
7. The UI runs against the live FastAPI app with no backend behavioral change other than the optional additive index/static mount.
8. No CI gate (#1 read-only, #2 import-linter, …) regresses; no agent module is imported by the UI.

## 9. Sample presenter / demo flow

1. **Open the console** → empty inbox. "This is the RCA operator view."
2. **Fire a scenario** (button → `POST /api/alerts/prometheus`, `dependency_timeout` on `payment`) → an incident row **slides in**, red critical dot. "Alert arrived. RCA opens an incident automatically."
3. **Click the incident** → detail opens; status = `running`; timeline shows the planner picking the top hypothesis and promoting a plan. Chat panel narrates: *"Investigating `payment` as the likely root…"*.
4. **Watch the timeline advance** (poll) → hypothesis-advance on replan; status flips to `success` (or `partial`).
5. **RCA report fills** → cause, confidence, playbook hit. "Here is the cited evidence." (If evidence is empty in the POC build, say: "evidence collector lands in Story 4-2 — the conclusion still stands from the planner/reflector.")
6. **Click a preset chat question** ("How confident are you?") → grounded answer from `report`.
7. **Closing line:** "Every conclusion here is incident-scoped and read-only — the agent explains, it never acts."

## 10. Risks / guardrails (do not overpromise)

- **Evidence/reflector are stubbed in the POC.** Do not dress the timeline as if rich evidence exists. Honest empty states only.
- **Chat is not an agent capability in MVP.** Label preset Q&A as "answers from the investigation," not "the agent thinking in real time."
- **No streaming = polling latency.** Set expectations: updates arrive per poll interval, not per token.
- **`partial` must not look like failure or success.** It is the agent declining to overclaim — surface it as a first-class status.
- **Read-only is inviolable.** No control actions anywhere in the UI; the console observes and explains.
- **Incident list has no backend source today.** Either add a tiny additive index endpoint or maintain the list client-side from fired triggers. Do not pretend incidents the client never fired will appear.

## 11. Open questions for next step

- Confirm whether phase-1 may add a read-only `GET /api/investigations` index endpoint, or must stay purely client-side.
- Confirm whether the UI should also support a **replay** mode (recorded incident JSON) as a demo fallback when the live stack is flaky.
- Decide serving: mount via FastAPI `StaticFiles` vs open a static file directly.
