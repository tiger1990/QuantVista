"""Saved-screen wire DTOs (QV-039). ``04`` §3.4 — ``POST /screens { name, criteria }``."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from quantvista.schemas.screener import FilterClause


class ScreenCriteria(BaseModel):
    """A runnable screener spec (a ``/screener`` body sans ``limit``/``cursor``)."""

    market: str = "NSE"
    filters: list[FilterClause] = Field(default_factory=list)
    sort: str | None = None


class SaveScreenRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    criteria: ScreenCriteria


class SavedScreen(BaseModel):
    id: str
    name: str
    criteria: dict[str, Any]
    created_at: str
