"""graph/nodes — PE-R §3.5 node functions (Story 1.3+).

Each §3.5 node is a PURE function ``(state) -> partial-state-dict`` (AD-4:
nodes return PARTIAL state; the ``upsert_*`` / ``append_dedupe_*`` reducers in
``graph.state`` merge it). Nodes never compile the graph (that is Story 3-5
assembly) and never import ``routers`` / ``services`` (one-way AD-1 / gate #2).

Story 1.3 adds the first node — :mod:`graph.nodes.incident_context_builder` (the
§3.5 entry node). The remaining 7 nodes (preplanning_playbook_retriever,
hypothesis_planner, plan_validator, executor_router, evidence_normalizer,
reflector, rca_writer) land in their respective stories.
"""

from graph.nodes.incident_context_builder import (
    build_incident_context,
    incident_context_builder,
)

__all__ = [
    "build_incident_context",
    "incident_context_builder",
]
