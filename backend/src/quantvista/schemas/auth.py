"""Auth wire DTOs (QV-006). Shared so the generated TS client picks them up.

Email is a plain ``str`` (no `EmailStr`) to avoid pulling in `email-validator`; the
service lower-cases it. Stronger validation can come with a later story.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=200)
    name: str | None = Field(default=None, max_length=200)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=200)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MeResponse(BaseModel):
    user_id: str
    email: str
    name: str | None
    tenant_id: str
    tenant_name: str
    role: str
    entitlements: dict[str, Any]
