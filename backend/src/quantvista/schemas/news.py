"""News wire DTOs (QV-043). Derived fields + the link only — no full article text (03 §1 rule 4)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class NewsItem(BaseModel):
    id: str
    headline: str
    summary: str | None
    source: str | None
    source_url: str | None
    published_at: datetime
