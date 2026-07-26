"""Saved-screen wire DTOs (QV-039). ``04`` §3.4 — ``POST /screens { name, criteria }``."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from quantvista.schemas.screener import FilterClause


class ScreenCriteria(BaseModel):
    """A runnable screener spec (a ``/screener`` body sans ``limit``/``cursor``)."""

    model_config = ConfigDict(extra="forbid")  # reject unknown fields (QV-079)
    market: str = "NSE"
    filters: list[FilterClause] = Field(default_factory=list)
    sort: str | None = None


class SaveScreenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")  # reject unknown fields (QV-079)
    name: str = Field(min_length=1, max_length=120)
    criteria: ScreenCriteria


class SavedScreen(BaseModel):
    id: str
    name: str
    criteria: dict[str, Any]
    created_at: str
