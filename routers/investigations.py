"""Read-store router — GET /api/investigations/{investigation_id} (AD-10 #3).

Story 1.4 — AD-10 #3 (trace+report via store, NO sync return) / AD-9 (JSON-safe).

Returns the investigation ``status`` + JSON-safe ``state_snapshot`` + optional
``report`` FROM THE STORE (poll), NOT synchronously. The handler returns
immediately and does NOT block on the investigation running — the client POLLS
the store by ``investigation_id``. This is the read-only projection of the
in-process ``InvestigationStore``; there is no write/remediation path (AD-3).

ONE-WAY (AD-1 / gate #2): imports ``services`` only — MUST NOT import
graph/adapters/tools (gate #2 HARD-FAIL). The router is thin: it projects a store
record into the response model.

Scope (locked 1-4): poll REQUIRED (POC default). SSE = DEFERRED — the spec AC
says "poll hoặc SSE"; poll is sufficient for POC and an SSE endpoint is NOT
implemented here (Constrain note, AC4). Unknown investigation_id → 404 (graceful
read-store lookup miss).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.investigations import default_store

router = APIRouter()


class InvestigationReadResponse(BaseModel):
    """`GET /api/investigations/{id}` response body (AD-10 #3 — poll, no sync).

    ``state_snapshot`` is a JSON-safe bounded projection of the state spine
    (context / next_action / counts — set by the runner, AD-9). ``report`` is
    ``None`` until the rca_writer node (Story 5-1).
    """

    investigation_id: str
    status: str
    state_snapshot: dict[str, Any]
    report: dict[str, Any] | None = None


@router.get(
    "/api/investigations/{investigation_id}",
    response_model=InvestigationReadResponse,
)
def get_investigation(investigation_id: str) -> InvestigationReadResponse:
    """Poll the read-store for an investigation's status + snapshot + report (no sync)."""
    view = default_store().view(investigation_id)
    if view is None:
        # graceful lookup miss — unknown investigation_id (never minted / evicted)
        raise HTTPException(
            status_code=404,
            detail={
                "error": "investigation not found",
                "code": "investigation_not_found",
                "detail": investigation_id,
            },
        )
    return InvestigationReadResponse(
        investigation_id=view.investigation_id,
        status=view.status,
        state_snapshot=view.state_snapshot,
        report=view.report,
    )


__all__ = ["InvestigationReadResponse", "router"]
