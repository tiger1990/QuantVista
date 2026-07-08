"""Standard API response envelope.

Every ``/api/v1`` endpoint returns this shape: ``{ success, data, error, meta }``.
Errors set ``success=False, data=None, error={code, message}``. Cursor pagination
metadata goes in ``meta`` (``next_cursor``).

Pydantic generics so FastAPI can derive each endpoint's *full* response schema via
``response_model=Envelope[XResponse]`` — the OpenAPI spec then describes responses, not
just paths/bodies, and the generated frontend client is end-to-end typed (04 §1, contract-first).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

# Canonical error codes → HTTP status (see project-context.md / plans/04-api-contracts.md).
ERROR_STATUS: dict[str, int] = {
    "validation_error": 422,
    "unauthenticated": 401,
    "forbidden": 403,
    "not_found": 404,
    "entitlement_exceeded": 403,
    "rate_limited": 429,
    "conflict": 409,
    "infeasible": 422,
    "upstream_unavailable": 503,
    "internal_error": 500,
}


class Error(BaseModel):
    code: str
    message: str


class Envelope[T](BaseModel):
    success: bool
    data: T | None = None
    error: Error | None = None
    meta: dict[str, Any] | None = None

    @classmethod
    def ok(cls, data: T, *, meta: dict[str, Any] | None = None) -> Envelope[T]:
        return cls(success=True, data=data, meta=meta)

    @classmethod
    def fail(cls, code: str, message: str) -> Envelope[T]:
        return cls(success=False, data=None, error=Error(code=code, message=message))
