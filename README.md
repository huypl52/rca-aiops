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

## CI invariants (AD-13)

See `ci/GATES.md` for the 6-gate reference. Story 0.1 wires #1 + #2 (HARD-FAIL); #3-6 are placeholders filled by later epics.

## Status

Story 0.1 (scaffold + CI gates #1/#2) — see `_bmad-output/implementation-artifacts/0-1-scaffold-ci-gates.md`.
