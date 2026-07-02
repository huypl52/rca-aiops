# 26-rca-aiops — RCA AI Agent POC

Read-only investigator (LangGraph Plan-Execute-Reflect) + 5-microservice demo + observability stack + 11-scenario benchmark.

**Scope POC:** investigator-only read-only (NO remediation) · single-tenant namespace `demo` · single-node · 13 Deferred NOT implemented.

## Module structure (AD-1 — one-way)

```
routers  →  services  →  graph  →  adapters / tools
```

Dependency direction **một chiều**, KHÔNG circular, KHÔNG back-edge (adapter↛graph, adapter↛services, tools↛graph, tools↛services). Enforced by CI gate #2 (import-linter, AD-13).

| Package | Role |
| --- | --- |
| `routers/` | FastAPI: ingest + read-store endpoints |
| `services/` | use-case: ingest, normalize, dispatch, read-store |
| `graph/` | LangGraph PE-R: 8 nodes + edges, compiled once (AD-2) |
| `adapters/` | read-only clients: prometheus, loki, k8s, qdrant, topology (AD-3) |
| `tools/` | read-only tool registry + executor_router dispatch (AD-3) |
| `models/` | Pydantic contracts AT PORTS: IncidentTrigger §3.4, Evidence §3.6 (AD-9) |
| `eval/` | 11-scenario benchmark, calibration, partial-credit, anti-hallucination (FR-10) |
| `playbooks/` | Qdrant playbook store + floor registry (declarative YAML, AD-12) |
| `config/` | floor registry, confidence mapping (AD-7), namespaces |
| `tests/` | CI gate self-tests + smoke (AD-13) |
| `checkpoints/` | SqliteSaver file backend (POC, AD-11) |
| `ci/` | gate scripts + import-linter contract + deny-set + GATES.md |

## Read-only boundary (AD-3 BLOCKER, §3.8)

Tool/adapter KHÔNG expose `write/exec/patch/delete/scale/rollback/restart/remediate`. `kubectl debug/exec/patch` KHÔNG tồn tại trong registry. Enforced at registry level (CI gate #1, AD-13), NOT via LLM.

## Tooling (lock-order D1, web-verified 2026-06-23)

Ruff (lint + format) · uv (package/runner + `uv.lock`) · mypy (type-check, `--strict`) · pytest · import-linter (gate #2).

## Quick start

```bash
uv sync                 # reproducible install from uv.lock
uv run ruff check       # lint
uv run ruff format --check
uv run mypy .           # type-check
uv run pytest           # tests + CI gate self-tests
uv run python ci/gate1_readonly_registry.py   # CI gate #1
uv run lint-imports     # CI gate #2
```

## Local app setup

This repo is a FastAPI backend plus demo/integration tooling.

There are two different ways to run it:
- **Local backend smoke mode** — start FastAPI on your machine, hit `localhost:8000`, validate ingest/read surfaces quickly
- **Full Kubernetes-backed demo mode** — use the `demo`, `observability`, and `rca` namespaces plus port-forwards/scripts to validate the real demo environment

A local `202 + investigation_id` proves the backend accepted a request. It does **not** prove the full cluster-backed demo stack is healthy.

### 1. Install dependencies

```bash
uv sync
```

### 2. Start the backend locally

Use the repo's FastAPI app entrypoint:

```bash
uv run fastapi dev routers/app.py
```

If you prefer uvicorn directly:

```bash
uv run uvicorn routers.app:app --reload
```

Useful local surfaces after startup:
- `http://127.0.0.1:8000/health` — health check
- `http://127.0.0.1:8000/docs` — OpenAPI/Swagger UI
- `http://127.0.0.1:8000/ui/` — demo UI when `demo/ui/` is present

### 3. Trigger and inspect one investigation

Example **local backend smoke** flow:

```bash
curl -X POST http://127.0.0.1:8000/api/alerts/prometheus \
  -H 'content-type: application/json' \
  -d '{"fingerprint":"demo-dependency-timeout-001","startsAt":"2026-07-01T10:00:00Z","labels":{"alertname":"DependencyTimeout","service":"order-service","severity":"critical","scenario":"dependency_timeout","namespace":"demo"},"annotations":{"summary":"upstream dependency timing out","description":"order -> payment upstream errors"}}'
```

Then poll:

```bash
curl http://127.0.0.1:8000/api/investigations/<investigation_id>
```

## Demo and environment setup

For the **full Kubernetes-backed demo** stack, the default replay path is:

```bash
export RCA_HYPOTHESIS_LLM_API_KEY=<your-key>
export RCA_HYPOTHESIS_LLM_API_URL=<your-llm-endpoint>
scripts/demo-mode-b.sh
```

That path owns deploy order, preflight, backend port-forward, trigger, and watch for the validated Prometheus report-centric story.

If you need to debug manually instead:
- start with `scripts/demo-preflight.sh` to verify kubectl context, cluster reachability, namespaces, and backend health
- treat `localhost:8000` as ambiguous until you know whether it is a local FastAPI process or a `kubectl port-forward` into `deploy/rca-backend`
- prefer the replay-owned port-forward target `127.0.0.1:18000` for manual cluster-backed runs
- the deployed backend should now serve the demo UI directly at `http://127.0.0.1:18000/ui/` after `kubectl -n rca port-forward deploy/rca-backend 18000:8000`
- do not claim Mode B / Mode C demo readiness from a local backend response alone

Then use the curated docs:

- `docs/demo/index.md` — demo doc entrypoint
- `docs/demo/guide.md` — canonical validated demo truth, run order, GO / NO-GO, fallback policy
- `docs/demo/operator-cheatsheet.md` — exact demo commands
- `docs/integration/index.md` — environment bootstrap and integration bundle
- `docs/integration/environment-bootstrap-runbook.md` — practical deploy/bootstrap order for `demo`, `observability`, and `rca`
- `docs/operator-runbook.md` — operator deployment guidance

Most useful demo scripts:

- `scripts/demo-preflight.sh` — readiness / GO-NO-GO check
- `scripts/demo-trigger-prometheus.sh` — direct Prometheus demo trigger
- `scripts/demo-trigger-grafana.sh` — live Grafana Loki trigger path
- `scripts/demo-watch-investigation.sh` — poll and summarize one investigation

## CI invariants (AD-13)

See `ci/GATES.md` for the 6-gate reference. Story 0.1 wires #1 + #2 (HARD-FAIL); #3-6 are placeholders filled by later epics.

## Documentation map

Start with `docs/index.md` for the curated documentation entry point.

Fast paths:
- `docs/current-rca-runtime-truth-table.md` — what is true in the runtime today
- `docs/integration/index.md` — onboarding and integrated acceptance bundle
- `docs/demo/index.md` — demo prep, scripts, and reporting docs
- `docs/operator-runbook.md` — operator deployment runbook
- `docs/architecture/index.md` — planning and future-shape docs

## Status

Story 0.1 (scaffold + CI gates #1/#2) completed.
