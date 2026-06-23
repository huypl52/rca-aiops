# `tools/` — Read-only tool registry + executor_router (AD-3)

Trách nhiệm: tool registry (read-only executors, tool set §3.6 = 7 row/10 function) + executor_router dispatch (set {Prometheus, Loki, Kubernetes, playbook, topology}).

**Read-only boundary (AD-3 BLOCKER):** KHÔNG expose write/exec/patch/delete/scale/rollback/restart/remediate. Enforced ở mức registry, KHÔNG dựa LLM (FR-5).

**One-way (AD-1):** KHÔNG import `graph` hoặc `services`.

**Trạng thái:** SKELETON (Story 0.1) — registry thực + deny-set enforcement ở Story 2.1, dispatch ở Story 2.3.
