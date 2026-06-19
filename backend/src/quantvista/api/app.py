"""FastAPI application factory (the ``api`` runtime role).

Composition root for the HTTP boundary. Responses use the project-standard envelope
(`quantvista.schemas.envelope`). Business routers are added by later stories; QV-002
ships only the health probes needed for the local stack.
"""

from __future__ import annotations

from fastapi import APIRouter, FastAPI

from quantvista.schemas.envelope import Envelope

health_router = APIRouter(prefix="/api/v1", tags=["health"])


@health_router.get("/health", response_model=None)
def health() -> Envelope[dict[str, str]]:
    """Liveness probe — dependency-free so it stays green during boot."""
    return Envelope.ok({"status": "ok"}, meta={})


def create_app() -> FastAPI:
    app = FastAPI(title="QuantVista API", version="0.1.0")
    app.include_router(health_router)
    return app


# ASGI entrypoint for uvicorn: `uvicorn quantvista.api.app:app`.
app = create_app()
