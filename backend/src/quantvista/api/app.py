"""FastAPI application factory (the ``api`` runtime role).

Composition root for the HTTP boundary. Responses use the project-standard envelope
(`quantvista.schemas.envelope`). Domain errors are mapped to canonical envelope codes.
"""

from __future__ import annotations

from fastapi import APIRouter, FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from quantvista.api.routes import router as auth_router
from quantvista.identity.models import (
    EmailAlreadyExists,
    EntitlementExceeded,
    InvalidCredentials,
    InvalidRefreshToken,
)
from quantvista.schemas.envelope import ERROR_STATUS, Envelope

health_router = APIRouter(prefix="/api/v1", tags=["health"])


@health_router.get("/health", response_model=None)
def health() -> Envelope[dict[str, str]]:
    """Liveness probe — dependency-free so it stays green during boot."""
    return Envelope.ok({"status": "ok"}, meta={})


def _fail(code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=ERROR_STATUS.get(code, 500),
        content=jsonable_encoder(Envelope.fail(code, message)),
    )


def _register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(EmailAlreadyExists)
    async def _conflict(_req: Request, _exc: EmailAlreadyExists) -> JSONResponse:
        return _fail("conflict", "email is already registered")

    @app.exception_handler(InvalidCredentials)
    async def _unauth(_req: Request, _exc: InvalidCredentials) -> JSONResponse:
        return _fail("unauthenticated", "invalid credentials or token")

    @app.exception_handler(InvalidRefreshToken)
    async def _bad_refresh(_req: Request, _exc: InvalidRefreshToken) -> JSONResponse:
        return _fail("unauthenticated", "invalid or expired session")

    @app.exception_handler(EntitlementExceeded)
    async def _entitlement(_req: Request, exc: EntitlementExceeded) -> JSONResponse:
        return _fail("entitlement_exceeded", f"your plan does not include '{exc.feature}'")

    @app.exception_handler(RequestValidationError)
    async def _validation(_req: Request, exc: RequestValidationError) -> JSONResponse:
        return _fail("validation_error", "request validation failed")


def create_app() -> FastAPI:
    app = FastAPI(title="QuantVista API", version="0.1.0")
    app.include_router(health_router)
    app.include_router(auth_router)
    _register_error_handlers(app)
    return app


# ASGI entrypoint for uvicorn: `uvicorn quantvista.api.app:app`.
app = create_app()
