# demo/Dockerfile — ONE lean image for all demo workloads (Story 7.1).
#
# This is the SYSTEM-UNDER-INVESTIGATION (the 5 demo microservices + traffic
# runner), NOT the RCA agent. It is a STANDALONE deployable: it installs ONLY
# fastapi/uvicorn/httpx (NOT the agent's langgraph/qdrant-client/etc.) and copies
# ONLY the demo/ package (never graph/services/routers/models/adapters/tools/eval/
# ci/config) — the standalone boundary is enforced at build time here AND at import
# time by gate #2 (the import-linter `forbidden` contract in pyproject.toml).
#
# ONE image serves all 6 workloads: the 5 services select their module via the
# DEMO_MODULE/DEMO_PORT env (set per Deployment); the traffic-runner overrides the
# command. Build once:
#     docker build -f demo/Dockerfile -t demo/app:latest .
FROM python:3.12-slim

# PYTHONHASHSEED=42 — keeps the live service's hash-seed-bound behavior reproducible
# (the demo-system analog of AD-12; the determinism test proves the code is correct
# across {0,1,42}, this just fixes one for the running container).
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONHASHSEED=42 \
    PYTHONPATH=/app

WORKDIR /app

# Lean runtime deps only — pinned to match pyproject so the live service matches CI.
RUN pip install --no-cache-dir \
      "fastapi==0.138.0" \
      "uvicorn==0.49.0" \
      "httpx==0.28.1"

# Copy ONLY the demo package (standalone — no agent code in this image).
COPY demo/ ./demo/

# Defaults; overridden per-Deployment via env (DEMO_MODULE/DEMO_PORT) or command.
ENV DEMO_MODULE=user \
    DEMO_PORT=8080

EXPOSE 8080
# uvicorn targets demo.services.<module>:app — env-expanded by sh.
CMD ["sh", "-c", "exec uvicorn demo.services.${DEMO_MODULE}:app --host 0.0.0.0 --port ${DEMO_PORT}"]
