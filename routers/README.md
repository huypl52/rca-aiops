# `routers/` — FastAPI routers (ingest + read-store)

Trách nhiệm: tiếp nhận trigger đa nguồn (POST /api/alerts/prometheus, /api/alerts/grafana, /api/events/kubernetes) + read-store (/api/investigations/{id}).

**One-way (AD-1):** được phép import `services`. KHÔNG import trực tiếp `graph` internals.

**Trạng thái:** SKELETON (Story 0.1) — implement thực ở Epic 1.
