# `services/` — Use-case services

Trách nhiệm: ingest, normalize → IncidentTrigger, dispatch, read-store.

**One-way (AD-1/AD-2):** gọi graph qua entry contract (invoke/stream + `investigation_id`); KHÔNG import node/state internals.

**Trạng thái:** SKELETON (Story 0.1) — implement thực ở Epic 1.
