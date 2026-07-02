"""FastAPI app factory for the RCA ingest gateway (Story 1-1).

Hosts the ingest router and a global exception handler that maps normalizer
domain errors (+ Pydantic validate-on-ingress failures) to the structured error
envelope `{error, code, detail}` (project-context Cat 3 / AD-9). The app factory
keeps this testable via `fastapi.testclient.TestClient` without wiring a uvicorn
server (deploy/runtime = Story 1-4 / Epic 7).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from routers.ingest import router as ingest_router
from routers.investigations import router as investigations_router
from services.durable import wire_durable_dispatcher_if_configured
from services.normalize import NormalizeError

# Demo UI static root (repo-relative). Served only when present — additive, optional.
_DEMO_UI_DIR = Path(__file__).resolve().parent.parent / "demo" / "ui"


def create_app() -> FastAPI:
    """Build the FastAPI app: ingest router + read-store router + error-envelope handlers."""
    app = FastAPI(title="RCA AI Agent POC — ingest", version="0.1.0")
    app.include_router(ingest_router)
    app.include_router(investigations_router)

    # Optional same-origin static serving of the demo UI (demo/ui/). Mounted ONLY when
    # the directory exists, so the app stays importable in environments without it and
    # the API routers above keep priority. Additive read-only surface (no new routes
    # beyond the static mount); does not touch ingest/read-store contracts.
    if _DEMO_UI_DIR.is_dir():
        app.mount("/ui", StaticFiles(directory=str(_DEMO_UI_DIR), html=True), name="demo-ui")

    @app.get("/health")
    async def health() -> dict[str, str]:
        # Lightweight liveness/readiness probe target for Kubernetes.
        # Does NOT check downstream dependencies — that would couple pod lifecycle
        # to external services. TCP/HTTP 200 = process alive and serving.
        return {"status": "ok"}

    @app.exception_handler(NormalizeError)
    async def normalize_error_handler(_: Request, exc: NormalizeError) -> JSONResponse:
        # Domain rejection (missing field / unknown canonical) → 422 envelope.
        return JSONResponse(
            status_code=422,
            content={"error": "normalize rejected", "code": exc.code, "detail": exc.detail},
        )

    @app.exception_handler(ValidationError)
    async def validation_error_handler(_: Request, exc: ValidationError) -> JSONResponse:
        # Pydantic validate-on-ingress failure (bad enum/type/extra on IncidentTrigger)
        # → 422 envelope.
        return JSONResponse(
            status_code=422,
            content={
                "error": "trigger field validation failed",
                "code": "invalid_trigger_field",
                "detail": jsonable_encoder(exc.errors()),
            },
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_error_handler(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Malformed request body (not a JSON object, wrong envelope shape) → 422
        # envelope. Without this FastAPI returns its default {"detail": [...]}, which
        # would break the unified {error, code, detail} contract.
        return JSONResponse(
            status_code=422,
            content={
                "error": "request body validation failed",
                "code": "invalid_request_body",
                "detail": jsonable_encoder(exc.errors()),
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
        # Catch-all defense-in-depth: never leak a stack trace / default 500 body.
        # Payload size bounds (DoS) are deferred to Story 1-4 / Epic 7 (deploy).
        del exc
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal error",
                "code": "internal_error",
                "detail": "unexpected internal error",
            },
        )

    return app


# Module-level app for `uvicorn routers.app:app` (deploy = Story 1-4 / Epic 7).
app = create_app()


# Wire the durable path at module load (no-op unless RCA_CHECKPOINT_DB is set). The wiring lives
# in ``services.durable`` (the composition root): routers is FORBIDDEN from importing ``graph``
# (``test_routers_module_does_not_import_forbidden_layers`` mirrors gate #2 — routers imports
# only fastapi/pydantic/models/services), so it delegates to services (which may import graph,
# forward — services(1)→graph(2)). Called AFTER `app = create_app()` so the base app is always
# importable; the dispatcher swap is additive and does not touch the FastAPI factory itself.
wire_durable_dispatcher_if_configured()
