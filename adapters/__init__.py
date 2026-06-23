"""Read-only external clients — prometheus, loki, k8s, qdrant, topology (AD-3 BLOCKER).

Story 2.2 ships the 5 source adapter classes (``adapters/readonly.py``) implementing the 8 read
methods of ``tools.port.ReadOnlyAdapterPort``, over an injectable transport seam
(``adapters/transport.py``). The composite (``CompositeReadOnlyAdapter``) is the object a tool
receives and satisfies the PORT (``tools/`` UNCHANGED — AC5 seam from 2-1 held). Import it explicitly
from ``adapters.readonly`` (kept out of the package eager-import to keep ``import adapters`` light).

ONE-WAY (AD-1 / gate #2): MUST NOT import graph/services/routers (back-edge forbidden); MAY import
tools (forward edge). Read-only (§3.8): MUST NOT expose write/exec/patch/delete/scale/rollback/
restart/remediate — enforced statically by CI gate #1 (scans adapters/) + leader no-hidden-write-path
grep (no POST/PUT/PATCH/DELETE / mutating K8s verb). Real live-stack transport + integration = Epic 7.
"""
