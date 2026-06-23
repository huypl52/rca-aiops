# `graph/` — LangGraph PE-R graph

Trách nhiệm: 8 node (incident_context_builder, preplanning_playbook_retriever, hypothesis_planner, plan_validator, executor_router, evidence_normalizer, reflector, rca_writer) + edges, compile 1 lần (AD-2).

**One-way (AD-1):** KHÔNG import `routers`.

**Trạng thái:** Story 0.3 ĐÃ implement **graph state spine** — `InvestigationState` TypedDict 13 top-level key (AD-9) + reducer (append+dedupe / upsert-by-id / merge, AD-4/AD-10) + `create_initial_state()` factory + `SCHEMA_VERSION` fail-fast guard (xem `graph/state.py`). Nodes (8 node §3.5) + `StateGraph(...).compile()` ở Epic 3 (Story 3-5 + 1-3/3-2/2-3/4-2/4-3/5-1). KHÔNG compile graph/node/consumer trong Story 0.3 (scope).

**Type-coherence (AD-9):** state = plain JSON-safe TypedDict, KHÔNG bọc Pydantic (Pydantic chỉ ở port `models/`). Nested shape ⊆ port contract — CI gate #3 (`tests/ci/test_gate3_type_coherence.py`) assert shape ⊆ `ci.contract_schema` + round-trip serialize→deserialize deep-equal + JSON-safe invariant.
