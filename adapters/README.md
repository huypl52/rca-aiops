# `adapters/` — Read-only external clients (AD-3 BLOCKER)

Trách nhiệm: clients read-only — prometheus, loki, k8s, qdrant, topology.

**Read-only boundary (AD-3 BLOCKER, §3.8):** KHÔNG expose write/exec/patch/delete/scale/rollback/restart/remediate. `kubectl debug/exec/patch` KHÔNG tồn tại. Read verbs only (GET cho HTTP APIs; list/read cho K8s REST; query-only cho Qdrant) — no POST/PUT/PATCH/DELETE / mutating K8s verb.

**One-way (AD-1 / gate #2):** KHÔNG import `graph`/`services`/`routers` (back-edge forbidden). MAY import `tools` (forward edge — `ReadOnlyAdapterPort`).

**Story 2.2 (shipped):** 5 source adapter classes (`adapters/readonly.py`) implementing the 8 read methods của `tools.port.ReadOnlyAdapterPort`, over an injectable transport seam (`adapters/transport.py`):

- `ReadOnlyTransport` Protocol — 5 read methods (1 per source), the I/O seam.
- `FakeReadOnlyTransport` — deterministic offline transport (models REAL backend response shapes); used by 2-2 tests.
- `PrometheusAdapter` / `LokiAdapter` / `K8sAdapter` / `QdrantAdapter` / `TopologyAdapter` — real read-only normalization (backend response → tool `RawOutput`, stub-aligned shape) + error envelope on failure (AC3, never raises) + time_window pass-through.
- `CompositeReadOnlyAdapter` — holds all 5 + one transport; implements the FULL `ReadOnlyAdapterPort` (8 methods) → the object a tool receives; satisfies the PORT at runtime.

**DEFERRED (Constrain-note, NOT silent):**
- Real live-stack transport (httpx + qdrant-client, read verbs only) + integration tests → **Epic 7 (7-1/7-2/7-4)**.
- Composition-root wiring (inject the composite into the tool registry at runtime) → **Story 3.5 / app**.
- `executor_router` dispatch → **Story 2.3**. Evidence/error-envelope interpretation → **Story 4.2**.

**Trạng thái:** SHIPPED (Story 2.2) — real read-only adapter logic + transport seam; real live-stack I/O ở Epic 7.
