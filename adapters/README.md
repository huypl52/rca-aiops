# `adapters/` — Read-only external clients (AD-3)

Trách nhiệm: clients read-only — prometheus, loki, k8s, qdrant, topology.

**Read-only boundary (AD-3 BLOCKER, §3.8):** KHÔNG expose write/exec/patch/delete/scale/rollback/restart/remediate. `kubectl debug/exec/patch` KHÔNG tồn tại.

**One-way (AD-1):** KHÔNG import `graph` hoặc `services`.

**Trạng thái:** SKELETON (Story 0.1) — clients thực ở Story 2.2.
