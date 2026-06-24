# deploy/Dockerfile — the RCA backend (the agent) image (Story 7.3 AC2).
#
# Deploys the FastAPI routers/ + LangGraph graph/ agent as `rca-backend`, the Service the 7.2
# trigger sources POST to (http://rca-backend.rca.svc.cluster.local:8000). The AGENT CODE is
# UNCHANGED by this story; this image only packages the existing packages behind a uvicorn
# entrypoint.
#
# Checkpointer (CS Q2): Story 7.3 deploys with the CURRENT wiring — NO SqliteSaver yet
# (langgraph-checkpoint-sqlite is pinned but unused; graph/compiled.py compiles bare). The
# SqliteSaver swap + durable InvestigationStore is Story 7.4.
#
# PYTHONHASHSEED=42 — deterministic hash ordering (AD-12 / NFR-Determinism) for the agent
# process, matching the gate-suite discipline.
FROM python:3.12-slim

ENV PYTHONHASHSEED=42 \
    PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Runtime deps — pyproject [project].dependencies (locked 2026-06-23, D2). Installed explicitly
# (not `pip install .`) so dev-only tooling (ruff/mypy/pytest/import-linter) is excluded.
RUN pip install \
      langgraph==1.2.6 \
      langgraph-checkpoint-sqlite==3.1.0 \
      fastapi==0.138.0 \
      uvicorn==0.49.0 \
      httpx==0.28.1 \
      pydantic==2.13.4 \
      pyyaml==6.0.3 \
      qdrant-client==1.18.0

# Agent packages — the hatch wheel packages minus dev-only eval/ci.
COPY routers services graph adapters tools models config /app/

EXPOSE 8000

# Honest POC output (AC2): the default dispatcher (ContextBuilderRunner) accepts a trigger,
# runs a single node, and returns status="success"/report=None — NO manufactured green RCA
# (the graph is non-convergent until 5-A1 real-transport; SqliteSaver durability is 7.4). The
# deploy proves WIRING (Service up, endpoints reachable, graph executes), not working RCA.
CMD ["uvicorn", "routers.app:app", "--host", "0.0.0.0", "--port", "8000"]
