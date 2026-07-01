"""LangGraph PE-R graph package (AD-9 / AD-2).

Story 0.3 implements the **graph state spine**:
  - `InvestigationState` — plain JSON-safe `TypedDict`, 14 top-level keys (AD-9)
  - reducer functions (append+dedupe / upsert-by-id / merge) wired via
    `Annotated[<type>, <reducer>]` (AD-4 / AD-10)
  - `create_initial_state()` factory + `SCHEMA_VERSION` / `assert_schema_version`
    fail-fast guard

The 8 PE-R nodes (incident_context_builder, preplanning_playbook_retriever,
hypothesis_planner, plan_validator, executor_router, evidence_normalizer,
reflector, rca_writer) + edges + `StateGraph(...).compile()` are added by
Epic 3 (Story 3-5 compiled-graph assembly, plus 1-3 / 3-2 / 2-3 / 4-2 / 4-3 /
5-1). Story 0.3 only defines state + reducers + factory — it does NOT compile
the graph, implement nodes, or wire consumers (routers ingest = Story 1-1).

ONE-WAY (AD-1): MUST NOT import `routers`/`services`. `graph.state` imports the
`models` port contract + `ci.contract_schema` (non-layer) + 3rd-party/stdlib
only — gate #2 (dependency-direction) stays green.
"""

from graph.state import (
    SCHEMA_VERSION,
    InvestigationState,
    JsonValue,
    append_dedupe_evidence,
    append_dedupe_playbook_hits,
    append_dedupe_tool_calls,
    append_safety_flags,
    assert_schema_version,
    create_initial_state,
    upsert_context,
    upsert_hypotheses,
)

__all__ = [
    "InvestigationState",
    "JsonValue",
    "SCHEMA_VERSION",
    "append_dedupe_evidence",
    "append_dedupe_playbook_hits",
    "append_dedupe_tool_calls",
    "append_safety_flags",
    "assert_schema_version",
    "create_initial_state",
    "upsert_context",
    "upsert_hypotheses",
]
