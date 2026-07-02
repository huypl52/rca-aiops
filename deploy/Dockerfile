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
#
# PRODUCTION HARDENING (Phase 3, 2026-07-01):
# - Non-root user (appuser:1000) for least-privilege container execution.
# - Structured JSON logging via env var (LOG_LEVEL + uvicorn access log config).
# - /data volume mount point for durable checkpoint storage (PVC-backed in K8s).
FROM python:3.12-slim

ENV PYTHONHASHSEED=42 \
    PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    LOG_LEVEL=INFO

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
COPY routers/ /app/routers/
COPY services/ /app/services/
COPY graph/ /app/graph/
COPY adapters/ /app/adapters/
COPY tools/ /app/tools/
COPY models/ /app/models/
COPY config/ /app/config/
COPY ci/ /app/ci/
COPY demo/ui/ /app/demo/ui/

# Create /data for durable checkpoint storage (PVC mounts here in K8s).
# The FastAPI app serves /ui only when /app/demo/ui exists, so fail the image build
# loudly if the static UI bundle is omitted from the deploy artifact.
RUN test -f /app/demo/ui/index.html \
 && mkdir -p /data \
 && chown 1000:1000 /data /app

# Non-root user for least-privilege container execution.
USER 1000:1000

EXPOSE 8000

# Honest POC output (AC2): the default dispatcher (ContextBuilderRunner) accepts a trigger,
# runs a single node, and returns status="success"/report=None — NO manufactured green RCA
# (the graph is non-convergent until 5-A1 real-transport; SqliteSaver durability is 7.4). The
# deploy proves WIRING (Service up, endpoints reachable, graph executes), not working RCA.
#
# --log-level from env LOG_LEVEL (default INFO); --access-log enables access logs for ops.
CMD ["uvicorn", "routers.app:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info", "--access-log"]
